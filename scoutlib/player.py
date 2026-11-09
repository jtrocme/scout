"""Everything about one player, aggregated from their game records."""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from . import geo
from .static import LEAGUE_QUEUES, QUEUES, TIER_FR, TIER_ORDER, Static
from .stats import avg, kda_of, rate, top, wr_block

DAY = 86400 * 1000

def _tl(records):
    return [r["tl"] for r in records if r.get("tl")]


def _champ_rows(records: list, static: Static, now_ms: int) -> list:
    by = defaultdict(list)
    for r in records:
        by[r["champ"]].append(r)
    rows = []
    for cid, rs in by.items():
        tls = _tl(rs)
        runes = Counter(r["keystone"] for r in rs if r.get("keystone"))
        items = Counter(t["build"][0][1] for t in tls if t.get("build"))
        if not items:  # no timeline: fall back to any legendary in final inventory
            items = Counter(next((i for i in r["items"] if static.is_legendary(i)), None) for r in rs)
            items.pop(None, None)
        boots = Counter(t["boots"] for t in tls if t.get("boots"))
        kda = kda_of(rs)
        wb = wr_block(rs)
        rows.append({
            "champ": cid,
            "g": wb["g"], "w": wb["w"], "wr": wb["wr"],
            "g30": sum(1 for r in rs if now_ms - r["start"] < 30 * DAY),
            "k": kda["k"], "d": kda["d"], "a": kda["a"], "kda": kda["ratio"],
            "csm": avg(r["csm"] for r in rs),
            "dpm": avg(r["dpm"] for r in rs),
            "kp": avg(r["kp"] for r in rs),
            "gd15": avg(t.get("gd15") for t in tls),
            "csd15": avg(t.get("csd15") for t in tls),
            "rune": [runes.most_common(1)[0][0], runes.most_common(1)[0][1], sum(runes.values())] if runes else None,
            "item": [items.most_common(1)[0][0], items.most_common(1)[0][1], sum(items.values())] if items else None,
            "boots": boots.most_common(1)[0][0] if boots else None,
            "last": max(r["start"] for r in rs),
            "roles": dict(Counter(r["role"] for r in rs)),
        })
    rows.sort(key=lambda x: (-x["g"], -(x["wr"] or 0)))
    return rows


def _vs_rows(records: list, key, label_fn=None, min_games: int = 1) -> list:
    by = defaultdict(list)
    for r in records:
        k = key(r)
        if k is None:
            continue
        by[k].append(r)
    rows = []
    for k, rs in by.items():
        if len(rs) < min_games:
            continue
        tls = _tl(rs)
        wb = wr_block(rs)
        rows.append({
            "key": k,
            "g": wb["g"], "wr": wb["wr"],
            "kda": kda_of(rs)["ratio"],
            "gd15": avg(t.get("gd15") for t in tls),
            "played": top(Counter(r["champ"] for r in rs), 3),
        })
    rows.sort(key=lambda x: -x["g"])
    return rows


def ban_candidates(champ_rows: list, n: int = 3) -> list:
    out = []
    for c in champ_rows:
        if c["g"] < 4:
            continue
        smooth = (c["w"] + 3) / (c["g"] + 6)
        weight = c["g"] + 1.5 * c["g30"]
        score = weight * (smooth - 0.42)
        if score > 0:
            out.append({"champ": c["champ"], "g": c["g"], "wr": c["wr"], "g30": c["g30"], "score": score})
    out.sort(key=lambda x: -x["score"])
    return out[:n]


def rising(champ_rows: list, total: int, total30: int) -> list:
    out = []
    if not total30:
        return out
    for c in champ_rows:
        if c["g30"] < 3:
            continue
        share30 = c["g30"] / total30
        share = c["g"] / total
        if share30 >= 0.2 and share30 >= 1.3 * share:
            out.append({"champ": c["champ"], "g30": c["g30"], "share30": share30, "share": share})
    out.sort(key=lambda x: -x["g30"])
    return out


