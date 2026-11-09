"""Second-account ("smurf") detection.

Idea: people who duo with a player also duo with that player's other
accounts. So for each scouted player P:

 1. Take P's regular teammates ("friends"): the other roster members plus
    outsiders who were on P's team in 3+ games.
 2. Read the friends' recent games that P is NOT in, and list who they
    queue with there.
 3. An account that plays a lot with P's friends but never with P, never
    in the same game as P, and never at the same time as P is a candidate.
 4. Score it on role, champion pool, hours of play, account level, and
    whether it plays on days P doesn't. The best candidates get a stricter
    check: their own match list is pulled and any game that could overlap
    one of P's games is downloaded to compare exact timestamps.
"""
from __future__ import annotations

import math
import time
from collections import Counter, defaultdict

from .collect import Progress
from .extract import match_summary, valid_game
from .riot import RiotClient, RiotError

DEPTH = {
    "off": None,
    "quick": {"friends": 4, "games": 12, "verify": 2, "verify_games": 5},
    "normal": {"friends": 6, "games": 20, "verify": 3, "verify_games": 8},
    "deep": {"friends": 10, "games": 40, "verify": 5, "verify_games": 15},
}


def _hours(starts):
    h = [0] * 24
    for s in starts:
        h[time.localtime(s / 1000).tm_hour] += 1
    return h


def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _overlaps(start, end, intervals, margin=60_000):
    for s, e in intervals:
        if start < e - margin and end > s + margin:
            return True
    return False


def _game_id(mid: str) -> int:
    try:
        return int(mid.split("_", 1)[1])
    except Exception:
        return 0


class _TimeIndex:
    """Estimate a game's start time from its numeric id (ids grow with time
    on a platform). Only used to pick which games are worth downloading."""

    def __init__(self, summaries):
        pts = sorted((_game_id(mid), s["start"]) for mid, s in summaries.items() if s.get("start"))
        self.ids = [p[0] for p in pts]
        self.ts = [p[1] for p in pts]

    def estimate(self, gid: int):
        import bisect
        if len(self.ids) < 2:
            return None
        i = bisect.bisect_left(self.ids, gid)
        if i <= 0:
            i = 1
        if i >= len(self.ids):
            i = len(self.ids) - 1
        x0, x1, y0, y1 = self.ids[i - 1], self.ids[i], self.ts[i - 1], self.ts[i]
        if x1 == x0:
            return y0
        return y0 + (gid - x0) * (y1 - y0) / (x1 - x0)


