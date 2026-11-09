"""Small numeric helpers shared by the analysis modules."""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional


def avg(values: Iterable) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def rate(values: Iterable) -> Optional[float]:
    vals = [bool(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def median(values: Iterable) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def wr_block(records: list) -> dict:
    g = len(records)
    w = sum(1 for r in records if r["win"])
    return {"g": g, "w": w, "wr": w / g if g else None}


def kda_of(records: list) -> dict:
    g = len(records) or 1
    k = sum(r["k"] for r in records) / g
    d = sum(r["d"] for r in records) / g
    a = sum(r["a"] for r in records) / g
    return {"k": k, "d": d, "a": a, "ratio": (k + a) / max(d, 1) if records else None}


def top(counter: Counter, n: int = 3) -> list:
    return [[k, v] for k, v in counter.most_common(n)]


def r1(v, nd=1):
    return None if v is None else round(v, nd)