def _ranks(leagues: list) -> list:
    out = []
    for e in leagues:
        q = e.get("queueType", "")
        label = LEAGUE_QUEUES.get(q, q.replace("_", " ").title())
        g = e.get("wins", 0) + e.get("losses", 0)
        tier = e.get("tier", "")
        apex = tier in ("MASTER", "GRANDMASTER", "CHALLENGER")
        out.append({
            "queue": label, "queueType": q, "tier": tier,
            "label": f"{TIER_FR.get(tier, tier.title())}{'' if apex else ' ' + e.get('rank', '')} {e.get('leaguePoints', 0)} LP",
            "score": (TIER_ORDER.index(tier) * 400 if tier in TIER_ORDER else 0)
                     + (0 if apex else (4 - ["I", "II", "III", "IV"].index(e.get("rank", "IV"))) * 100 if e.get("rank") in ("I", "II", "III", "IV") else 0)
                     + e.get("leaguePoints", 0),
            "lp": e.get("leaguePoints", 0), "g": g, "wr": e.get("wins", 0) / g if g else None,
            "hot": e.get("hotStreak", False), "fresh": e.get("freshBlood", False),
            "veteran": e.get("veteran", False), "inactive": e.get("inactive", False),
        })
    order = ["SoloQ", "Flex", "Ranked 5 stack"]
    out.sort(key=lambda x: order.index(x["queue"]) if x["queue"] in order else 9)
    return out


def _zone_table(events: list, team_of) -> list:
    tab = defaultdict(lambda: {"k": 0, "a": 0, "d": 0})
    for ev, team in events:
        z = geo.zone(ev[1], ev[2], team)
        tab[z][ev[3]] += 1
    rows = [{"zone": z, **v} for z, v in tab.items()]
    rows.sort(key=lambda x: -(x["k"] + x["a"] + x["d"]))
    return rows