def detect(client: RiotClient, raw: dict, prem: dict, depth: str, progress: Progress) -> dict:
    cfg = DEPTH.get(depth)
    if not cfg:
        return {"enabled": False}
    players = raw["players"]
    summaries = raw["summaries"]
    start_time = raw["start_time"]
    roster = {p["puuid"] for p in players.values()}
    outsiders = prem["_outsiders"]
    id_cache: dict[str, list[str]] = {}

    def ids_of(puuid):
        if puuid not in id_cache:
            try:
                id_cache[puuid] = client.match_ids(puuid, start_time=start_time, type_=None, limit=100)
            except RiotError:
                id_cache[puuid] = []
        return id_cache[puuid]

    def summary(mid):
        if mid in summaries:
            return summaries[mid]
        m = client.match(mid)
        if not m or not valid_game(m):
            return None
        summaries[mid] = match_summary(m)
        return summaries[mid]

    results = {}
    for role, p in players.items():
        label = f"{p['name']}#{p['tag']}"
        progress.log(f"Comptes secondaires : on regarde avec qui jouent les potes de {label}…")
        my_ids = set(p["ids"])
        my_sums = [summaries[m] for m in p["ids"] if m in summaries]
        my_intervals = [(s["start"], s["end"]) for s in my_sums]
        seen_with_me = {pl["puuid"] for s in my_sums for pl in s["players"]}
        my_days = {time.strftime("%Y-%m-%d", time.localtime(s["start"] / 1000)) for s in my_sums}
        my_hours = _hours(s["start"] for s in my_sums)
        my_champs = Counter(r["champ"] for r in p["records"])
        my_pool = {c for c, _ in my_champs.most_common(15)}
        my_level = (p.get("summoner") or {}).get("summonerLevel")

        # friends = roster mates who played with P + regular outsiders
        friends = []
        for other in players.values():
            if other["puuid"] == p["puuid"]:
                continue
            together = sum(1 for s in my_sums for pl in s["players"]
                           if pl["puuid"] == other["puuid"] and pl["team"] == _team(s, p["puuid"]))
            friends.append((other["puuid"], f"{other['name']}#{other['tag']}", together, True))
        for puuid, o in outsiders.items():
            n = o["with"].get(p["puuid"], 0)
            if n >= 3:
                friends.append((puuid, o["name"], n, False))
        friends.sort(key=lambda f: (-f[3], -f[2]))
        roster_friends = [f for f in friends if f[3]]
        outside_friends = [f for f in friends if not f[3]][: cfg["friends"]]

        cands = defaultdict(lambda: {"g": 0, "friends": Counter(), "roles": Counter(), "champs": Counter(),
                                     "starts": [], "intervals": [], "name": "", "level": None, "w": 0,
                                     "seen": set()})
        for f_puuid, f_name, _, is_roster in roster_friends + outside_friends:
            if is_roster:
                f_ids = [m for m in players_by_puuid(players, f_puuid)["ids"] if m not in my_ids]
            else:
                f_ids = [m for m in ids_of(f_puuid) if m not in my_ids][: cfg["games"]]
            for mid in f_ids:
                s = summary(mid)
                if not s:
                    continue
                fteam = _team(s, f_puuid)
                for pl in s["players"]:
                    if pl["team"] != fteam or pl["puuid"] in (f_puuid, p["puuid"]) or pl["puuid"] in roster:
                        continue
                    c = cands[pl["puuid"]]
                    c["friends"][f_name] += 1
                    if mid in c["seen"]:  # same game reached through another friend
                        continue
                    c["seen"].add(mid)
                    c["g"] += 1
                    c["w"] += pl["win"]
                    c["roles"][pl["role"]] += 1
                    c["champs"][pl["champ"]] += 1
                    c["starts"].append(s["start"])
                    c["intervals"].append((s["start"], s["end"]))
                    c["name"] = f"{pl['name']}#{pl['tag']}"
                    c["level"] = pl.get("level")

        suspects, cleared = [], []
        for puuid, c in cands.items():
            n_friends = len(c["friends"])
            if c["g"] < 3 or (n_friends < 2 and c["g"] < 5):
                continue
            if puuid in seen_with_me:
                continue  # already met P in a game: two different people
            if any(_overlaps(s, e, my_intervals) for s, e in c["intervals"]):
                cleared.append({"name": c["name"], "reason": "a joué en même temps que lui", "g": c["g"]})
                continue
            role_share = c["roles"].get(role, 0) / c["g"]
            champ_share = sum(n for ch, n in c["champs"].items() if ch in my_pool) / c["g"]
            hours_sim = _cosine(my_hours, _hours(c["starts"])) if len(c["starts"]) >= 5 else None
            off_days = sum(1 for s in c["starts"]
                           if time.strftime("%Y-%m-%d", time.localtime(s / 1000)) not in my_days) / len(c["starts"])
            lvl = c["level"]
            # A sub who fills the empty slot always matches the role, so role
            # weighs little; same champions and a young account weigh a lot.
            score = 0.0
            score += min(c["g"], 12) / 12 * 15
            score += min(n_friends, 3) / 3 * 10
            score += role_share * 10
            score += champ_share * 30
            score += (hours_sim if hours_sim is not None else 0.5) * 10
            score += off_days * 5
            if lvl is not None and not (my_level and lvl > my_level):
                score += 15 if lvl < 80 else 10 if lvl < 150 else 5 if lvl < 250 else 0
            suspects.append({
                "puuid": puuid, "name": c["name"], "g": c["g"], "wr": c["w"] / c["g"],
                "friends": [[n, k] for n, k in c["friends"].most_common()],
                "roleShare": role_share, "mainRole": c["roles"].most_common(1)[0][0],
                "champShare": champ_share,
                "commonChamps": [ch for ch, _ in c["champs"].most_common() if ch in my_pool][:5],
                "champs": [[ch, n] for ch, n in c["champs"].most_common(5)],
                "hoursSim": hours_sim, "offDays": off_days, "level": lvl, "myLevel": my_level,
                "score": round(score), "verified": None, "checked": 0,
                "_starts": c["starts"],
            })
        suspects.sort(key=lambda x: -x["score"])

        # strict verification for the best candidates
        tindex = _TimeIndex(summaries)
        kept = []
        for sus in suspects[: cfg["verify"]]:
            if sus["score"] < 35:
                kept.append(sus)
                continue
            progress.log(f"Vérification de {sus['name']} (soupçonné pour {label})…")
            their_ids = ids_of(sus["puuid"])
            if my_ids & set(their_ids):
                cleared.append({"name": sus["name"], "reason": "était dans une de ses games", "g": sus["g"]})
                continue
            # games that could overlap one of P's games
            risky = []
            for mid in their_ids:
                est = tindex.estimate(_game_id(mid))
                if est is None:
                    continue
                dist = min((abs(est - s) for s, e in my_intervals), default=None)
                if dist is not None and dist < 3 * 3600 * 1000:
                    risky.append((dist, mid))
            risky.sort()
            overlap = False
            checked = 0
            for _, mid in risky[: cfg["verify_games"]]:
                s = summary(mid)
                if not s:
                    continue
                checked += 1
                if _overlaps(s["start"], s["end"], my_intervals):
                    overlap = True
                    break
            sus["checked"] = checked + len(sus["_starts"])
            sus["totalGames"] = len(their_ids)
            if overlap:
                cleared.append({"name": sus["name"], "reason": "a joué en même temps que lui (vérifié)", "g": sus["g"]})
                continue
            sus["verified"] = True
            sus["score"] = min(100, sus["score"] + 10)
            kept.append(sus)
        kept += suspects[cfg["verify"]:]
        for s in kept:
            s.pop("_starts", None)
        kept.sort(key=lambda x: -x["score"])
        results[role] = {
            "player": label,
            "friends": [[f[1], f[2], f[3]] for f in roster_friends + outside_friends],
            "suspects": [s for s in kept if s["score"] >= 50][:4],
            "cleared": cleared[:8],
        }
    return {"enabled": True, "depth": depth, "players": results}


def _team(summary, puuid):
    for pl in summary["players"]:
        if pl["puuid"] == puuid:
            return pl["team"]
    return None


def players_by_puuid(players, puuid):
    for p in players.values():
        if p["puuid"] == puuid:
            return p
    return {"ids": []}
