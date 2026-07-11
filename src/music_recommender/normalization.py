from __future__ import annotations

import re
import unicodedata

_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_lookup_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return _WHITESPACE_PATTERN.sub(" ", without_accents).strip()
