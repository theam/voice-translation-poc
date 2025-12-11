"""Text normalization utilities for metrics calculation.

This module provides text normalization functions to handle common variations
that don't affect semantic meaning, making metrics like WER more robust.
"""

import re
from typing import Dict


# English contractions mapping
ENGLISH_CONTRACTIONS: Dict[str, str] = {
    # Common contractions
    "ain't": "am not",
    "aren't": "are not",
    "can't": "cannot",
    "can't've": "cannot have",
    "could've": "could have",
    "couldn't": "could not",
    "couldn't've": "could not have",
    "didn't": "did not",
    "doesn't": "does not",
    "don't": "do not",
    "hadn't": "had not",
    "hadn't've": "had not have",
    "hasn't": "has not",
    "haven't": "have not",
    "he'd": "he would",
    "he'd've": "he would have",
    "he'll": "he will",
    "he'll've": "he will have",
    "he's": "he is",
    "how'd": "how did",
    "how'd'y": "how do you",
    "how'll": "how will",
    "how's": "how is",
    "i'd": "i would",
    "i'd've": "i would have",
    "i'll": "i will",
    "i'll've": "i will have",
    "i'm": "i am",
    "i've": "i have",
    "isn't": "is not",
    "it'd": "it would",
    "it'd've": "it would have",
    "it'll": "it will",
    "it'll've": "it will have",
    "it's": "it is",
    "let's": "let us",
    "ma'am": "madam",
    "might've": "might have",
    "mightn't": "might not",
    "mightn't've": "might not have",
    "must've": "must have",
    "mustn't": "must not",
    "mustn't've": "must not have",
    "needn't": "need not",
    "needn't've": "need not have",
    "o'clock": "of the clock",
    "oughtn't": "ought not",
    "oughtn't've": "ought not have",
    "shan't": "shall not",
    "sha'n't": "shall not",
    "shan't've": "shall not have",
    "she'd": "she would",
    "she'd've": "she would have",
    "she'll": "she will",
    "she'll've": "she will have",
    "she's": "she is",
    "should've": "should have",
    "shouldn't": "should not",
    "shouldn't've": "should not have",
    "so've": "so have",
    "so's": "so is",
    "that'd": "that would",
    "that'd've": "that would have",
    "that's": "that is",
    "there'd": "there would",
    "there'd've": "there would have",
    "there's": "there is",
    "they'd": "they would",
    "they'd've": "they would have",
    "they'll": "they will",
    "they'll've": "they will have",
    "they're": "they are",
    "they've": "they have",
    "to've": "to have",
    "wasn't": "was not",
    "we'd": "we would",
    "we'd've": "we would have",
    "we'll": "we will",
    "we'll've": "we will have",
    "we're": "we are",
    "we've": "we have",
    "weren't": "were not",
    "what'll": "what will",
    "what'll've": "what will have",
    "what're": "what are",
    "what's": "what is",
    "what've": "what have",
    "when's": "when is",
    "when've": "when have",
    "where'd": "where did",
    "where's": "where is",
    "where've": "where have",
    "who'll": "who will",
    "who'll've": "who will have",
    "who's": "who is",
    "who've": "who have",
    "why's": "why is",
    "why've": "why have",
    "will've": "will have",
    "won't": "will not",
    "won't've": "will not have",
    "would've": "would have",
    "wouldn't": "would not",
    "wouldn't've": "would not have",
    "y'all": "you all",
    "y'all'd": "you all would",
    "y'all'd've": "you all would have",
    "y'all're": "you all are",
    "y'all've": "you all have",
    "you'd": "you would",
    "you'd've": "you would have",
    "you'll": "you will",
    "you'll've": "you will have",
    "you're": "you are",
    "you've": "you have",
}

# Spanish contractions (less common but some exist)
SPANISH_CONTRACTIONS: Dict[str, str] = {
    "al": "a el",
    "del": "de el",
}


def expand_contractions(text: str, language: str = "en") -> str:
    """Expand contractions in text to their full forms.

    Args:
        text: Input text containing contractions
        language: Language code ("en" for English, "es" for Spanish)

    Returns:
        Text with contractions expanded

    Example:
        >>> expand_contractions("I've been there, haven't you?")
        "I have been there, have not you?"
    """
    # Select contractions map based on language
    if language.startswith("en"):
        contractions_map = ENGLISH_CONTRACTIONS
    elif language.startswith("es"):
        contractions_map = SPANISH_CONTRACTIONS
    else:
        # Unknown language, return as-is
        return text

    # Create pattern that matches any contraction (case-insensitive)
    # Sort by length (longest first) to avoid partial matches
    sorted_contractions = sorted(contractions_map.keys(), key=len, reverse=True)
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(c) for c in sorted_contractions) + r')\b',
        flags=re.IGNORECASE
    )

    def replace_contraction(match):
        """Replace matched contraction with its expansion."""
        contraction = match.group(0)
        # Preserve original case if possible
        contraction_lower = contraction.lower()
        expansion = contractions_map.get(contraction_lower, contraction)

        # Preserve capitalization
        if contraction[0].isupper():
            # Capitalize first word of expansion
            expansion = expansion[0].upper() + expansion[1:]

        return expansion

    return pattern.sub(replace_contraction, text)


def normalize_text_for_wer(text: str, language: str = "en") -> str:
    """Normalize text for WER calculation.

    Applies multiple normalization steps to make WER more robust to
    variations that don't affect semantic meaning.

    Args:
        text: Input text
        language: Language code for language-specific normalizations

    Returns:
        Normalized text

    Example:
        >>> normalize_text_for_wer("I've got 2 cats!")
        "i have got 2 cats"
    """
    # 1. Expand contractions
    text = expand_contractions(text, language)

    # 2. Convert to lowercase
    text = text.lower()

    # 3. Remove punctuation (keep alphanumeric and spaces)
    text = re.sub(r'[^\w\s]', '', text)

    # 4. Normalize whitespace
    text = ' '.join(text.split())

    return text


def normalize_text_basic(text: str) -> str:
    """Basic text normalization (lowercase + whitespace).

    Lighter normalization that only handles case and whitespace,
    without expanding contractions.

    Args:
        text: Input text

    Returns:
        Normalized text

    Example:
        >>> normalize_text_basic("  Hello  World!  ")
        "hello world!"
    """
    text = text.lower().strip()
    text = ' '.join(text.split())
    return text
