class Mnemonic:
    def __init__(self, raw_words: str):
        self._raw_words = raw_words.strip().lower()
        self._words = raw_words.split(" ")
    
    def getRawWords(self) -> str:
        return self._raw_words

    def getWords(self) -> list[str]:
        return self._words
    
    def __str__(self) -> str:
        return f"Mnemonic('{' '.join(self.getWords()[:3])}'...)"