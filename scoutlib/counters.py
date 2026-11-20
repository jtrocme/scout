"""Lane matchup win rates, from u.gg's public stats files.

u.gg publishes one JSON per champion and patch with every lane matchup
(wins, games and gold lead at 15 min, from that champion's side). We keep
only the worldwide numbers, merge the last two patches so a fresh patch
still has enough games, and cache the result on disk.

Nothing here touches the Riot API or the rate limiter.
"""
from __future__ import annotations

import json
import threading
import time

import requests

from .riot import CACHE

VERSIONS = "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/ugg/ugg-api-versions.json"
MATCHUPS = "https://stats2.u.gg/lol/1.5/matchups/{patch}/ranked_solo_5x5/{champ}/{ver}.json"
UA = {"User-Agent": "Mozilla/5.0 (scout-lol)"}

WORLD = "12"
TIERS = {  # our name -> u.gg id
    "emerald_plus": "17", "platinum_plus": "10", "diamond_plus": "11",
    "master_plus": "14", "all": "8",
}
ROLE_ID = {"JUNGLE": "1", "UTILITY": "2", "BOTTOM": "3", "TOP": "4", "MIDDLE": "5"}
FRESH = 6 * 3600  # re-download the current patch after this many seconds

_DIR = CACHE / "ugg"
_lock = threading.Lock()
_versions: dict = {"t": 0, "data": None}


def _patches() -> list[tuple[str, str]]:
    """The two most recent patches as (patch, file version), newest first."""
    with _lock:
        if not _versions["data"] or time.time() - _versions["t"] > FRESH:
            fp = _DIR / "versions.json"
            try:
                r = requests.get(VERSIONS, timeout=15, headers=UA)
                r.raise_for_status()
                _versions["data"] = r.json()
                _DIR.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(_versions["data"]), encoding="utf-8")
            except Exception:
                if not fp.exists():
                    raise RuntimeError("u.gg injoignable : impossible de lire la liste des patchs.")
                _versions["data"] = json.loads(fp.read_text(encoding="utf-8"))
            _versions["t"] = time.time()
        data = _versions["data"]
    key = lambda p: [int(x) for x in p.split("_") if x.isdigit()]
    patches = sorted((p for p in data if data[p].get("matchups")), key=key, reverse=True)
    return [(p, data[p]["matchups"]) for p in patches[:2]]


def _load(champ: int, patch: str, ver: str, newest: bool) -> dict | None:
    """{tier id: {role id: [[opp, wins, games, goldAdv15], ...]}} for the world, or None."""
    fp = _DIR / patch / f"{champ}.json"
    if fp.exists() and (not newest or time.time() - fp.stat().st_mtime < FRESH):
        return json.loads(fp.read_text(encoding="utf-8"))
    try:
        r = requests.get(MATCHUPS.format(patch=patch, champ=champ, ver=ver), timeout=30, headers=UA)
        if r.status_code in (403, 404):
            return None
        r.raise_for_status()
        world = r.json().get(WORLD, {})
    except Exception:
        if fp.exists():  # stale beats nothing
            return json.loads(fp.read_text(encoding="utf-8"))
        raise
    keep = set(TIERS.values())
    out = {t: {role: [[x[0], x[1], x[2], x[4]] for x in v[0]] for role, v in roles.items()}
           for t, roles in world.items() if t in keep}
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out


def matchups(champ: int, role: str, tier: str = "emerald_plus") -> dict:
    """Every lane opponent of `champ` in `role`, from the OPPONENT's side:
    wr = how often they beat `champ`, gd15 = their gold lead at 15 min."""
    tid = TIERS.get(tier, TIERS["emerald_plus"])
    rid = ROLE_ID[role]
    acc: dict[int, list] = {}
    used = []
    for i, (patch, ver) in enumerate(_patches()):
        data = _load(champ, patch, ver, newest=(i == 0))
        rows = ((data or {}).get(tid) or {}).get(rid) or []
        if rows:
            used.append(patch.replace("_", "."))
        for opp, wins, games, gold in rows:
            a = acc.setdefault(opp, [0, 0, 0])
            a[0] += wins
            a[1] += games
            a[2] += gold
    total = sum(a[1] for a in acc.values())
    out = []
    for opp, (wins, games, gold) in acc.items():
        if games < 1:
            continue
        out.append({"champ": opp, "g": games, "wr": 1 - wins / games, "gd15": -gold / games,
                    "share": games / total if total else 0})
    out.sort(key=lambda x: -x["wr"])
    return {"champ": champ, "role": role, "tier": tier, "patches": used, "games": total, "rows": out}
