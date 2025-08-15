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
        _p: Playwright instance used for launching the browser.
        _b: Playwright Browser instance for session management.
        _mnemonic (Mnemonic): The wallet's mnemonic phrase object.
        _address (str): Wallet's Monero address.
        _viewKey (str): Wallet's secret view key.
        _spendKey (str): Wallet's secret spend key.
    """

    def __init__(self, mnemonic: Mnemonic, address: str, secretViewKey: str, secretSpendKey: str):
        """Initialize a Wallet with a mnemonic phrase, address, and keys.

        Args:
            mnemonic (Mnemonic): The wallet's mnemonic phrase.
            address (str): Wallet's public Monero address.
            secretViewKey (str): Secret view key associated with the wallet.
            secretSpendKey (str): Secret spend key associated with the wallet.

        Raises:
            RuntimeError: If mnemonic is not an instance of Mnemonic.
        """
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
        """Generate multiple wallets concurrently and save mnemonics to a file.

        Args:
            outfp (str): Path to output file for storing wallet information.
            max_workers (int, optional): Maximum number of concurrent workers. Defaults to 5.
            total (int, optional): Total number of wallets to generate. Defaults to 50.

        Returns:
            list[Wallet]: A list of generated Wallet instances.
        """
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
        """Load wallets from a file containing mnemonic phrases.

        Args:
            fp (str): Path to the file containing wallet mnemonics and keys.

        Returns:
            list[Wallet]: A list of Wallet instances loaded from file.
        """
        wallets = []
        with open(fp, "r") as f:
            for line in f.readlines():
                if line.strip() == "" or line.startswith("#"):
                    continue
                raw_mnemonic, *args = line.split("|")
                
                wallets.append(Wallet(Mnemonic(raw_mnemonic.strip()), *[arg.strip() for arg in args]))
        return wallets

    @staticmethod
    async def _generateWalletWithRetry(context, max_retries=5):
        """Attempt to generate a wallet with retries on failure.

        Args:
            context: Playwright browser context.
            max_retries (int, optional): Maximum number of retries. Defaults to 5.

        Returns:
            Wallet: A successfully generated wallet.

        Raises:
            RuntimeError: If wallet generation fails after max_retries.
        """
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
        """Generate a new wallet using MyMonero's online wallet UI.

        Args:
            page (Page, optional): Playwright page object. If None, a new browser will be launched.

        Returns:
            Wallet: A newly generated Wallet instance.
        """
        p = None
        b = None
        if page == None:
            p = await async_playwright().start()

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
        """Return the wallet's mnemonic phrase as a string."""
        return self._mnemonic.getRawWords()

    @property
    def address(self) -> str:
        """Return the wallet's Monero address."""
        return self._address

    @property
    def secretViewKey(self) -> str:
        """Return the wallet's secret view key."""
        return self._viewKey

    @property
    def secretSpendKey(self) -> str:
        """Return the wallet's secret spend key."""
        return self._spendKey

    async def __aenter__(self) -> _ActiveBrowserWallet:
        """Log into MyMonero using the wallet's mnemonic.

        Returns:
            _ActiveBrowserWallet: An active browser wallet session.
        """
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

        send_tab_clickable = False
        button = None
        for _ in range(50):
            button = await page.wait_for_selector("div#tabButton-send", state="visible")
            if "opacity: 1;" in (await button.get_attribute("style")):
                send_tab_clickable = True
                break
                
            await asyncio.sleep(0.1)
        
        if not send_tab_clickable:
            raise RuntimeError("An unknown error occurred.")
        
        await button.click()

        return _ActiveBrowserWallet(page, self._mnemonic, self.address, self.secretViewKey, self.secretSpendKey)

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Close the Playwright browser session."""
        if self._b:
            await self._b.close()
            self._b = None
        if self._p:
            await self._p.stop()
            self._p = None

    def __str__(self):
        """Return a shortened string representation of the wallet."""
        return f"Wallet('{' '.join(self._mnemonic.getWords()[:3])}'...)')"


class _ActiveBrowserWallet:
    """Represents an active browser session for a loaded Monero wallet.

    Attributes:
        _page (Page): Playwright page object for browser interaction.
        _mnemonic (Mnemonic): Wallet's mnemonic phrase object.
        _address (str): Wallet's Monero address.
        _viewkey (str): Wallet's secret view key.
        _spendkey (str): Wallet's secret spend key.
    """

    def __init__(self, page: Page, mnemonic: Mnemonic, address: str, secretviewkey: str, secretspendkey: str):
        """Initialize an active browser wallet session.

        Args:
            page (Page): Playwright page object.
            mnemonic (Mnemonic): Wallet's mnemonic phrase.
            address (str): Wallet's Monero address.
            secretviewkey (str): Wallet's secret view key.
            secretspendkey (str): Wallet's secret spend key.
        """
        self._page = page
        self._mnemonic = mnemonic
        self._address = address
        self._viewkey = secretviewkey
        self._spendkey = secretspendkey

    @property
    def address(self) -> str:
        """Return the wallet's Monero address."""
        return self._address

    @property
    def secretViewKey(self) -> str:
        """Return the wallet's secret view key."""
        return self._viewkey

    @property
    def secretSpendKey(self) -> str:
        """Return the wallet's secret spend key."""
        return self._spendkey

    @property
    def secretMnemonic(self) -> Mnemonic:
        """Return the wallet's mnemonic phrase."""
        return self._mnemonic

    async def getBalance(self) -> float:
        """Retrieve the current XMR balance from the wallet UI.

        Returns:
            float: The wallet's balance in XMR.
        """
        balance = None
        for _ in range(50):
            try:
                balance = float((await (await self._page.wait_for_selector("div.selectionDisplayCellView > div.description-label")).inner_text()).strip(" XMR"))
                break
            except ValueError:
                await asyncio.sleep(0.1)
        
        return balance

    async def send(self, amount: float, to_address: str, priority: typing.Literal["low", "medium", "hight", "very high"]) -> None:
        """Send Monero to another address.

        Args:
            amount (float): Amount of XMR to send.
            to_address (str): Destination Monero address.
            priority (Literal): Transaction priority ("low", "medium", "high", "very high").

        Raises:
            TransactionException: If the transaction fails or returns an error message.
        """
        await self._set_priority(priority=priority)
        
        await self._page.fill("td > div > input", "")
        await self._page.type("td > div > input", str(amount))
        await self._page.fill("div.contactPicker_Lite > input", "")
        await self._page.type("div.contactPicker_Lite > input", to_address)
        await self._page.click("#rightBarButtonHolderView > div")

        errmsg = (await (await self._page.wait_for_selector(
            "#stack-view-stage-view > div > div.inlineMessageDialogLayer.wantsCloseButton")).inner_text()).strip()
        if errmsg:
            raise TransactionException(errmsg)

    async def getTransferFee(self, priority: typing.Literal["low", "medium", "hight", "very high"]) -> float:
        """Get the estimated fee for a transaction at a given priority.

        Args:
            priority (Literal): Transaction priority ("low", "medium", "high", "very high").

        Returns:
            float: Estimated transaction fee in XMR.
        """
        fee = None
        for _ in range(50):
            await self._set_priority(priority=priority)
            fee = await (await self._page.wait_for_selector(
                "#stack-view-stage-view > div > div:nth-child(2) > table > tr > td > div > div:nth-child(8) > span")).inner_text()
            try:
                fee = float(fee.lower().strip(" xmr est. fee").strip("+ "))
                break
            except ValueError:
                await asyncio.sleep(0.1)
        return fee

    async def _set_priority(self, priority: typing.Literal["low", "medium", "hight", "very high"]) -> None:
        """Set transaction priority in the UI.

        Args:
            priority (Literal): Transaction priority ("low", "medium", "high", "very high").
        """
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
        """Return a string representation of the active wallet."""
        return f"ActiveWallet({self.address})"
    

__all__ = [ "Wallet" ]
