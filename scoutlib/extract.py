"""Turn one match (+ its timeline) into flat records.

`match_summary`  -> compact view of the whole game (both teams), used for
                    premades, team comps, smurf detection.
`player_record`  -> everything about one player in that game: end-of-game
                    stats, lane diffs at 10/15, early deaths, positions,
                    items, skills, objectives...
"""
from __future__ import annotations

from typing import Optional

from . import geo

ROLE_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
PING_KEYS = [
    "allInPings", "assistMePings", "basicPings", "commandPings", "dangerPings",
    "enemyMissingPings", "enemyVisionPings", "getBackPings", "holdPings",
    "needVisionPings", "onMyWayPings", "pushPings", "retreatPings", "visionClearedPings",
]
CHALLENGE_KEYS = [
    "soloKills", "killParticipation", "teamDamagePercentage", "damageTakenOnTeamPercentage",
    "visionScorePerMinute", "controlWardsPlaced", "laningPhaseGoldExpAdvantage",
    "maxCsAdvantageOnLaneOpponent", "maxLevelLeadLaneOpponent", "visionScoreAdvantageLaneOpponent",
    "skillshotsHit", "skillshotsDodged", "initialCrabCount", "initialBuffCount",
    "jungleCsBefore10Minutes", "enemyJungleMonsterKills", "buffsStolen", "epicMonsterSteals",
    "turretPlatesTaken", "killsOnOtherLanesEarlyJungleAsLaner", "getTakedownsInAllLanesEarlyJungleAsLaner",
    "teleportTakedowns", "outnumberedKills", "saveAllyFromDeath", "effectiveHealAndShielding",
    "enemyChampionImmobilizations", "takedownsFirstXMinutes", "laneMinionsFirst10Minutes",
    "earliestDragonTakedown", "scuttleCrabKills", "wardTakedownsBefore20M", "stealthWardsPlaced",
    "dodgeSkillShotsSmallWindow", "abilityUses", "survivedSingleDigitHpCount", "pickKillWithAlly",
    "killsNearEnemyTurret", "killsUnderOwnTurret", "quickSoloKills", "unseenRecalls",
    "takedownsBeforeJungleMinionSpawn", "multikillsAfterAggressiveFlash",
]


def role_of(p: dict) -> str:
    return p.get("teamPosition") or p.get("individualPosition") or "INVALID"


def valid_game(match: dict) -> bool:
    info = match.get("info", {})
    return (
        info.get("mapId") == 11
        and info.get("gameDuration", 0) >= 300
        and len(info.get("participants", [])) == 10
    )


def match_summary(match: dict) -> dict:
    info = match["info"]
    teams = {}
    for t in info.get("teams", []):
        teams[t["teamId"]] = {
            "win": t.get("win", False),
            "bans": [b["championId"] for b in t.get("bans", []) if b.get("championId", -1) > 0],
            "obj": {k: {"first": v.get("first", False), "kills": v.get("kills", 0)}
                    for k, v in t.get("objectives", {}).items()},
        }
    players = []
    for p in info["participants"]:
        players.append({
            "puuid": p.get("puuid"),
            "name": p.get("riotIdGameName") or p.get("summonerName") or "?",
            "tag": p.get("riotIdTagline") or "",
            "team": p.get("teamId"),
            "role": role_of(p),
            "champ": p.get("championId"),
            "champKey": p.get("championName"),
            "k": p.get("kills", 0), "d": p.get("deaths", 0), "a": p.get("assists", 0),
            "win": bool(p.get("win")),
            "level": p.get("summonerLevel"),
            "dmg": [p.get("physicalDamageDealtToChampions", 0), p.get("magicDamageDealtToChampions", 0),
                    p.get("trueDamageDealtToChampions", 0)],
        })
    return {
        "id": match["metadata"]["matchId"],
        "queue": info.get("queueId"),
        "start": info.get("gameStartTimestamp") or info.get("gameCreation"),
        "end": info.get("gameEndTimestamp") or (info.get("gameCreation", 0) + info.get("gameDuration", 0) * 1000),
        "duration": info.get("gameDuration", 0),
        "patch": ".".join(str(info.get("gameVersion", "")).split(".")[:2]),
        "teams": teams,
        "players": players,
    }


# ---------------------------------------------------------------------------
def _frame(frames, minute, pid):
    if minute < len(frames):
        return frames[minute]["participantFrames"].get(str(pid))
    return None


