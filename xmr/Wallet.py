from __future__ import annotations
from xmr.Mnemonic import Mnemonic
from xmr.stealth.options import get_ua, get_viewport
from playwright.async_api import async_playwright, Page
from xmr.exceptions import TransactionException
import asyncio
import typing
import random

class Wallet:
    """Represents a Monero wallet, capable of generating, loading, and interacting
    with MyMonero's browser-based wallet UI via Playwright.

    Attributes:
        _browser: Playwright Browser instance for session management.
        _playwright: Playwright instance for browser automation.
        _mnemonic (Mnemonic): The wallet's mnemonic phrase object.
    """

    def __init__(self, mnemonic: Mnemonic, address: str, secretViewKey: str, secretSpendKey: str):
        """Initialize a Wallet with a mnemonic phrase."""
        if type(mnemonic) != Mnemonic:
            raise RuntimeError("Mnemonic key not passed into wallet.")
        self._p = None
        self._b = None
        self._mnemonic = mnemonic
        self._address = address
        self._viewKey = secretViewKey
        self._spendKey = secretSpendKey

    @staticmethod
    async def generateBulk(outfp: str, max_workers: int = 5, total: int = 50) -> list[Wallet]:
        """Generate multiple wallets concurrently and save mnemonics to a file."""
        semaphore = asyncio.Semaphore(max_workers)
        wallets = []
        file_lock = asyncio.Lock()

        with open(outfp, "w") as f:
            f.write("# Mnemonic | Address | secretViewKey | secretSpendKey\n")

        p = await async_playwright().start()
        b = await p.chromium.launch(headless=True)
        context = await b.new_context(
            user_agent=get_ua(),
            viewport=get_viewport(),
            java_script_enabled=True,
            locale="en-US"
        )

        async def worker():
            async with semaphore:
                wallet = await Wallet._generateWalletWithRetry(context)
                wallets.append(wallet)
                async with file_lock:
                    with open(outfp, "a") as f:
                        f.write(f"{wallet.mnemonic} | {wallet.address} | {wallet.secretViewKey} | {wallet.secretSpendKey}\n")


        tasks = [asyncio.create_task(worker()) for _ in range(total)]
        await asyncio.gather(*tasks)
        
        await b.close()
        await p.stop()
        
        return wallets

    @staticmethod
    def loadWallets(fp: str) -> list[Wallet]:
        """Load wallets from a file containing mnemonic phrases."""
        wallets = []
        with open(fp, "r") as f:
            for line in f.readlines():
                if line.strip() == "" or line.startswith("#"):
                    continue
                raw_mnemonic, *args = line.split("|")
                
                wallets.append(Wallet(Mnemonic(raw_mnemonic), *args))
        return wallets

    @staticmethod
    async def _generateWalletWithRetry(context, max_retries=5):
        for attempt in range(max_retries):
            try:
                page = await context.new_page()
                wallet = await Wallet.generateNew(page)
                await page.close()
                return wallet
            except Exception as e:
                print(f"Error generating wallet (attempt {attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(3 + random.uniform(0, 2))
        raise RuntimeError("Failed to generate wallet after several retries.")


    @staticmethod
    async def generateNew(page: Page = None):
        """Generate a new wallet using MyMonero's online wallet."""
        p = None
        b = None
        if page == None:
            p = await async_playwright().start()

            b = await p.chromium.launch(headless=False)

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
        await asyncio.sleep(random.uniform(0.5, 1.5))

        mnemonic = (await (await page.query_selector("div.mnemonic-container")).inner_text())
        mnemonic = Mnemonic(mnemonic)
        
        await asyncio.sleep(random.uniform(3, 5))
        await page.reload()
        await page.click("a:has-text('Use existing wallet')")
        await page.type("textarea.existing_key", mnemonic.getRawWords())
        await page.click("#rightBarButtonHolderView > div")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        
        await page.click("div.utility:has(div.walletIcon)")
        await page.click("a.__infoDisclosing_doNotUseForDisclosureToggling")

        address = await (await page.wait_for_selector(
            "#stack-view-stage-view > div > div:nth-child(3) > div > div:nth-child(1) > div > span.field_value",
            state="visible")).inner_text()

        secretviewkey = await (await page.wait_for_selector(
            "#stack-view-stage-view > div > div:nth-child(3) > div > div:nth-child(2) > div > span.field_value",
            state="visible")).inner_text()

        secretspendkey = await (await page.wait_for_selector(
            "#stack-view-stage-view > div > div:nth-child(3) > div > div:nth-child(3) > div > span.field_value",
            state="visible")).inner_text()

        wallet = Wallet(mnemonic, address, secretviewkey, secretspendkey)
        print(f"Generated {wallet}")
        
        if b != None:
            await b.close()
        if p != None:
            await p.stop()
        
        return wallet


    @property
    def mnemonic(self) -> str:
        return self._mnemonic.getRawWords()

    @property
    def address(self) -> str:
        return self._address

    @property
    def secretViewKey(self) -> str:
        return self._viewKey

    @property
    def secretSpendKey(self) -> str:
        return self._spendKey

    async def __aenter__(self) -> _ActiveBrowserWallet:
        """Log into MyMonero using the wallet's mnemonic."""
        self._p = await async_playwright().start()
        self._b = await self._p.chromium.launch(headless=True)

        context = await self._b.new_context(
            user_agent=get_ua(),
            viewport=get_viewport(),
            java_script_enabled=True,
            locale="en-US"
        )

        page = await context.new_page()
        await page.goto("https://wallet.mymonero.com")
        await page.click("a:has-text('Use existing wallet')")
        await page.type("textarea.existing_key", self.mnemonic)
        await page.click("#rightBarButtonHolderView > div")

        return await _ActiveBrowserWallet.create(page, self._mnemonic)

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def __str__(self):
        return f"Wallet('{' '.join(self._mnemonic.getWords()[:3])}'...)')"


class _ActiveBrowserWallet:
    """Represents an active browser session for a loaded Monero wallet."""

    def __init__(self, page: Page, mnemonic: Mnemonic, address: str, secretviewkey: str, secretspendkey: str):
        self._page = page
        self._mnemonic = mnemonic
        self._address = address
        self._viewkey = secretviewkey
        self._spendkey = secretspendkey


    @property
    def address(self) -> str:
        """Wallet's primary Monero address."""
        return self._address

    @property
    def secretViewKey(self) -> str:
        """Wallet's secret view key."""
        return self._viewkey

    @property
    def secretSpendKey(self) -> str:
        """Wallet's secret spend key."""
        return self._spendkey

    @property
    def secretMnemonic(self) -> Mnemonic:
        """Wallet's mnemonic phrase."""
        return self._mnemonic

    async def getBalance(self) -> float:
        """Retrieve the current XMR balance."""
        await self._page.click("div#tabButton-send")
        return float((await (await self._page.wait_for_selector(
            "div.selectionDisplayCellView > div.description-label")).inner_text()).strip(" XMR"))

    async def send(self, amount: float, to_address: str, priority: typing.Literal["low", "medium", "hight", "very high"]):
        """Send Monero to another address."""
        await self._set_priority(priority=priority)
        await self._page.type("td > div > input", str(amount))
        await self._page.type("div.contactPicker_Lite > input", to_address)
        await self._page.click("#rightBarButtonHolderView > div")

        errmsg = (await (await self._page.wait_for_selector(
            "#stack-view-stage-view > div > div.inlineMessageDialogLayer.wantsCloseButton")).inner_text()).strip()
        if errmsg:
            raise TransactionException(errmsg)

    async def getTransferFee(self, priority: typing.Literal["low", "medium", "hight", "very high"]) -> float:
        """Get the estimated fee for a transaction at a given priority."""
        await self._set_priority(priority=priority)
        fee = await (await self._page.wait_for_selector(
            "#stack-view-stage-view > div > div:nth-child(2) > table > tr > td > div > div:nth-child(8) > span")).inner_text()
        return float(fee.lower().strip(" xmr est. fee").strip("+ "))

    async def _set_priority(self, priority: typing.Literal["low", "medium", "hight", "very high"]) -> None:
        """Set transaction priority in the UI."""
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