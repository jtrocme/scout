"""Data Dragon static data (French locale): champions, items, runes, spells."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .riot import CACHE

DD = "https://ddragon.leagueoflegends.com"
LOCALE = "fr_FR"

QUEUES = {
    420: "SoloQ",
    440: "Flex",
    710: "Ranked 5 stack",
    700: "Clash",
    400: "Normal draft",
    430: "Normal blind",
    490: "Quickplay",
}
LEAGUE_QUEUES = {
    "RANKED_SOLO_5x5": "SoloQ",
    "RANKED_FLEX_SR": "Flex",
    "RANKED_PREMADE_5x5": "Ranked 5 stack",
}

# Data Dragon tag -> what a coach would call it
CLASS_FR = {
    "Fighter": "Bruiser",
    "Tank": "Tank",
    "Mage": "Mage",
    "Assassin": "Assassin",
    "Marksman": "Tireur",
    "Support": "Support",
}

TIER_FR = {
    "IRON": "Fer", "BRONZE": "Bronze", "SILVER": "Argent", "GOLD": "Or",
    "PLATINUM": "Platine", "EMERALD": "Émeraude", "DIAMOND": "Diamant",
    "MASTER": "Maître", "GRANDMASTER": "Grand Maître", "CHALLENGER": "Challenger",
}
TIER_ORDER = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND",
              "MASTER", "GRANDMASTER", "CHALLENGER"]


def _fetch_json(url: str, cache_name: str):
    fp = CACHE / "static" / cache_name
    if fp.exists():
        return json.loads(fp.read_text(encoding="utf-8"))
    fp.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=30, headers={"User-Agent": "scout-lol/1.0"})
    r.raise_for_status()
    data = r.json()
    fp.write_text(json.dumps(data), encoding="utf-8")
    return data


class Static:
    def __init__(self):
        try:
            r = requests.get(f"{DD}/api/versions.json", timeout=15)
            self.version = r.json()[0]
        except Exception:
            cached = sorted((CACHE / "static").glob("champion_*.json")) if (CACHE / "static").exists() else []
            if not cached:
                raise
            self.version = cached[-1].stem.split("_", 1)[1]
        v = self.version
        champs = _fetch_json(f"{DD}/cdn/{v}/data/{LOCALE}/champion.json", f"champion_{v}.json")["data"]
        self.champs = {}       # numeric id -> info
        self.champ_by_key = {}  # "MonkeyKing" -> info
        for key, c in champs.items():
            info = {
                "id": int(c["key"]),
                "key": key,
                "name": c["name"],
                "tags": c.get("tags", []),
                "classes": [CLASS_FR.get(t, t) for t in c.get("tags", [])],
            }
            self.champs[info["id"]] = info
            self.champ_by_key[key] = info

        items = _fetch_json(f"{DD}/cdn/{v}/data/{LOCALE}/item.json", f"item_{v}.json")["data"]
        self.items = {}
        for iid, it in items.items():
            tags = it.get("tags", [])
            gold = it.get("gold", {})
            legendary = (
                gold.get("total", 0) >= 2200
                and not it.get("into")
                and "Consumable" not in tags
                and "Trinket" not in tags
                and gold.get("purchasable", True)
            )
            self.items[int(iid)] = {
                "id": int(iid),
                "name": it.get("name", iid),
                "gold": gold.get("total", 0),
                "boots": "Boots" in tags,
                "legendary": legendary,
            }

        runes = _fetch_json(f"{DD}/cdn/{v}/data/{LOCALE}/runesReforged.json", f"runes_{v}.json")
        self.runes = {}
        for style in runes:
            self.runes[style["id"]] = {"name": style["name"], "icon": style["icon"]}
            for slot in style["slots"]:
                for rune in slot["runes"]:
                    self.runes[rune["id"]] = {"name": rune["name"], "icon": rune["icon"]}

        spells = _fetch_json(f"{DD}/cdn/{v}/data/{LOCALE}/summoner.json", f"summoner_{v}.json")["data"]
        self.spells = {int(s["key"]): {"name": s["name"], "key": sid} for sid, s in spells.items()}

    # ---- helpers ----------------------------------------------------------
    def champ(self, champ_id: int, fallback_key: str = "") -> dict:
        c = self.champs.get(champ_id)
        if c:
            return c
        c = self.champ_by_key.get(fallback_key)
        if c:
            return c
        return {"id": champ_id, "key": fallback_key or str(champ_id), "name": fallback_key or "?",
                "tags": [], "classes": []}

    def champ_class(self, champ_id: int) -> str:
        cl = self.champ(champ_id)["classes"]
        return cl[0] if cl else "?"

    def champ_classes2(self, champ_id: int) -> str:
        cl = self.champ(champ_id)["classes"][:2]
        return " / ".join(cl) if cl else "?"

    def item_name(self, iid: int) -> str:
        return self.items.get(iid, {}).get("name", str(iid))

    def is_legendary(self, iid: int) -> bool:
        return self.items.get(iid, {}).get("legendary", False)

    def rune_name(self, rid: int) -> str:
        return self.runes.get(rid, {}).get("name", str(rid))

    def spell_name(self, sid: int) -> str:
        return self.spells.get(sid, {}).get("name", str(sid))

    def export(self, champ_ids: set[int], item_ids: set[int], rune_ids: set[int], spell_ids: set[int]) -> dict:
        """Compact lookup tables shipped inside a report for the UI."""
        return {
            "version": self.version,
            "champs": {cid: {"key": self.champ(cid)["key"], "name": self.champ(cid)["name"]} for cid in champ_ids},
            "items": {i: self.item_name(i) for i in item_ids},
            "runes": {r: self.runes.get(r, {"name": str(r), "icon": ""}) for r in rune_ids},
            "spells": {s: self.spells.get(s, {"name": str(s), "key": ""}) for s in spell_ids},
        }


_STATIC = None


def get_static() -> Static:
    global _STATIC
    if _STATIC is None:
        _STATIC = Static()
    return _STATIC