def _cs(pf):
    return pf.get("minionsKilled", 0) + pf.get("jungleMinionsKilled", 0)


def _parse_prefs(p: dict) -> dict:
    raw = p.get("selectedRolePreferences") or ""
    parts = raw.split(".") if raw else []
    return {
        "slot": parts[1] if len(parts) > 1 else None,           # PRIMARY / SECONDARY / AUTOFILL
        "primary": parts[2] if len(parts) > 2 else None,
        "secondary": parts[3] if len(parts) > 3 and parts[3] != "UNSELECTED" else None,
    }


def player_record(match: dict, timeline: Optional[dict], puuid: str, static) -> Optional[dict]:
    info = match["info"]
    parts = info["participants"]
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if me is None:
        return None
    pid = me["participantId"]
    team = me["teamId"]
    role = role_of(me)
    dur_s = max(info.get("gameDuration", 1), 1)
    dur_m = dur_s / 60
    ch = me.get("challenges") or {}

    allies = [p for p in parts if p["teamId"] == team]
    enemies = [p for p in parts if p["teamId"] != team]
    by_role_enemy = {role_of(p): p for p in enemies}
    by_role_ally = {role_of(p): p for p in allies}
    opp = by_role_enemy.get(role)
    enemy_jg = by_role_enemy.get("JUNGLE")
    pid_map = {p["participantId"]: p for p in parts}

    team_kills = sum(p.get("kills", 0) for p in allies)
    team_dmg = sum(p.get("totalDamageDealtToChampions", 0) for p in allies) or 1
    cs = me.get("totalMinionsKilled", 0) + me.get("neutralMinionsKilled", 0)

    styles = (me.get("perks") or {}).get("styles", [])
    keystone = styles[0]["selections"][0]["perk"] if styles and styles[0].get("selections") else None

    r = {
        "match": match["metadata"]["matchId"],
        "queue": info.get("queueId"),
        "start": info.get("gameStartTimestamp") or info.get("gameCreation"),
        "duration": dur_s,
        "patch": ".".join(str(info.get("gameVersion", "")).split(".")[:2]),
        "win": bool(me.get("win")),
        "team": team,
        "role": role,
        "champ": me.get("championId"),
        "champKey": me.get("championName"),
        "level": me.get("summonerLevel"),
        "k": me.get("kills", 0), "d": me.get("deaths", 0), "a": me.get("assists", 0),
        "kp": (me.get("kills", 0) + me.get("assists", 0)) / team_kills if team_kills else 0,
        "dmgShare": me.get("totalDamageDealtToChampions", 0) / team_dmg,
        "dpm": me.get("totalDamageDealtToChampions", 0) / dur_m,
        "dmgTypes": [me.get("physicalDamageDealtToChampions", 0), me.get("magicDamageDealtToChampions", 0),
                     me.get("trueDamageDealtToChampions", 0)],
        "takenShare": ch.get("damageTakenOnTeamPercentage"),
        "csm": cs / dur_m,
        "gpm": me.get("goldEarned", 0) / dur_m,
        "vspm": me.get("visionScore", 0) / dur_m,
        "pinks": me.get("visionWardsBoughtInGame", 0),
        "wardsPlaced": me.get("wardsPlaced", 0),
        "wardsKilled": me.get("wardsKilled", 0),
        "fb": bool(me.get("firstBloodKill") or me.get("firstBloodAssist")),
        "soloKills": ch.get("soloKills", 0),
        "multi": [me.get("doubleKills", 0), me.get("tripleKills", 0), me.get("quadraKills", 0), me.get("pentaKills", 0)],
        "spells": sorted([me.get("summoner1Id"), me.get("summoner2Id")], key=lambda s: (s != 4, s)),  # Flash first
        "keystone": keystone,
        "styles": [s.get("style") for s in styles],
        "items": [me.get(f"item{i}") for i in range(6) if me.get(f"item{i}")],
        "prefs": _parse_prefs(me),
        "surrender": bool(me.get("gameEndedInSurrender")),
        "earlySurrender": bool(me.get("gameEndedInEarlySurrender")),
        "afk": bool(me.get("wasAfk")) if me.get("wasAfk") is not None else False,
        "timeDead": me.get("totalTimeSpentDead", 0) / dur_s,
        "pings": {k: me.get(k, 0) for k in PING_KEYS},
        "ch": {k: ch.get(k) for k in CHALLENGE_KEYS if ch.get(k) is not None},
        "spellCasts": [me.get(f"spell{i}Casts", 0) for i in range(1, 5)],
        # opponents / allies (for matchup and botlane tables)
        "opp": opp.get("championId") if opp else None,
        "oppKey": opp.get("championName") if opp else None,
        "enemyBot": [by_role_enemy[r].get("championId") if r in by_role_enemy else None for r in ("BOTTOM", "UTILITY")],
        "allyBot": [by_role_ally[r].get("puuid") if r in by_role_ally else None for r in ("BOTTOM", "UTILITY")],
        "allyBotChamps": [by_role_ally[r].get("championId") if r in by_role_ally else None for r in ("BOTTOM", "UTILITY")],
        "teamFirst": {},
        "tl": None,
    }
    for t in info.get("teams", []):
        if t["teamId"] == team:
            r["teamFirst"] = {k: v.get("first", False) for k, v in t.get("objectives", {}).items()}

    if timeline and timeline.get("info", {}).get("frames"):
        try:
            r["tl"] = _timeline_part(timeline, me, opp, enemy_jg, allies, enemies, by_role_enemy, pid_map, static)
        except Exception:
            r["tl"] = None
    return r


