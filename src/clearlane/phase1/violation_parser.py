from __future__ import annotations

import ast
import json
import re
from typing import Iterable

from .category_normalization import is_null_like, normalize_text


def _as_list(value: object) -> list[object]:
    if is_null_like(value):
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
            if isinstance(parsed, (list, tuple, set)):
                return list(parsed)
            return [parsed]
        except Exception:
            pass
    return [p for p in re.split(r"[|;,]+", text) if p.strip()]


def normalize_label(value: object) -> str | None:
    text = normalize_text(value, uppercase=True)
    if text is None:
        return None
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def parse_violation_labels(value: object) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in _as_list(value):
        label = normalize_label(item)
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def classify_parking(labels: Iterable[str], parking_labels: set[str]) -> bool:
    return any(label in parking_labels for label in labels)


def primary_violation(labels: Iterable[str], parking_labels: set[str]) -> str | None:
    labels = list(labels)
    for label in labels:
        if label in parking_labels:
            return label
    return labels[0] if labels else None


def parse_offence_codes(value: object) -> tuple[list[str], bool]:
    if is_null_like(value):
        return [], True
    raw = str(value).strip()
    items: list[object] | None = None
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(raw)
            items = list(parsed) if isinstance(parsed, (list, tuple, set)) else [parsed]
            break
        except Exception:
            pass
    if items is None:
        if re.fullmatch(r"[0-9A-Za-z_. -]+(,[0-9A-Za-z_. -]+)*", raw):
            items = raw.split(",")
        else:
            return [], False
    out: list[str] = []
    for item in items:
        text = normalize_text(item, uppercase=True)
        if text is not None:
            out.append(text)
    return out, True

