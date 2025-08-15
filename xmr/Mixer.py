from dataclasses import dataclass
from xmr.Wallet import Wallet
import random
from xmr.exceptions import TransactionException
import asyncio


@dataclass
class WalletChain:
    """Represents a transfer path from a source wallet, through optional middlemen, to a destination wallet."""
    from_wallet: Wallet
    middlemen: list[Wallet]
    to_wallet: Wallet
    
TRANSFER_APPROX_MINS = 25

class DominoMixer:
    """
    Monero mixer that transfers funds sequentially through multiple wallets.

    Each transfer triggers the next, forming a chain of transactions that 
    eventually delivers the funds to the target wallet. The process is 
    similar to dominoes falling one after another, ensuring a step-by-step 
    movement rather than all-at-once transfers.
    """
    
    def __init__(self, wallet_chain: WalletChain):
        wallet_chain.middlemen = wallet_chain.middlemen.copy()
        random.shuffle(wallet_chain.middlemen)
        self._chain = wallet_chain
    
    
    async def start(self, amount: float, max_attempts: int = 5) -> None:
        path = self._chain.middlemen + [self._chain.to_wallet]
        current_wallet = self._chain.from_wallet
        print(f"Domino mixing will take high-approx {self.approxMinutes}mins.")

        for i, next_wallet in enumerate(path):
            async with current_wallet as wallet:
                # calculate fees & balance
                transferFee = await wallet.getTransferFee(priority="low")
                balance = await wallet.getBalance()
                if balance < amount + transferFee * (self.transfersN - i):
                    raise TransactionException("Not enough balance for transfer + fee")

                for attempt in range(max_attempts):
                    try:
                        await wallet.send(amount=amount, to_address=next_wallet.address, priority="low")
                        break
                    except TransactionException as e:
                        print(f"Attempt {attempt+1} failed: {e}")
                        await asyncio.sleep(3)
                else:
                    raise TransactionException(f"Failed to send from {current_wallet.address} to {next_wallet.address} after {max_attempts} attempts")
                print(f"Transferred {amount} XMR from {current_wallet.address} to {next_wallet.address}")
        
            current_wallet = next_wallet  # move to the next wallet
            await asyncio.sleep(60*TRANSFER_APPROX_MINS)    
            
        
    
    @property
    def transfersN(self) -> int:
        return 1+len(self._chain.middlemen)
    
    @property
    def approxMinutes(self) -> int:
        return self.transfersN*TRANSFER_APPROX_MINS



class LeafwayMixer:
    def __init__(self, wallet_chain: WalletChain):
        wallet_chain.middlemen = wallet_chain.middlemen.copy()
        random.shuffle(wallet_chain.middlemen)
        self._chain = wallet_chain

    async def start(self, amount: float, max_attempts: int = 5) -> None:
        print(f"Leafway mixing will take high-approx {self.approxMinutes}mins.")
        
        async with self._chain.from_wallet as from_wallet:
            transferFee = await from_wallet.getTransferFee(priority="low")
            balance = await from_wallet.getBalance()
            if balance < amount + transferFee*self.transfersN:
                raise TransactionException("Not enough balance for transfer + fee")

            transfer_amount = amount / len(self._chain.middlemen)
            
            for middleman in self._chain.middlemen:
                for _ in range(max_attempts):
                    try:
                        await from_wallet.send(transfer_amount, middleman.address, priority="low")
                        break
                    except TransactionException:
                        await asyncio.sleep(3.5)
                print(f"Transferred from main[{from_wallet.address}] to middleman[{middleman.address}]")        
                await asyncio.sleep(random.uniform(5, 10))
        
        print(f"Waiting for {TRANSFER_APPROX_MINS} mins so every start->middleman transfer goes through.")        
        await asyncio.sleep(TRANSFER_APPROX_MINS*60)
        
        for middleman in self._chain.middlemen:
            async with middleman as from_wallet:
                transferFee = await from_wallet.getTransferFee(priority="low")
                balance = await from_wallet.getBalance()
                transfer_amount = balance-transferFee
                if transfer_amount > 0:
                    print(f"Transferred from middleman[{from_wallet.address}] to target[{self._chain.to_wallet.address}]")        
                
                    for _ in range(max_attempts):
                        try:
                            await from_wallet.send(transfer_amount, self._chain.to_wallet.address, priority="low")
                            break
                        except TransactionException:
                            await asyncio.sleep(3.5)
                        
                    await asyncio.sleep(random.uniform(5, 10))
                else:
                    print(f"Middleman[{from_wallet.address}]'s balance is 0.")      
        


    @property
    def transfersN(self) -> int:
        return len(self._chain.middlemen)*2

    @property
    def approxMinutes(self) -> int:
        return TRANSFER_APPROX_MINS + len(self._chain.middlemen) * 15


__all__ = [ "WalletChain", "DominoMixer"]
        