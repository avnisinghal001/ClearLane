from __future__ import annotations

import re
import unicodedata

NULL_TOKENS = {"", "NULL", "null", "NaN", "nan", "None", "none"}


def is_null_like(value: object, null_tokens: set[str] | None = None) -> bool:
    if value is None:
        return True
    toks = null_tokens or NULL_TOKENS
    return str(value).strip() in toks


def normalize_text(value: object, *, uppercase: bool = False,
                   null_tokens: set[str] | None = None) -> str | None:
    if is_null_like(value, null_tokens):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"\s+", " ", text)
    if text in (null_tokens or NULL_TOKENS):
        return None
    return text.upper() if uppercase else text


def normalize_identifier(value: object, null_tokens: set[str] | None = None) -> str | None:
    return normalize_text(value, uppercase=False, null_tokens=null_tokens)


def normalize_bool(value: object, null_tokens: set[str] | None = None) -> bool | None:
    text = normalize_text(value, uppercase=True, null_tokens=null_tokens)
    if text is None:
        return None
    if text in {"TRUE", "T", "1", "YES", "Y"}:
        return True
    if text in {"FALSE", "F", "0", "NO", "N"}:
        return False
    return None


def normalize_validation_status(value: object, mapping: dict,
                                null_tokens: set[str] | None = None) -> str:
    text = normalize_text(value, uppercase=False, null_tokens=null_tokens)
    if text is None:
        return "UNKNOWN"
    key = text.lower()
    for target, aliases in mapping.items():
        if key in {str(a).lower() for a in aliases}:
            return target.upper()
    return "UNMAPPED"

