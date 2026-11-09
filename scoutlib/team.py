"""Team-level analysis: botlane duo, premades, games played as a stack."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from .static import QUEUES, Static
from .stats import avg, kda_of, top, wr_block

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
ROLE_FR = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}


def _team_of(summary: dict, puuid: str):
    for pl in summary["players"]:
        if pl["puuid"] == puuid:
            return pl["team"]
    return None


def _vs_table(records: list, key) -> list:
    by = defaultdict(list)
    for r in records:
        k = key(r)
        if k:
            by[k].append(r)
    rows = []
    for k, rs in by.items():
        wb = wr_block(rs)
        rows.append({"key": k, "g": wb["g"], "wr": wb["wr"], "kda": kda_of(rs)["ratio"],
                     "gd15": avg((r.get("tl") or {}).get("gd15") for r in rs),
                     "played": top(Counter(r["champ"] for r in rs), 3)})
    rows.sort(key=lambda x: -x["g"])
    return rows


def botlane(players: dict, static: Static) -> dict | None:
    adc = players.get("BOTTOM")
    sup = players.get("UTILITY")
    if not adc or not sup:
        return None
    adc_r = [r for r in adc["records"] if r["role"] == "BOTTOM"]
    sup_r = [r for r in sup["records"] if r["role"] == "UTILITY"]
    duo = [r for r in adc_r if r["allyBot"][1] == sup["puuid"]]
    duo_ids = {r["match"] for r in duo}
    sup_by_match = {r["match"]: r for r in sup_r}
    adc_solo = [r for r in adc_r if r["match"] not in duo_ids]
    sup_solo = [r for r in sup_r if r["match"] not in duo_ids]

    pairs = defaultdict(list)
    for r in duo:
        pairs[(r["champ"], r["allyBotChamps"][1])].append(r)
    pair_rows = []
    for (a, s), rs in pairs.items():
        wb = wr_block(rs)
        pair_rows.append({"adc": a, "sup": s, "g": wb["g"], "wr": wb["wr"], "kda": kda_of(rs)["ratio"],
                          "gd15": avg((r.get("tl") or {}).get("gd15") for r in rs)})
    pair_rows.sort(key=lambda x: -x["g"])

    def ecls(r, i):
        c = r["enemyBot"][i]
        return static.champ_classes2(c) if c else None

    return {
        "adc": f"{adc['name']}#{adc['tag']}", "sup": f"{sup['name']}#{sup['tag']}",
        "duo": wr_block(duo),
        "adcSolo": wr_block(adc_solo),
        "supSolo": wr_block(sup_solo),
        "botGd15": avg((r.get("tl") or {}).get("botGd15") for r in duo),
        "pairs": pair_rows[:8],
        "duoVsSup": _vs_table(duo, lambda r: ecls(r, 1)),
        "duoVsAdc": _vs_table(duo, lambda r: ecls(r, 0)),
        "duoVsCombo": _vs_table(duo, lambda r: (
            f"{static.champ_class(r['enemyBot'][0])} + {static.champ_class(r['enemyBot'][1])}"
            if all(r["enemyBot"]) else None)),
        "adcVsSup": _vs_table(adc_r, lambda r: ecls(r, 1)),
        "supVsAdc": _vs_table(sup_r, lambda r: ecls(r, 0)),
        "duoGames": [{"match": r["match"], "start": r["start"], "win": r["win"], "adc": r["champ"],
                      "sup": r["allyBotChamps"][1]} for r in duo[:10]],
    }


def premades(players: dict, summaries: dict) -> dict:
    roster = {p["puuid"]: f"{p['name']}#{p['tag']}" for p in players.values()}
    roster_role = {p["puuid"]: role for role, p in players.items()}
    pair = defaultdict(lambda: [0, 0])
    groups = Counter()
    outsiders = defaultdict(lambda: {"g": 0, "w": 0, "with": Counter(), "roles": Counter(), "name": "", "level": None})
    seen = set()
    for mid, s in summaries.items():
        for team in (100, 200):
            members = [pl for pl in s["players"] if pl["team"] == team and pl["puuid"] in roster]
            if not members:
                continue
            key = (mid, team)
            if key in seen:
                continue
            seen.add(key)
            win = members[0]["win"]
            for a, b in combinations(sorted(m["puuid"] for m in members), 2):
                pair[(a, b)][0] += 1
                pair[(a, b)][1] += win
            if len(members) >= 3:
                groups[len(members)] += 1
            for pl in s["players"]:
                if pl["team"] != team or pl["puuid"] in roster:
                    continue
                o = outsiders[pl["puuid"]]
                o["g"] += 1
                o["w"] += pl["win"]
                o["name"] = f"{pl['name']}#{pl['tag']}"
                o["level"] = pl.get("level")
                o["roles"][pl["role"]] += 1
                for m in members:
                    o["with"][m["puuid"]] += 1
    pairs = [{"a": roster[a], "b": roster[b], "g": v[0], "wr": v[1] / v[0]} for (a, b), v in pair.items()]
    pairs.sort(key=lambda x: -x["g"])
    regulars = []
    for puuid, o in outsiders.items():
        if o["g"] < 3:
            continue
        regulars.append({
            "puuid": puuid, "name": o["name"], "g": o["g"], "wr": o["w"] / o["g"], "level": o["level"],
            "with": [roster[p] for p, _ in o["with"].most_common()],
            "withCount": {roster[p]: n for p, n in o["with"].items()},
            "roles": [ROLE_FR.get(r, r) for r, _ in o["roles"].most_common(2)],
            "mainRole": o["roles"].most_common(1)[0][0],
        })
    regulars.sort(key=lambda x: -x["g"])
    return {"pairs": pairs, "groups": dict(groups), "regulars": regulars[:25],
            "_outsiders": outsiders, "_roster_role": roster_role}


def stack_games(players: dict, summaries: dict, static: Static) -> dict | None:
    roster = {p["puuid"]: role for role, p in players.items()}
    names = {p["puuid"]: p["name"] for p in players.values()}
    games = []
    for mid, s in summaries.items():
        for team in (100, 200):
            members = [pl for pl in s["players"] if pl["team"] == team and pl["puuid"] in roster]
            if len(members) >= 3:
                games.append((s, team, members))
    if not games:
        return None
    games.sort(key=lambda x: -x[0]["start"])
    n = len(games)
    wins = sum(1 for s, t, _ in games if s["teams"][t]["win"])
    queues = Counter(QUEUES.get(s["queue"], str(s["queue"])) for s, _, _ in games)
    sizes = Counter(len(m) for _, _, m in games)

    per_player = {}
    for puuid, role in roster.items():
        champs = Counter()
        roles = Counter()
        g = 0
        for s, t, members in games:
            me = next((m for m in members if m["puuid"] == puuid), None)
            if me:
                g += 1
                champs[me["champ"]] += 1
                roles[me["role"]] += 1
        per_player[role] = {
            "name": names[puuid], "g": g, "champs": top(champs, 8),
            "otherRoles": [[ROLE_FR.get(r, r), c] for r, c in roles.most_common() if r != role],
        }

    # recurring duos between roster members
    duo = defaultdict(lambda: [0, 0])
    for s, t, members in games:
        win = s["teams"][t]["win"]
        for a, b in combinations(sorted(members, key=lambda m: ROLES.index(m["role"]) if m["role"] in ROLES else 9), 2):
            key = (a["role"], a["champ"], b["role"], b["champ"])
            duo[key][0] += 1
            duo[key][1] += win
    duos = [{"roles": f"{ROLE_FR.get(k[0], k[0])} + {ROLE_FR.get(k[2], k[2])}", "a": k[1], "b": k[3],
             "g": v[0], "wr": v[1] / v[0]} for k, v in duo.items() if v[0] >= 2]
    duos.sort(key=lambda x: (-x["g"], -x["wr"]))

    bans = Counter()
    for s, t, _ in games:
        bans.update(s["teams"][t]["bans"])

    # champions reserved to stack games
    reserved = []
    for role, p in players.items():
        stack_ids = {s["id"] for s, t, m in games if any(x["puuid"] == p["puuid"] for x in m)}
        inside = Counter(r["champ"] for r in p["records"] if r["match"] in stack_ids)
        outside = Counter(r["champ"] for r in p["records"] if r["match"] not in stack_ids)
        for c, g in inside.items():
            if g >= 2 and outside[c] <= 1:
                w = sum(1 for r in p["records"] if r["match"] in stack_ids and r["champ"] == c and r["win"])
                reserved.append({"champ": c, "player": p["name"], "g": g, "w": w, "outside": outside[c]})
    reserved.sort(key=lambda x: -x["g"])

    cls_us, cls_them = Counter(), Counter()
    dmg = [0, 0, 0]
    for s, t, _ in games:
        for pl in s["players"]:
            c = static.champ_class(pl["champ"])
            (cls_us if pl["team"] == t else cls_them)[c] += 1
            if pl["team"] == t:
                for i in range(3):
                    dmg[i] += pl["dmg"][i]
    total_dmg = sum(dmg) or 1
    classes = sorted(set(cls_us) | set(cls_them), key=lambda c: -cls_us[c])
    profile = [{"cls": c, "us": cls_us[c] / n, "them": cls_them[c] / n} for c in classes if c != "?"]

    buckets = {"Moins de 25 min": [], "25 à 32 min": [], "Plus de 32 min": []}
    for s, t, _ in games:
        d = s["duration"] / 60
        key = "Moins de 25 min" if d < 25 else "Plus de 32 min" if d > 32 else "25 à 32 min"
        buckets[key].append(s["teams"][t]["win"])
    durations = [{"label": k, "g": len(v), "wr": sum(v) / len(v) if v else None} for k, v in buckets.items()]

    objectives = []
    for key, label in (("champion", "First blood"), ("tower", "1re tour"), ("dragon", "1er drake"),
                       ("horde", "1ers grubs"), ("riftHerald", "Héraut"), ("baron", "1er nashor"),
                       ("atakhan", "Atakhan")):
        firsts = [s["teams"][t]["obj"].get(key) for s, t, _ in games]
        firsts = [f for f in firsts if f is not None]
        if not firsts:
            continue
        objectives.append({"label": label, "first": sum(f["first"] for f in firsts) / len(firsts),
                           "perGame": sum(f["kills"] for f in firsts) / len(firsts)})

    def comp(s, team):
        pls = [pl for pl in s["players"] if pl["team"] == team]
        pls.sort(key=lambda pl: ROLES.index(pl["role"]) if pl["role"] in ROLES else 9)
        return [[pl["champ"], pl["puuid"] in roster] for pl in pls]

    recent = [{
        "start": s["start"], "queue": QUEUES.get(s["queue"], str(s["queue"])), "win": s["teams"][t]["win"],
        "duration": s["duration"], "us": comp(s, t), "them": comp(s, 300 - t), "n": len(m),
    } for s, t, m in games[:15]]

    return {
        "n": n, "wins": wins, "wr": wins / n, "queues": dict(queues), "sizes": dict(sizes),
        "last": games[0][0]["start"], "players": per_player, "duos": duos[:6],
        "bans": top(bans, 10), "reserved": reserved[:8], "profile": profile,
        "dmg": [d / total_dmg for d in dmg], "durations": durations, "objectives": objectives,
        "recent": recent,
    }


def team_bans(players_out: list, n: int = 5) -> list:
    cands = []
    for p in players_out:
        for b in p["bans"]:
            label = f"{p['name']}#{p['tag']}"
            if p.get("smurfOf"):
                label += f" (smurf de {p['smurfOf']['name']})"
            cands.append({**b, "player": label})
    cands.sort(key=lambda x: -x["score"])
    seen, out = set(), []
    for c in cands:
        if c["champ"] in seen:
            continue
        seen.add(c["champ"])
        out.append(c)
    return out[:n]
