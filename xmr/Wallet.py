from __future__ import annotations

from xmr.Mnemonic import Mnemonic
from xmr.stealth.options import get_ua, get_viewport
from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth
import asyncio
from xmr.exceptions import TransactionException
# import requests
import typing


class Wallet:
    def __init__(self, mnemonic: Mnemonic):#, address: str, viewkey: str):
        self._browser = None
        self._playwright = None
        
        if type(mnemonic) != Mnemonic:
            raise RuntimeError("Mnemonic key not passed into wallet.")
    
        self._mnemonic = mnemonic    
        #self._addr = address
        #self._viewKey = viewkey
    
    ### STATICS
    @staticmethod
    async def generateBulk(outfp: str, total: int = 50, max_workers: int = 5) -> list[Wallet]:
        semaphore = asyncio.Semaphore(max_workers)

        wallets = []
        async def worker():
            async with semaphore:
                wallet = await Wallet.generateNew()
                wallets.append(wallet)
                mnemonic = wallet.getMnemonic()
                # Append immediately
                with open(outfp, "a") as f:
                    f.write(mnemonic + "\n")

        # Create tasks
        tasks = [asyncio.create_task(worker()) for _ in range(total)]
        await asyncio.gather(*tasks)
        
        return wallets
    
    
    @staticmethod
    def loadWallets(fp: str) -> list[Wallet]:
        wallets = []
        with open(fp, "r") as f:
            for line in f.readlines():
                if line.strip() == "": continue
                mnemonic = Mnemonic(line)
                wallet = Wallet(mnemonic)
                wallets.append(wallet)
        return wallets
            
    
    @staticmethod
    async def generateNew():
        async with Stealth().use_async(async_playwright()) as p:
            b = await p.chromium.launch(headless=True)
            context = await b.new_context(
                user_agent=get_ua(),
                viewport=get_viewport(),
                java_script_enabled=True,
                locale="en-US"
            )
            
            page = await context.new_page()
            
            
            await page.goto("https://wallet.mymonero.com")
            await page.click("a:has-text('Create new wallet')")
            await page.click("a:has-text('GOT IT!')")
            await page.click("#rightBarButtonHolderView > div")
            
            mnemonic = (await (await page.query_selector("div.mnemonic-container")).inner_text())
            mnemonic = Mnemonic(mnemonic)

            wallet = Wallet(mnemonic)
            
            print(f"Generated {wallet}")

            return wallet

    ### |END| STATICS

        
    ### PAGE (ENTER EXIT) FUNCTIONALITIES
    async def _login(self) -> _ActiveBrowserWallet:
        p = await async_playwright().start()
        b = await p.chromium.launch(headless=True)
        context = await b.new_context(
            user_agent=get_ua(),
            viewport=get_viewport(),
            java_script_enabled=True,
            locale="en-US"
        )
        
        self._playwright = p
        self._browser = b
        
        page = await context.new_page()
        await page.goto("https://wallet.mymonero.com")
        
        await page.click("a:has-text('Use existing wallet')")
        await page.type("textarea.existing_key", self.getMnemonic())
        await page.click("#rightBarButtonHolderView > div")
        
        
        return await _ActiveBrowserWallet.create(page, self._mnemonic)
    
    
    ## |END| PAGE (ENTER EXIT) FUNCTIONALITIES
    
    
    
    def getMnemonic(self) -> str:
        return self._mnemonic.getRawWords()
    
    async def __aenter__(self) -> _ActiveBrowserWallet:
        return await self._login()
        
    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()

    def __str__(self):
        return f"Wallet('{' '.join(self._mnemonic.getWords()[:3])}'...)"
            


class _ActiveBrowserWallet:
    def __init__(self, page: Page, mnemonic: Mnemonic, staticinfo):
        self._page = page
        self._mnemonic = mnemonic
        self._staticinfo = staticinfo
    
    @classmethod
    async def create(cls, page: Page, mnemonic: Mnemonic):
        staticinfo = await cls._getStaticInfo(page, mnemonic)
        return cls(page, mnemonic, staticinfo)
    
    @staticmethod
    async def _getStaticInfo(page: Page, mnemonic: Mnemonic) -> dict:
        ret = {"Address": None, "SecretViewKey": None, "SecretSpendKey": None, "SecretMnemonic": mnemonic}
        
        await page.click("div.utility:has(div.walletIcon)")
        await page.click("a.__infoDisclosing_doNotUseForDisclosureToggling")
        
        address_el = await page.wait_for_selector("#stack-view-stage-view > div > div:nth-child(3) > div > div:nth-child(1) > div > span.field_value", state="visible")
        address = await address_el.inner_text()
        
        secretviewkey_el = await page.wait_for_selector("#stack-view-stage-view > div > div:nth-child(3) > div > div:nth-child(2) > div > span.field_value", state="visible")
        secretviewkey = await secretviewkey_el.inner_text()

        secretspendkey_el = await page.wait_for_selector("#stack-view-stage-view > div > div:nth-child(3) > div > div:nth-child(3) > div > span.field_value", state="visible")
        secretspendkey = await secretspendkey_el.inner_text()
        
        ret["Address"] = address
        ret["SecretViewKey"] = secretviewkey
        ret["SecretSpendKey"] = secretspendkey
        ret["SecretMnemonic"] = mnemonic.getRawWords()
        
        return ret
    
    
    @property
    def address(self) -> str:
        return self._staticinfo["Address"]
    
    @property
    def secretViewKey(self) -> str:
        return self._staticinfo["SecretViewKey"]
    
    @property
    def secretSpendKey(self) -> str:
        return self._staticinfo["SecretSpendKey"]
    
    @property
    def secretMnemonic(self) -> str:
        return self._staticinfo["SecretMnemonic"]
        
    async def getBalance(self) -> float:
        await self._page.click("div#tabButton-send") 
        
        return float((await (await self._page.wait_for_selector("div.selectionDisplayCellView > div.description-label")).inner_text()).strip(" XMR"))
    
    async def send(self, amount: float, to_address: str, priority: typing.Literal["low", "medium", "hight", "very high"]):
        await self._set_priority(priority=priority)
        
        await self._page.type("td > div > input", str(amount))
        await self._page.type("div.contactPicker_Lite > input", to_address)
        
        await self._page.click("#rightBarButtonHolderView > div")
        
        # check error
        errmsg = (await (await self._page.wait_for_selector("#stack-view-stage-view > div > div.inlineMessageDialogLayer.wantsCloseButton")).inner_text()).strip()
        if errmsg:
            raise TransactionException(errmsg)
        
    
    async def getTransferFee(self, priority: typing.Literal["low", "medium", "hight", "very high"]) -> float:
        await self._set_priority(priority=priority)
        
        fee_el = await self._page.wait_for_selector("#stack-view-stage-view > div > div:nth-child(2) > table > tr > td > div > div:nth-child(8) > span")
        fee = await fee_el.inner_text()
        fee = float(fee.lower().strip(" xmr est. fee").strip("+ "))
        
        return fee
    
    async def _set_priority(self, priority: typing.Literal["low", "medium", "hight", "very high"]) -> None:
        match priority.lower():
            case "low":
                await self._page.select_option("div:nth-child(6) select", value="1")
            case "medium":
                await self._page.select_option("div:nth-child(6) select", value="2")
            case "high":
                await self._page.select_option("div:nth-child(6) select", value="3")
            case "very high":
                await self._page.select_option("div:nth-child(6) select", value="4")
        
    
    
    def __str__(self) -> str:
        return f"ActiveWallet({self.address})"


__all__ = [ "Wallet" ]