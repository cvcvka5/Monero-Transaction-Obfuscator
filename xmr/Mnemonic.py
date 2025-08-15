class Mnemonic:
    """
    A class that represents a mnemonic phrase used for cryptographic wallets or secure key generation.

    Attributes
    ----------
    _raw_words : str
        The raw string of words representing the mnemonic.
    _words : list[str]
        The list of words obtained by splitting the mnemonic string.
    """

    def __init__(self, raw_words: str):
        """
        Initialize a Mnemonic object.

        Parameters
        ----------
        raw_words : str
            The raw mnemonic phrase as a single string.
        """
        self._raw_words = raw_words.strip().lower()
        self._words = raw_words.split(" ")
    
    def getRawWords(self) -> str:
        """
        Get the raw mnemonic phrase as a string.

        Returns
        -------
        str
            The full mnemonic phrase in lowercase.
        """
        return self._raw_words

    def getWords(self) -> list[str]:
        """
        Get the mnemonic phrase as a list of individual words.

        Returns
        -------
        list[str]
            A list of words in the mnemonic phrase.
        """
        return self._words
    
    def __str__(self) -> str:
        """
        Return a shortened string representation of the mnemonic.

        Returns
        -------
        str
            A string showing the first three words of the mnemonic followed by an ellipsis.
        """
        return f"Mnemonic('{' '.join(self.getWords()[:3])}'...)"
