"""Text normalization utilities for metrics calculation.

Provides text normalization functions to handle common variations
that don't affect semantic meaning, making metrics like WER more robust.
"""
from __future__ import annotations

import re
from typing import Dict


# English contractions mapping (subset of most common)
ENGLISH_CONTRACTIONS: Dict[str, str] = {
    "ain't": "am not",
    "aren't": "are not",
    "can't": "cannot",
    "couldn't": "could not",
    "didn't": "did not",
    "doesn't": "does not",
    "don't": "do not",
    "hadn't": "had not",
    "hasn't": "has not",
    "haven't": "have not",
    "he'd": "he would",
    "he'll": "he will",
    "he's": "he is",
    "i'd": "i would",
    "i'll": "i will",
    "i'm": "i am",
    "i've": "i have",
    "isn't": "is not",
    "it's": "it is",
    "let's": "let us",
    "shouldn't": "should not",
    "that's": "that is",
    "there's": "there is",
    "they'd": "they would",
    "they'll": "they will",
    "they're": "they are",
    "they've": "they have",
    "wasn't": "was not",
    "we'd": "we would",
    "we'll": "we will",
    "we're": "we are",
    "we've": "we have",
    "weren't": "were not",
    "what's": "what is",
    "won't": "will not",
    "wouldn't": "would not",
    "you'd": "you would",
    "you'll": "you will",
    "you're": "you are",
    "you've": "you have",
}


# Spanish contractions (common spoken forms)
SPANISH_CONTRACTIONS: Dict[str, str] = {
    "pa": "para",
    "pal": "para el",
    "pa'": "para",
    "p'": "para",
}


def expand_contractions(text: str, language: str = "en") -> str:
    """Expand contractions in text to their full forms.

    Args:
        text: Input text with contractions
        language: Language code ("en" or "es")

    Returns:
        Text with expanded contractions

    Example:
        >>> expand_contractions("I'm fine, thanks")
        "I am fine, thanks"
    """
    contractions = ENGLISH_CONTRACTIONS if language == "en" else SPANISH_CONTRACTIONS

    # Build regex pattern from contractions
    # Sort by length (longest first) to handle overlapping patterns
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(key) for key in sorted(contractions.keys(), key=len, reverse=True)) + r')\b',
        flags=re.IGNORECASE
    )

    def replace_contraction(match: re.Match) -> str:
        """Replace matched contraction with expanded form, preserving case."""
        contraction = match.group(0).lower()
        expanded = contractions.get(contraction, contraction)

        # Preserve original capitalization
        if match.group(0)[0].isupper():
            return expanded.capitalize()
        return expanded

    return pattern.sub(replace_contraction, text)


def remove_punctuation(text: str) -> str:
    """Remove all punctuation from text, keeping only letters, numbers, and spaces.

    Args:
        text: Input text with punctuation

    Returns:
        Text without punctuation

    Example:
        >>> remove_punctuation("Hello, world!")
        "Hello world"
    """
    # Keep alphanumeric characters, spaces, and hyphens (for compound words)
    return re.sub(r'[^\w\s-]', '', text)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace to single spaces and trim.

    Args:
        text: Input text with irregular whitespace

    Returns:
        Text with normalized whitespace

    Example:
        >>> normalize_whitespace("Hello   world\\n\\t!")
        "Hello world !"
    """
    return ' '.join(text.split())


def normalize_text_for_wer(text: str, language: str = "en") -> str:
    """Apply full normalization pipeline for WER calculation.

    Performs:
    1. Contraction expansion
    2. Lowercase conversion
    3. Punctuation removal
    4. Whitespace normalization

    This makes WER more robust to formatting variations that don't
    affect semantic meaning.

    Args:
        text: Input text to normalize
        language: Language code ("en" or "es")

    Returns:
        Fully normalized text

    Example:
        >>> normalize_text_for_wer("I'm fine, thanks!")
        "i am fine thanks"
    """
    text = expand_contractions(text, language)
    text = text.lower()
    text = remove_punctuation(text)
    text = normalize_whitespace(text)
    return text.strip()


__all__ = [
    "expand_contractions",
    "remove_punctuation",
    "normalize_whitespace",
    "normalize_text_for_wer",
    "ENGLISH_CONTRACTIONS",
    "SPANISH_CONTRACTIONS",
]
