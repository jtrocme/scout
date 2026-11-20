"""Second-account ("smurf") detection.

Idea: people who duo with a player also duo with that player's other
accounts. So for each scouted player P:

 1. Take P's regular teammates ("friends"): the other roster members plus
    outsiders who were on P's team in 3+ games.
 2. Read the friends' recent games that P is NOT in, and list who they
    queue with there.
 3. An account that plays a lot with P's friends but never with P, never
    in the same game as P, and never at the same time as P is a candidate.
 4. The strongest clue is a "near miss": P's game ends at 20:10 and the
    candidate's starts at 20:20 (or the other way round). One person
    switching accounts does exactly that; two people almost never do it
    again and again without ever overlapping. Hours of play, account level
    and shared partners add to it. Same role / same champions only ever ADD
    points: a smurf is most useful to find when it trains other champions.
    The best candidates get a stricter check: their own match list is
    pulled and every game close in time to one of P's games is downloaded,
    both to rule out an overlap and to find more near misses.
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
    # own = games of the player in other queues (ARAM, normals...) downloaded
    # to see who he plays with and when; they are cached for next time.
    "quick": {"friends": 4, "games": 12, "verify": 3, "verify_games": 8, "own": 30},
    "normal": {"friends": 6, "games": 20, "verify": 4, "verify_games": 12, "own": 60},
    "deep": {"friends": 10, "games": 40, "verify": 6, "verify_games": 20, "own": 100},
}

NEAR_MISS = 60 * 60_000   # gap between one account's game end and the other's start
TIGHT = 15 * 60_000       # a gap this short counts fully (1.0)
CLOSE = 30 * 60_000       # up to here counts 0.6; up to NEAR_MISS counts 0.3, so a
                          # loose near miss alone means little but many of them add up


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


def _any_game(match: dict) -> bool:
    """Any 5v5 game counts to know who plays with whom and when: ARAM,
    normals, ranked... (stats stay on Summoner's Rift, see valid_game)."""
    info = match.get("info", {})
    teams = {p.get("teamId") for p in info.get("participants", [])}
    return len(info.get("participants", [])) == 10 and len(teams) == 2 and info.get("gameDuration", 0) >= 240


def _overlaps(start, end, intervals, margin=60_000):
    for s, e in intervals:
        if start < e - margin and end > s + margin:
            return True
    return False


def _near_misses(intervals, my_intervals):
    """Candidate games that start shortly after one of P's games ends, or end
    shortly before one starts. At most one near miss per candidate game."""
    out = []
    for s, e in intervals:
        best = None
        for ms, me in my_intervals:
            for gap, first_end, second_start, after in ((s - me, me, s, True), (ms - e, e, ms, False)):
                if -60_000 <= gap <= NEAR_MISS and (best is None or gap < best[0]):
                    best = (gap, first_end, second_start, after)
        if best:
            out.append({"gap": max(0, round(best[0] / 60_000)), "end": best[1], "start": best[2],
                        "smurfAfter": best[3]})
    out.sort(key=lambda x: -x["start"])
    return out


def _near_weight(nm):
    return sum(1.0 if x["gap"] * 60_000 <= TIGHT else 0.6 if x["gap"] * 60_000 <= CLOSE else 0.3 for x in nm)


def _score(c):
    """Total out of 100. Without any near miss a candidate tops out around 70,
    so only accounts with near misses reach the full-analysis threshold."""
    score = 0.0
    score += min(c["g"], 12) / 12 * 12              # games with P's partners
    score += min(c["nFriends"], 3) / 3 * 8          # distinct partners
    score += 50 * (1 - 0.5 ** _near_weight(c["nearMisses"]))  # main clue: 3 tight ones ~ 44
    score += (c["hoursSim"] if c["hoursSim"] is not None else 0.5) * 10
    score += c["offDays"] * 5
    lvl, my = c["level"], c["myLevel"]
    if lvl is not None and not (my and lvl > my):
        score += 10 if lvl < 80 else 7 if lvl < 150 else 3 if lvl < 250 else 0
    # reinforcing only: never a penalty when they differ
    score += max(0.0, c["champShare"] - 0.1) / 0.9 * 10
    score += max(0.0, c["roleShare"] - 0.5) / 0.5 * 5
    if c["verified"]:
        score += 10
    return min(100, round(score))


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

    # Games outside Summoner's Rift (ARAM...) are kept apart so they never
    # leak into the stats of the report; here they only tell who and when.
    off_rift: dict[str, dict] = {}

    def summary(mid, puuid=None):
        """`puuid`: whose match list the game comes from (to catch stale cache)."""
        if mid in summaries:
            return summaries[mid]
        if mid in off_rift:
            return off_rift[mid]
        m = client.match(mid, puuid)
        if not m:
            return None
        if valid_game(m):
            summaries[mid] = match_summary(m)
            return summaries[mid]
        if _any_game(m):
            off_rift[mid] = {**match_summary(m), "offRift": True}
            return off_rift[mid]
        return None

    results = {}
    for role, p in players.items():
        label = f"{p['name']}#{p['tag']}"
        progress.log(f"Comptes secondaires : on regarde avec qui jouent les potes de {label}…")
        my_ids = set(p["ids"])
        my_sums = [summaries[m] for m in p["ids"] if m in summaries]
        # his games in every queue: ARAM or normals with a friend count too
        extra_ids = [m for m in ids_of(p["puuid"]) if m not in my_ids][: cfg["own"]]
        if extra_ids:
            progress.log(f"  {label} : {len(extra_ids)} games hors ranked (ARAM, normales…) pour les horaires et les partenaires")
        for mid in extra_ids:
            sm = summary(mid, p["puuid"])
            if sm:
                my_sums.append(sm)
        my_ids |= set(extra_ids)
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
        # regular partners outside the roster, counted over all his queues
        mates, mate_names = Counter(), {}
        for sm in my_sums:
            my_team = _team(sm, p["puuid"])
            for pl in sm["players"]:
                if pl["team"] == my_team and pl["puuid"] != p["puuid"] and pl["puuid"] not in roster:
                    mates[pl["puuid"]] += 1
                    mate_names[pl["puuid"]] = f"{pl['name']}#{pl['tag']}"
        for puuid, o in outsiders.items():
            mates[puuid] = max(mates[puuid], o["with"].get(p["puuid"], 0))
            mate_names.setdefault(puuid, o["name"])
        for puuid, n in mates.items():
            if n >= 3:
                friends.append((puuid, mate_names[puuid], n, False))
        friends.sort(key=lambda f: (-f[3], -f[2]))
        roster_friends = [f for f in friends if f[3]]
        outside_friends = [f for f in friends if not f[3]][: cfg["friends"]]

        cands = defaultdict(lambda: {"g": 0, "rift": 0, "friends": Counter(), "roles": Counter(), "champs": Counter(),
                                     "starts": [], "intervals": [], "name": "", "level": None, "w": 0,
                                     "seen": set()})
        for f_puuid, f_name, _, is_roster in roster_friends + outside_friends:
            if is_roster:
                f_ids = [m for m in players_by_puuid(players, f_puuid)["ids"] if m not in my_ids]
            else:
                f_ids = [m for m in ids_of(f_puuid) if m not in my_ids][: cfg["games"]]
            for mid in f_ids:
                s = summary(mid, f_puuid)
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
                    if not s.get("offRift"):  # ARAM picks say nothing about his pool or role
                        c["rift"] += 1
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
            rift = max(c["rift"], 1)
            role_share = c["roles"].get(role, 0) / rift
            champ_share = sum(n for ch, n in c["champs"].items() if ch in my_pool) / rift
            hours_sim = _cosine(my_hours, _hours(c["starts"])) if len(c["starts"]) >= 5 else None
            off_days = sum(1 for s in c["starts"]
                           if time.strftime("%Y-%m-%d", time.localtime(s / 1000)) not in my_days) / len(c["starts"])
            lvl = c["level"]
            sus = {
                "puuid": puuid, "name": c["name"], "g": c["g"], "wr": c["w"] / c["g"],
                "friends": [[n, k] for n, k in c["friends"].most_common()],
                "roleShare": role_share, "mainRole": c["roles"].most_common(1)[0][0] if c["roles"] else "ARAM",
                "champShare": champ_share,
                "commonChamps": [ch for ch, _ in c["champs"].most_common() if ch in my_pool][:5],
                "champs": [[ch, n] for ch, n in c["champs"].most_common(5)],
                "hoursSim": hours_sim, "offDays": off_days, "level": lvl, "myLevel": my_level,
                "nFriends": n_friends, "nearMisses": _near_misses(c["intervals"], my_intervals),
                "verified": None, "checked": 0,
                "_starts": c["starts"], "_intervals": list(c["intervals"]),
            }
            sus["score"] = _score(sus)
            suspects.append(sus)
        suspects.sort(key=lambda x: -x["score"])

        # strict verification for the best candidates
        tindex = _TimeIndex({**summaries, **off_rift})
        kept = []
        for sus in suspects[: cfg["verify"]]:
            if sus["score"] < 30:
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
            intervals = set(sus["_intervals"])
            for _, mid in risky[: cfg["verify_games"]]:
                s = summary(mid, sus["puuid"])
                if not s:
                    continue
                checked += 1
                if _overlaps(s["start"], s["end"], my_intervals):
                    overlap = True
                    break
                intervals.add((s["start"], s["end"]))
            sus["checked"] = checked + len(sus["_starts"])
            sus["totalGames"] = len(their_ids)
            if overlap:
                cleared.append({"name": sus["name"], "reason": "a joué en même temps que lui (vérifié)", "g": sus["g"]})
                continue
            sus["verified"] = True
            sus["nearMisses"] = _near_misses(sorted(intervals), my_intervals)
            sus["score"] = _score(sus)
            kept.append(sus)
        kept += suspects[cfg["verify"]:]
        for s in kept:
            s.pop("_starts", None)
            s.pop("_intervals", None)
            s.pop("nFriends", None)
            s["nearTight"] = sum(1 for x in s["nearMisses"] if x["gap"] * 60_000 <= TIGHT)
            s["nearCount"] = len(s["nearMisses"])
            s["nearClose"] = sum(1 for x in s["nearMisses"] if x["gap"] * 60_000 <= CLOSE)
            s["nearMisses"] = s["nearMisses"][:8]
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
