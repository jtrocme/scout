"""Fetch everything needed for one scouting run, with progress reporting."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .extract import match_summary, player_record, valid_game
from .riot import RiotClient, RiotError
from .static import Static

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


class Progress:
    def __init__(self, cb: Optional[Callable[[dict], None]] = None):
        self.cb = cb or (lambda s: None)
        self.state = {"step": "", "done": 0, "total": 0, "log": [], "players": {}}

    def log(self, msg: str):
        self.state["log"].append({"t": time.time(), "msg": msg})
        self.state["log"] = self.state["log"][-200:]
        self.cb(self.state)

    def set(self, **kw):
        self.state.update(kw)
        self.cb(self.state)


def parse_riot_id(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    if "#" not in raw:
        raise ValueError(f"« {raw} » : il faut le format Pseudo#TAG")
    name, tag = raw.rsplit("#", 1)
    return name.strip(), tag.strip()


def fetch_games(client: RiotClient, ids: list[str], timelines: bool, progress: Progress, label: str,
                workers: int = 4, puuid: Optional[str] = None) -> dict[str, tuple[dict, Optional[dict]]]:
    """Download matches (+timelines) for a list of ids. Cached ones are free."""
    out: dict[str, tuple[dict, Optional[dict]]] = {}
    todo = list(ids)
    done = 0

    def one(mid):
        m = client.match(mid, puuid)
        if not m or not valid_game(m):
            return mid, m, None
        t = client.timeline(mid) if timelines else None
        return mid, m, t

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for mid, m, t in ex.map(one, todo):
            done += 1
            if m and valid_game(m):
                out[mid] = (m, t)
            if done % 5 == 0 or done == len(todo):
                progress.state["players"].setdefault(label, {})["games"] = f"{done}/{len(todo)}"
                progress.set(done=progress.state.get("done", 0))
    return out


def estimate_requests(client: RiotClient, ids: list[str], timelines: bool, owner: Optional[dict] = None) -> int:
    n = 0
    owner = owner or {}
    for mid in ids:
        if not client.is_cached("matches", mid, owner.get(mid)):
            n += 1
        if timelines and not client.is_cached("timelines", mid):
            n += 1
    return n


def load_profile(client: RiotClient, p: dict, start_time: int, max_games: int):
    p["summoner"] = client.summoner(p["puuid"]) or {}
    p["leagues"] = client.leagues(p["puuid"])
    try:
        p["masteries"] = client.masteries(p["puuid"])[:40]
    except RiotError:
        p["masteries"] = []
    p["ids"] = client.match_ids(p["puuid"], start_time=start_time, type_="ranked", limit=max_games)


def collect_extra(client: RiotClient, static: Static, p: dict, start_time: int, max_games: int,
                  timelines: bool, progress: Progress, summaries: dict) -> dict:
    """Same treatment as a roster player, for an account found later (a smurf)."""
    label = f"{p['name']}#{p['tag']}"
    load_profile(client, p, start_time, max_games)
    progress.state["players"][label] = {"games": f"0/{len(p['ids'])}"}
    progress.log(f"Téléchargement des games de {label} ({len(p['ids'])})…")
    games = fetch_games(client, p["ids"], timelines, progress, label, puuid=p["puuid"])
    recs = []
    for mid, (m, t) in games.items():
        summaries.setdefault(mid, match_summary(m))
        rec = player_record(m, t, p["puuid"], static)
        if rec:
            recs.append(rec)
    recs.sort(key=lambda r: r["start"], reverse=True)
    p["records"] = recs
    return p


def find_by_puuid(client: RiotClient, puuid: str, old_id: str, progress: Progress) -> dict | None:
    """Current account of a player already scouted. The PUUID never changes, so a
    player who renamed is still found. None if the lookup fails (e.g. a key from
    another Riot app, which encrypts PUUIDs differently)."""
    try:
        acc = client.account_by_puuid(puuid)
    except RiotError as e:
        if e.status in (401, 403, 429) or e.status >= 500:
            raise
        return None
    if not acc or not acc.get("gameName"):
        return None
    new_id = f"{acc['gameName']}#{acc.get('tagLine', '')}"
    if old_id and new_id.lower() != old_id.lower():
        progress.log(f"{old_id} s'appelle maintenant {new_id}.")
    return acc


def resolve_account(client: RiotClient, rid: str, progress: Progress, puuid: str | None = None) -> dict:
    """Riot ID 'Name#TAG' -> {puuid, name, tag}. With a known PUUID (refresh of a
    report), a player who renamed is still found. Raises ValueError with a message
    for the user when the ID is malformed or unknown."""
    name, tag = parse_riot_id(rid)
    if not name or not tag:
        raise ValueError(f"« {rid.strip()} » : il faut le format Pseudo#TAG")
    progress.log(f"Recherche de {name}#{tag}…")
    acc = find_by_puuid(client, puuid, rid, progress) if puuid else None
    if acc is None:
        try:
            acc = client.account(name, tag)
        except RiotError as e:
            if e.status in (400, 404):
                raise ValueError(f"{name}#{tag} n'existe pas sur ce serveur")
            raise
    return {"puuid": acc["puuid"], "name": (acc.get("gameName") or name).strip(), "tag": acc.get("tagLine", tag)}


def collect(client: RiotClient, static: Static, roster: dict[str, str], days: int, max_games: int,
            timelines: bool, progress: Progress, puuids: dict[str, str] | None = None) -> dict:
    """roster: role -> 'Name#TAG'. puuids: role -> PUUID when refreshing a report,
    so renamed players are still found. Returns raw material for the analysis."""
    start_time = int(time.time()) - days * 86400
    players = {}
    for role in ROLES:
        rid = (roster.get(role) or "").strip()
        if not rid:
            continue
        players[role] = {"role": role, **resolve_account(client, rid, progress, (puuids or {}).get(role))}

    # profile data (cheap: 4 requests per player)
    for role, p in players.items():
        label = f"{p['name']}#{p['tag']}"
        progress.log(f"Profil de {label} (rangs, maîtrises)…")
        load_profile(client, p, start_time, max_games)
        progress.state["players"][label] = {"games": f"0/{len(p['ids'])}"}

    all_ids = list(dict.fromkeys(mid for p in players.values() for mid in p["ids"]))
    owner = {}
    for p in players.values():
        for mid in p["ids"]:
            owner.setdefault(mid, p["puuid"])
    need = estimate_requests(client, all_ids, timelines, owner)
    rate = client.limiter.per_second()
    progress.set(total=len(all_ids), need=need, eta=round(need / max(rate, 0.01)))
    progress.log(f"{len(all_ids)} games à lire, dont {need} requêtes à faire "
                 f"(≈ {round(need / max(rate, 0.01) / 60)} min avec cette clé, le reste est en cache).")

    games: dict[str, tuple[dict, Optional[dict]]] = {}
    for role, p in players.items():
        label = f"{p['name']}#{p['tag']}"
        missing = [m for m in p["ids"] if m not in games]
        progress.log(f"Téléchargement des games de {label} ({len(missing)} nouvelles)…")
        games.update(fetch_games(client, missing, timelines, progress, label, puuid=p["puuid"]))
        progress.state["players"][label]["games"] = f"{len(p['ids'])}/{len(p['ids'])}"
        progress.set(done=len(games))

    progress.log("Extraction des stats game par game…")
    summaries = {mid: match_summary(m) for mid, (m, t) in games.items()}
    for role, p in players.items():
        recs = []
        for mid in p["ids"]:
            if mid not in games:
                continue
            m, t = games[mid]
            rec = player_record(m, t, p["puuid"], static)
            if rec:
                recs.append(rec)
        recs.sort(key=lambda r: r["start"], reverse=True)
        p["records"] = recs

    return {"players": players, "summaries": summaries, "start_time": start_time, "games": games}
