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
                workers: int = 4) -> dict[str, tuple[dict, Optional[dict]]]:
    """Download matches (+timelines) for a list of ids. Cached ones are free."""
    out: dict[str, tuple[dict, Optional[dict]]] = {}
    todo = list(ids)
    done = 0

    def one(mid):
        m = client.match(mid)
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


def estimate_requests(client: RiotClient, ids: list[str], timelines: bool) -> int:
    n = 0
    for mid in ids:
        if not client.is_cached("matches", mid):
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
    games = fetch_games(client, p["ids"], timelines, progress, label)
    recs = []
    for mid, (m, t) in games.items():
        summaries.setdefault(mid, match_summary(m))
        rec = player_record(m, t, p["puuid"], static)
        if rec:
            recs.append(rec)
    recs.sort(key=lambda r: r["start"], reverse=True)
    p["records"] = recs
    return p


def collect(client: RiotClient, static: Static, roster: dict[str, str], days: int, max_games: int,
            timelines: bool, progress: Progress) -> dict:
    """roster: role -> 'Name#TAG'. Returns raw material for the analysis."""
    start_time = int(time.time()) - days * 86400
    players = {}
    for role in ROLES:
        rid = (roster.get(role) or "").strip()
        if not rid:
            continue
        name, tag = parse_riot_id(rid)
        progress.log(f"Recherche de {name}#{tag}…")
        try:
            acc = client.account(name, tag)
        except RiotError as e:
            if e.status == 404:
                raise ValueError(f"{name}#{tag} n'existe pas sur ce serveur")
            raise
        puuid = acc["puuid"]
        players[role] = {
            "role": role,
            "puuid": puuid,
            "name": (acc.get("gameName") or name).strip(),
            "tag": acc.get("tagLine", tag),
        }

    # profile data (cheap: 4 requests per player)
    for role, p in players.items():
        label = f"{p['name']}#{p['tag']}"
        progress.log(f"Profil de {label} (rangs, maîtrises)…")
        load_profile(client, p, start_time, max_games)
        progress.state["players"][label] = {"games": f"0/{len(p['ids'])}"}

    all_ids = list(dict.fromkeys(mid for p in players.values() for mid in p["ids"]))
    need = estimate_requests(client, all_ids, timelines)
    rate = client.limiter.per_second()
    progress.set(total=len(all_ids), need=need, eta=round(need / max(rate, 0.01)))
    progress.log(f"{len(all_ids)} games à lire, dont {need} requêtes à faire "
                 f"(≈ {round(need / max(rate, 0.01) / 60)} min avec cette clé, le reste est en cache).")

    games: dict[str, tuple[dict, Optional[dict]]] = {}
    for role, p in players.items():
        label = f"{p['name']}#{p['tag']}"
        missing = [m for m in p["ids"] if m not in games]
        progress.log(f"Téléchargement des games de {label} ({len(missing)} nouvelles)…")
        games.update(fetch_games(client, missing, timelines, progress, label))
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