def _movement(records: list, role: str) -> dict:
    tls = [(r["tl"], r["team"], r) for r in records if r.get("tl") and r["tl"].get("pos")]
    if not tls:
        return {}
    events = [(ev, team) for tl, team, _ in tls for ev in tl.get("early", [])]
    zone_time = Counter()
    for tl, team, _ in tls:
        for m, z in tl.get("zones", {}).items():
            if 3 <= int(m) <= 14:
                zone_time[z] += 1
    total_frames = sum(zone_time.values()) or 1
    mv = {
        "games": len(tls),
        # raw points, the UI draws them; [t, x, y, kind, team]
        "events": [[ev[0], ev[1], ev[2], ev[3], team] for ev, team in events],
        "zoneTable": _zone_table(events, None),
        "zoneTime": [[z, n, n / total_frames] for z, n in zone_time.most_common()],
        # positions for heatmaps: [minute, x, y, team]
        "positions": [[p[0], p[1], p[2], team] for tl, team, _ in tls for p in tl["pos"] if p[0] <= 14],
    }
    roams = [tl.get("roam") for tl, _, _ in tls]
    if role != "JUNGLE":
        has = [x for x in roams if x]
        mv["roamRate"] = len(has) / len(tls)
        mv["firstRoam"] = avg(x["m"] for x in has)
        mv["roamDest"] = top(Counter(x["zone"] if role == "UTILITY" else x["side"] for x in has), 6)
        mv["roamPits"] = dict(Counter(x["pit"] for x in has if x.get("pit")))
    if role == "MIDDLE":
        outside = sum(tl.get("takedownsOutside", 0) for tl, _, _ in tls)
        all3 = sum(tl.get("takedowns3_14", 0) for tl, _, _ in tls)
        mv["outside"] = {"n": outside, "of": all3,
                         "top": sum(tl.get("takedownsOutsideTop", 0) for tl, _, _ in tls),
                         "bot": sum(tl.get("takedownsOutsideBot", 0) for tl, _, _ in tls)}
    if role == "UTILITY":
        mv["enemyJungleTime"] = sum(zone_time[z] for z in geo.ENEMY_JUNGLE) / total_frames
        mv["riverBotTime"] = zone_time[geo.RIVER_BOT] / total_frames
    if role == "JUNGLE":
        g = len(tls)
        mv["invade1"] = rate(tl.get("invade1") for tl, _, _ in tls)
        mv["enemyJg6"] = rate(tl.get("enemyJg6") for tl, _, _ in tls)
        mv["scuttle34"] = rate(tl.get("scuttle34") for tl, _, _ in tls)
        mv["back35"] = rate(tl.get("back35") for tl, _, _ in tls)
        mv["startSide"] = top(Counter(tl.get("startSide") for tl, _, _ in tls if tl.get("startSide")), 2)
        per_champ = defaultdict(Counter)
        for tl, _, r in tls:
            if tl.get("startSide"):
                per_champ[r["champ"]][tl["startSide"]] += 1
        mv["startSideByChamp"] = sorted(
            [[c, cnt.most_common(1)[0][0], cnt.most_common(1)[0][1], sum(cnt.values())] for c, cnt in per_champ.items()],
            key=lambda x: -x[3])[:6]
        mv["at3"] = top(Counter(tl.get("at3") for tl, _, _ in tls if tl.get("at3")), 5)
        mv["at4"] = top(Counter(tl.get("at4") for tl, _, _ in tls if tl.get("at4")), 5)
        fl = [tl["firstLane"] for tl, _, _ in tls if tl.get("firstLane")]
        lanes = defaultdict(list)
        for x in fl:
            lanes[x["lane"]].append(x["m"])
        mv["firstLane"] = sorted([[l, len(ms), avg(ms)] for l, ms in lanes.items()], key=lambda x: -x[1])
        ft = [tl["firstTakedown"] for tl, _, _ in tls if tl.get("firstTakedown")]
        ftz = defaultdict(list)
        for x in ft:
            z = x["zone"]
            lane = "Top" if "top" in z.lower() else "Bot" if "bot" in z.lower() else "Mid" if "Mid" in z else z
            ftz[lane].append(x["t"])
        mv["firstTakedown"] = sorted([[l, len(ts), avg(ts) / 60] for l, ts in ftz.items()], key=lambda x: -x[1])
        mv["games"] = g
    return mv


def _objectives(records: list) -> dict:
    agg = defaultdict(lambda: {"team": 0, "me": 0, "enemy": 0, "games": 0})
    for r in records:
        tl = r.get("tl")
        if not tl:
            continue
        for mtype, o in tl.get("obj", {}).items():
            a = agg[mtype]
            a["team"] += o["team"]
            a["me"] += o["me"]
            a["enemy"] += o["enemy"]
    return {k: {**v, "part": v["me"] / v["team"] if v["team"] else None} for k, v in agg.items()}