def _timeline_part(timeline, me, opp, enemy_jg, allies, enemies, by_role_enemy, pid_map, static) -> dict:
    frames = timeline["info"]["frames"]
    pid = me["participantId"]
    team = me["teamId"]
    role = role_of(me)
    opp_pid = opp["participantId"] if opp else None
    ejg_pid = enemy_jg["participantId"] if enemy_jg else None
    ally_pids = {p["participantId"] for p in allies}
    enemy_pids = {p["participantId"] for p in enemies}
    if role in ("BOTTOM", "UTILITY"):
        lane_enemies = {by_role_enemy[r]["participantId"] for r in ("BOTTOM", "UTILITY") if r in by_role_enemy}
    else:
        lane_enemies = {opp_pid} if opp_pid else set()

    out: dict = {}

    # ---- lane diffs at 10 / 15 ----------------------------------------
    for m in (10, 15):
        a = _frame(frames, m, pid)
        b = _frame(frames, m, opp_pid) if opp_pid else None
        if a:
            out[f"cs{m}"] = _cs(a)
            out[f"gold{m}"] = a.get("totalGold", 0)
            out[f"xp{m}"] = a.get("xp", 0)
        if a and b:
            out[f"gd{m}"] = a.get("totalGold", 0) - b.get("totalGold", 0)
            out[f"csd{m}"] = _cs(a) - _cs(b)
            out[f"xpd{m}"] = a.get("xp", 0) - b.get("xp", 0)
    for m in (15, 20):
        if m < len(frames):
            pfs = frames[m]["participantFrames"]
            mine = sum(pfs.get(str(p), {}).get("totalGold", 0) for p in ally_pids)
            theirs = sum(pfs.get(str(p), {}).get("totalGold", 0) for p in enemy_pids)
            out[f"teamGd{m}"] = mine - theirs
    # bot lane gold diff at 15 (ADC + support vs theirs)
    if role in ("BOTTOM", "UTILITY") and len(frames) > 15:
        pfs = frames[15]["participantFrames"]
        ally_bot = [p["participantId"] for p in allies if role_of(p) in ("BOTTOM", "UTILITY")]
        enemy_bot = [p["participantId"] for p in enemies if role_of(p) in ("BOTTOM", "UTILITY")]
        if len(ally_bot) == 2 and len(enemy_bot) == 2:
            out["botGd15"] = sum(pfs[str(p)]["totalGold"] for p in ally_bot) - sum(pfs[str(p)]["totalGold"] for p in enemy_bot)

    # ---- positions (one per minute) ------------------------------------
    pos = []
    for m in range(1, min(len(frames), 21)):
        pf = frames[m]["participantFrames"].get(str(pid))
        if pf and pf.get("position"):
            pos.append([m, pf["position"]["x"], pf["position"]["y"]])
    out["pos"] = pos
    zones = {m: geo.zone(x, y, team) for m, x, y in pos}
    out["zones"] = {m: z for m, z in zones.items() if m <= 14}

    # ---- events ----------------------------------------------------------
    events = [e for f in frames for e in f.get("events", [])]
    kills = [e for e in events if e.get("type") == "CHAMPION_KILL"]
    early = []          # kills/assists/deaths before 14 min with position
    deaths_14 = deaths_6 = deaths_gank = deaths_1v1_14 = deaths_1v1_opp_14 = deaths_1v1 = 0
    kills_on_opp_14 = 0
    first_death = None
    first_takedown = None
    gave_fb = bool(kills) and kills[0].get("victimId") == pid
    for e in kills:
        t = e.get("timestamp", 0) / 1000
        killer = e.get("killerId", 0)
        victim = e.get("victimId")
        assists = e.get("assistingParticipantIds") or []
        p = e.get("position") or {}
        x, y = p.get("x"), p.get("y")
        involved = {killer, *assists}
        if victim == pid:
            solo = 1 <= killer <= 10 and not assists
            if solo:
                deaths_1v1 += 1
            if first_death is None:
                first_death = t
            if t < 14 * 60:
                deaths_14 += 1
                if t < 6 * 60:
                    deaths_6 += 1
                if solo:
                    deaths_1v1_14 += 1
                    if killer == opp_pid:
                        deaths_1v1_opp_14 += 1
                if role == "JUNGLE":
                    if ejg_pid in involved:
                        deaths_gank += 1
                elif any(q in enemy_pids and q not in lane_enemies for q in involved):
                    deaths_gank += 1
                if x is not None:
                    early.append([round(t), x, y, "d"])
        elif killer == pid or pid in assists:
            kind = "k" if killer == pid else "a"
            if first_takedown is None and x is not None:
                first_takedown = {"t": round(t), "zone": geo.zone(x, y, team), "kind": kind}
            if t < 14 * 60:
                if kind == "k" and victim == opp_pid:
                    kills_on_opp_14 += 1
                if x is not None:
                    early.append([round(t), x, y, kind])
    out.update({
        "deaths14": deaths_14, "deaths6": deaths_6, "deathsGank14": deaths_gank,
        "deaths1v1_14": deaths_1v1_14, "deaths1v1Opp14": deaths_1v1_opp_14, "deaths1v1": deaths_1v1,
        "killsOnOpp14": kills_on_opp_14, "firstDeath": first_death, "gaveFB": gave_fb,
        "early": early, "firstTakedown": first_takedown,
    })

    # ---- level 6 timing ------------------------------------------------
    lvl6 = {}
    for e in events:
        if e.get("type") == "LEVEL_UP" and e.get("level") == 6 and e.get("participantId") not in lvl6:
            lvl6[e["participantId"]] = e["timestamp"] / 1000
    out["lvl6"] = lvl6.get(pid)
    if opp_pid and pid in lvl6 and opp_pid in lvl6:
        out["lvl6Diff"] = lvl6[pid] - lvl6[opp_pid]

    # ---- objectives participation -------------------------------------
    obj = {}
    for e in events:
        if e.get("type") != "ELITE_MONSTER_KILL":
            continue
        mtype = e.get("monsterType")
        kteam = e.get("killerTeamId") or (pid_map.get(e.get("killerId"), {}).get("teamId"))
        o = obj.setdefault(mtype, {"team": 0, "me": 0, "enemy": 0, "firstT": None})
        if kteam == team:
            o["team"] += 1
            if o["firstT"] is None:
                o["firstT"] = round(e["timestamp"] / 1000)
            if e.get("killerId") == pid or pid in (e.get("assistingParticipantIds") or []):
                o["me"] += 1
        else:
            o["enemy"] += 1
    out["obj"] = obj

    # ---- items -----------------------------------------------------------
    bought = []
    for e in events:
        if e.get("participantId") != pid:
            continue
        if e.get("type") == "ITEM_PURCHASED":
            bought.append([e["timestamp"] / 1000, e["itemId"]])
        elif e.get("type") == "ITEM_UNDO" and e.get("beforeId"):
            for i in range(len(bought) - 1, -1, -1):
                if bought[i][1] == e["beforeId"]:
                    bought.pop(i)
                    break
    legendaries = []
    for t, iid in bought:
        if static.is_legendary(iid) and iid not in [x[1] for x in legendaries]:
            legendaries.append([round(t), iid])
    out["build"] = legendaries[:4]
    out["start"] = sorted({iid for t, iid in bought if t < 60})
    boots = [iid for t, iid in bought if static.items.get(iid, {}).get("boots") and static.items[iid]["gold"] > 300]
    out["boots"] = boots[0] if boots else None
    later = [t for t, iid in bought if t > 150]
    out["firstBack"] = round(later[0]) if later else None

    # ---- skills ----------------------------------------------------------
    counts = {1: 0, 2: 0, 3: 0}
    maxed = []
    seq = []
    for e in events:
        if e.get("type") == "SKILL_LEVEL_UP" and e.get("participantId") == pid and e.get("levelUpType") == "NORMAL":
            s = e.get("skillSlot")
            if s in counts:
                counts[s] += 1
                seq.append(s)
                if counts[s] == 5:
                    maxed.append(s)
    rest = sorted([s for s in counts if s not in maxed], key=lambda s: -counts[s])
    order = maxed + rest
    out["skillOrder"] = "".join("QWE"[s - 1] for s in order) if sum(counts.values()) >= 6 else None
    out["skillStart"] = "".join("QWE"[s - 1] for s in seq[:3]) if len(seq) >= 3 else None

    # ---- wards -------------------------------------------------------------
    wards = {}
    wards14 = 0
    for e in events:
        if e.get("type") == "WARD_PLACED" and e.get("creatorId") == pid:
            wt = e.get("wardType", "UNDEFINED")
            wards[wt] = wards.get(wt, 0) + 1
            if e["timestamp"] < 14 * 60000:
                wards14 += 1
    out["wards"] = wards
    out["wards14"] = wards14

    # ---- movement patterns ------------------------------------------------
    pos_by_min = {m: (x, y) for m, x, y in pos}
    if role == "JUNGLE":
        z1 = zones.get(1)
        p1 = pos_by_min.get(1)
        out["invade1"] = z1 in geo.ENEMY_JUNGLE or any(
            ev[3] in "ka" and ev[0] < 100 and geo.zone(ev[1], ev[2], team) in geo.ENEMY_JUNGLE for ev in early)
        out["startSide"] = geo.side(*p1) if p1 else None
        out["enemyJg6"] = any(zones.get(m) in geo.ENEMY_JUNGLE for m in range(2, 7))
        out["scuttle34"] = any(zones.get(m) in geo.RIVERS for m in (3, 4))
        out["back35"] = any(zones.get(m) == geo.BASE for m in (3, 4, 5))
        out["at3"] = zones.get(3)
        out["at4"] = zones.get(4)
        first_lane = None
        for m in range(2, 11):
            if zones.get(m) in geo.LANES:
                first_lane = {"lane": zones[m], "m": m}
                break
        out["firstLane"] = first_lane
    if role in ("TOP", "MIDDLE", "BOTTOM", "UTILITY"):
        home = {
            "TOP": {geo.LANE_TOP},
            "MIDDLE": {geo.LANE_MID},
            "BOTTOM": {geo.LANE_BOT},
            "UTILITY": {geo.LANE_BOT},
        }[role]
        roam = None
        for m in range(3, 15):
            p = pos_by_min.get(m)
            if not p:
                continue
            z = zones.get(m)
            if role == "MIDDLE":
                is_roam = z in (geo.LANE_TOP, geo.LANE_BOT) or geo.at_pit(*p) is not None
            elif role == "UTILITY":
                is_roam = z in (geo.LANE_MID, geo.LANE_TOP, geo.RIVER_TOP, geo.JG_ALLY_TOP, geo.JG_ENEMY_TOP)
            elif role == "TOP":
                is_roam = z in (geo.LANE_MID, geo.LANE_BOT) or geo.at_pit(*p) == "Drake"
            else:  # ADC
                is_roam = z in (geo.LANE_MID, geo.LANE_TOP) or geo.at_pit(*p) == "Nashor"
            if is_roam and z not in home:
                pit = geo.at_pit(*p)
                roam = {"m": m, "zone": z, "side": geo.side(*p), "pit": pit}
                break
        out["roam"] = roam
        if role == "MIDDLE":
            out["takedownsOutside"] = sum(
                1 for t, x, y, k in early
                if k in "ka" and t >= 180 and (geo.zone(x, y, team) in (geo.LANE_TOP, geo.LANE_BOT) or geo.at_pit(x, y)))
            out["takedownsOutsideTop"] = sum(
                1 for t, x, y, k in early
                if k in "ka" and t >= 180 and geo.side(x, y) == "top"
                and (geo.zone(x, y, team) == geo.LANE_TOP or geo.at_pit(x, y)))
            out["takedownsOutsideBot"] = out["takedownsOutside"] - out["takedownsOutsideTop"]
            out["takedowns3_14"] = sum(1 for t, x, y, k in early if k in "ka" and t >= 180)
    return out
