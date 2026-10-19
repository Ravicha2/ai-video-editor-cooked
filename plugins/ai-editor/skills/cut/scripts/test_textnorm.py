#!/usr/bin/env python3
"""Self-check for textnorm.py, offline, no network.

    python3 test_textnorm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import textnorm as T  # noqa: E402


def test_latin_accents_fold_to_the_plain_letter():
    """Transcribers disagree about diacritics, so a quote written from one pass must match the other:
    "Garçons" in one pass and "Garcons" in the next are the same spoken word."""
    assert T.norm("Garçons") == "garcons", T.norm("Garçons")
    assert T.norm("café") == "cafe", T.norm("café")
    assert T.norm("naïve") == "naive", T.norm("naïve")


def test_thai_survives_norm():
    """Thai has no spaces between words, so the whole fragment is one token. Dropping the Thai block
    normed every Thai quote to "" and it never matched the other transcript."""
    assert T.norm("อันดับ") == "อันดับ", T.norm("อันดับ")
    assert T.norm("ภาษาไทย") == "ภาษาไทย", T.norm("ภาษาไทย")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all ok")