def analyze(p: dict, static: Static, roster_role: str, now_ms: int) -> dict:
    allr = p["records"]
    role_r = [r for r in allr if r["role"] == roster_role]
    focus = role_r if len(role_r) >= 5 else allr
    tls = _tl(focus)
    total = len(allr)
    total30 = sum(1 for r in allr if now_ms - r["start"] < 30 * DAY)

    queues = defaultdict(list)
    for r in allr:
        queues[QUEUES.get(r["queue"], f"File {r['queue']}")].append(r)

    # last 10 & streak
    last10 = allr[:10]
    streak_n, streak_type = 0, None
    for r in allr:
        if streak_type is None:
            streak_type = r["win"]
        if r["win"] != streak_type:
            break
        streak_n += 1

    spells = Counter(tuple(r["spells"]) for r in focus)
    champs = _champ_rows(allr, static, now_ms)

    gd15s = [(t.get("gd15"), r["win"]) for r, t in ((r, r["tl"]) for r in focus if r.get("tl")) if t.get("gd15") is not None]
    ahead = [w for g, w in gd15s if g > 0]
    behind = [w for g, w in gd15s if g < 0]
    short = [r for r in focus if r["duration"] < 25 * 60]
    long_ = [r for r in focus if r["duration"] > 32 * 60]

    early = {
        "gd15": avg(t.get("gd15") for t in tls),
        "csd15": avg(t.get("csd15") for t in tls),
        "xpd15": avg(t.get("xpd15") for t in tls),
        "lanesWon": rate((t.get("gd15") > 0) if t.get("gd15") is not None else None for t in tls),
        "fb": rate(r["fb"] for r in focus),
        "soloKills": avg(r["soloKills"] for r in focus),
        "deaths14": avg(t.get("deaths14") for t in tls),
        "deathsGank14": avg(t.get("deathsGank14") for t in tls),
        "gd10": avg(t.get("gd10") for t in tls),
        "csd10": avg(t.get("csd10") for t in tls),
        "cs10": avg(t.get("cs10") for t in tls),
        "killsOnOpp14": avg(t.get("killsOnOpp14") for t in tls),
        "deaths1v1_14": avg(t.get("deaths1v1_14") for t in tls),
        "deaths1v1Opp14": avg(t.get("deaths1v1Opp14") for t in tls),
        "deaths1v1": avg(t.get("deaths1v1") for t in tls),
        "deaths6": avg(t.get("deaths6") for t in tls),
        "firstDeath": avg(t.get("firstDeath") for t in tls),
        "noDeath14": rate((t.get("deaths14") == 0) if "deaths14" in t else None for t in tls),
        "gaveFB": rate(t.get("gaveFB") for t in tls),
        "wrAhead15": sum(ahead) / len(ahead) if ahead else None, "gAhead15": len(ahead),
        "wrBehind15": sum(behind) / len(behind) if behind else None, "gBehind15": len(behind),
        "lvl6": avg(t.get("lvl6") for t in tls),
        "lvl6Diff": avg(t.get("lvl6Diff") for t in tls),
        "firstBack": avg(t.get("firstBack") for t in tls),
        "plates": avg(r["ch"].get("turretPlatesTaken") for r in focus),
        "laneMinions10": avg(r["ch"].get("laneMinionsFirst10Minutes") for r in focus),
    }
    kda = kda_of(focus)
    style = {
        "kp": avg(r["kp"] for r in focus),
        "dmgShare": avg(r["dmgShare"] for r in focus),
        "csm": avg(r["csm"] for r in focus),
        "vspm": avg(r["vspm"] for r in focus),
        "pinks": avg(r["pinks"] for r in focus),
        "dpm": avg(r["dpm"] for r in focus),
        "gpm": avg(r["gpm"] for r in focus),
        "takenShare": avg(r.get("takenShare") for r in focus),
        "timeDead": avg(r["timeDead"] for r in focus),
        "visionAdv": avg(r["ch"].get("visionScoreAdvantageLaneOpponent") for r in focus),
        "wardsKilled": avg(r["wardsKilled"] for r in focus),
        "wardsPlaced": avg(r["wardsPlaced"] for r in focus),
        "saves": avg(r["ch"].get("saveAllyFromDeath") for r in focus),
        "heals": avg(r["ch"].get("effectiveHealAndShielding") for r in focus),
        "cc": avg(r["ch"].get("enemyChampionImmobilizations") for r in focus),
        "dmgTypes": [sum(r["dmgTypes"][i] for r in focus) for i in range(3)],
    }
    jungle_extra = None
    if roster_role == "JUNGLE":
        jungle_extra = {
            "jgCs10": avg(r["ch"].get("jungleCsBefore10Minutes") for r in focus),
            "enemyCamps": avg(r["ch"].get("enemyJungleMonsterKills") for r in focus),
            "buffsStolen": avg(r["ch"].get("buffsStolen") for r in focus),
            "steals": sum(r["ch"].get("epicMonsterSteals", 0) or 0 for r in focus),
            "crabs": avg(r["ch"].get("initialCrabCount") for r in focus),
            "earliestDrake": avg(r["ch"].get("earliestDragonTakedown") for r in focus),
        }

    duration = {
        "avg": avg(r["duration"] for r in focus) / 60 if focus else None,
        "short": wr_block(short),
        "long": wr_block(long_),
    }

    side = {"blue": wr_block([r for r in focus if r["team"] == 100]),
            "red": wr_block([r for r in focus if r["team"] == 200])}

    # masteries: comfort picks not seen in ranked lately
    played = {c["champ"] for c in champs}
    pocket = []
    for m in p.get("masteries", [])[:20]:
        if m["championId"] not in played and m.get("championPoints", 0) >= 50000:
            pocket.append({"champ": m["championId"], "points": m["championPoints"], "level": m.get("championLevel"),
                           "last": m.get("lastPlayTime")})
    mastery_top = [{"champ": m["championId"], "points": m["championPoints"], "level": m.get("championLevel"),
                    "last": m.get("lastPlayTime")} for m in p.get("masteries", [])[:8]]

    obj = _objectives(focus)
    obj_part = avg(v["part"] for k, v in obj.items() if k in ("DRAGON", "HORDE", "RIFTHERALD", "BARON_NASHOR") and v["part"] is not None)

    surrender = {
        "ffLoss": rate(r["surrender"] for r in allr if not r["win"]),
        "earlyFF": sum(1 for r in allr if r["earlySurrender"]),
        "throws": sum(1 for r in allr if r.get("tl") and (r["tl"].get("teamGd20") or 0) >= 3000 and not r["win"]),
        "comebacks": sum(1 for r in allr if r.get("tl") and (r["tl"].get("teamGd20") or 0) <= -3000 and r["win"]),
        "ahead20": sum(1 for r in allr if r.get("tl") and (r["tl"].get("teamGd20") or 0) >= 3000),
        "behind20": sum(1 for r in allr if r.get("tl") and (r["tl"].get("teamGd20") or 0) <= -3000),
    }

    roles = Counter(r["role"] for r in allr)

    res = {
        "name": p["name"], "tag": p["tag"], "puuid": p["puuid"], "role": roster_role,
        "level": (p.get("summoner") or {}).get("summonerLevel"),
        "icon": (p.get("summoner") or {}).get("profileIconId"),
        "ranks": _ranks(p.get("leagues", [])),
        "spells": [[list(k), v] for k, v in spells.most_common(2)],
        "games": total, "roleGames": len(role_r), "focusGames": len(focus),
        "wr": wr_block(allr)["wr"], "focusWr": wr_block(focus)["wr"],
        "kda": kda,
        "queues": {q: wr_block(rs) for q, rs in queues.items()},
        "last10": {"w": sum(r["win"] for r in last10), "g": len(last10)},
        "streak": {"n": streak_n, "win": streak_type},
        "roles": dict(roles),
        "early": early, "style": style, "duration": duration, "jungle": jungle_extra,
        "champions": champs,
        "vsOpp": _vs_rows(focus, lambda r: r.get("opp"), min_games=2),
        "vsOppAll": _vs_rows(focus, lambda r: r.get("opp")),
        "vsClass": _vs_rows(focus, lambda r: static.champ_class(r["opp"]) if r.get("opp") else None),
        "bans": ban_candidates(champs),
        "rising": rising(champs, total, total30),
        "games30": total30,
        "movement": _movement(focus, roster_role),
        "side": side,
        "objectives": obj,
        "surrender": surrender,
        "pocket": pocket[:5],
        "masteryTop": mastery_top,
        "lastGame": allr[0]["start"] if allr else None,
        "firstGame": allr[-1]["start"] if allr else None,
    }
    res["objPart"] = obj_part
    # compact game log: lets the head-to-head find games where two teams met
    res["log"] = [[r["match"], r["team"], int(r["win"]), r["champ"], r["start"]] for r in allr]
    return res
