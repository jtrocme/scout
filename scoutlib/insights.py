"""Signals: the stand-out numbers of a player, as table rows.

Each signal: {"cat", "tone", "label", "value", "ctx", "champ"?}.
tone is from the scouting team's point of view: "bad" = weakness to exploit,
"good" = strength to respect, "info" = neutral fact worth knowing.
Thresholds are absolute (no league comparison).
"""
from __future__ import annotations

ROLE_FR = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}


def _pct(x):
    return f"{round(100 * x)} %"


def _num(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _signed(x):
    return f"{'+' if x >= 0 else '−'}{abs(round(x))}"


def player_signals(p: dict) -> list:
    out = []
    e, st = p["early"], p["style"]
    role = p["role"]
    champs = p["champions"]
    total = p["games"] or 1

    def add(cat, tone, label, value, ctx="", champ=None):
        out.append({"cat": cat, "tone": tone, "label": label, "value": value, "ctx": ctx, "champ": champ})

    # ---- champions
    for r in p["rising"][:2]:
        add("Champions", "info", "En hausse", f"{r['g30']} g / 30 j",
            f"{_pct(r['share30'])} récent vs {_pct(r['share'])} période", r["champ"])
    if champs:
        c0 = champs[0]
        share = c0["g"] / total
        if share >= 0.4 and c0["g"] >= 8:
            add("Champions", "good", "Quasi mono", f"{_pct(share)} des games", f"{_pct(c0['wr'])} WR", c0["champ"])
        top3 = sum(c["g"] for c in champs[:3]) / total
        if top3 >= 0.75 and total >= 15:
            add("Champions", "info", "Pool serré", f"top 3 = {_pct(top3)}")
        if len(champs) >= 15 and share < 0.2:
            add("Champions", "info", "Pool large", f"{len(champs)} champions")
        for c in champs[:6]:
            if c["g"] >= 6 and c["wr"] is not None and c["wr"] <= 0.35:
                add("Champions", "bad", "Pick perdant joué", f"{_pct(c['wr'])} WR", f"{c['g']} g", c["champ"])
    for pk in p.get("pocket", [])[:2]:
        add("Champions", "info", "Pick caché", f"{round(pk['points'] / 1000)}k pts", "0 ranked sur la période", pk["champ"])

    # ---- early
    jg = role == "JUNGLE"
    if e.get("gd15") is not None and role != "UTILITY":
        if e["gd15"] >= 400:
            add("Early", "good", "GD@15 vs jungler adverse" if jg else "GD@15", _signed(e["gd15"]),
                f"devant {_pct(e['lanesWon'] or 0)} des games")
        elif e["gd15"] <= -300:
            add("Early", "bad", "GD@15 vs jungler adverse" if jg else "GD@15", _signed(e["gd15"]),
                f"devant {_pct(e['lanesWon'] or 0)} des games")
    d14, dg = e.get("deaths14"), e.get("deathsGank14")
    if d14 is not None and d14 >= 2.2:
        add("Early", "bad", "Morts < 14 min", f"{_num(d14)} / game",
            f"{_num(dg)} {'vs jungler adv.' if jg else 'sur gank'}")
    d1 = e.get("deaths1v1_14")
    if d1 is not None and d1 >= 0.6 and not jg:
        add("Early", "bad", "Tué en 1v1 < 14 min", f"{_num(d1)} / game", f"{_num(e.get('deaths1v1Opp14'))} par vis-à-vis")
    if e.get("soloKills") is not None and e["soloKills"] >= 2 and role in ("TOP", "MIDDLE"):
        add("Early", "good", "Solo kills", f"{_num(e['soloKills'])} / game")
    ga, gb = e.get("gAhead15", 0), e.get("gBehind15", 0)
    if ga >= 8 and e.get("wrAhead15") is not None and e["wrAhead15"] < 0.5:
        add("Early", "bad", "WR en avance @15", _pct(e["wrAhead15"]), f"{ga} g")
    if gb >= 8 and e.get("wrBehind15") is not None and e["wrBehind15"] >= 0.55:
        add("Early", "good", "WR en retard @15", _pct(e["wrBehind15"]), f"{gb} g")
    if e.get("lvl6Diff") is not None and role in ("TOP", "MIDDLE") and abs(e["lvl6Diff"]) >= 25:
        add("Early", "good" if e["lvl6Diff"] < 0 else "bad", "Niveau 6 vs vis-à-vis", f"{_signed(e['lvl6Diff'])} s")
    if e.get("gaveFB") is not None and e["gaveFB"] >= 0.15:
        add("Early", "bad", "First blood donné", _pct(e["gaveFB"]))
    if e.get("fb") is not None and e["fb"] >= 0.35:
        add("Early", "good", "Participation first blood", _pct(e["fb"]))

    # ---- matchups
    for r in p["vsOppAll"]:
        if r["g"] >= 3 and r["wr"] == 0:
            add("Matchups", "bad", "Vis-à-vis", f"0/{r['g']}", "", r["key"])
        elif r["g"] >= 4 and r["wr"] is not None and r["wr"] >= 0.8:
            add("Matchups", "good", "Vis-à-vis", f"{round(r['wr'] * r['g'])}/{r['g']}", "", r["key"])
    for r in p["vsClass"]:
        if r["g"] >= 5 and r["wr"] is not None and (r["wr"] >= 0.75 or r["wr"] <= 0.35):
            add("Matchups", "good" if r["wr"] >= 0.75 else "bad", f"Vs {r['key']}", _pct(r["wr"]), f"{r['g']} g")

    # ---- trends
    l10 = p["last10"]
    if l10["g"] >= 8 and (l10["w"] >= 7 or l10["w"] <= 3):
        add("Tendances", "good" if l10["w"] >= 7 else "bad", "10 dernières", f"{l10['w']}/{l10['g']}")
    du = p["duration"]
    s, lg = du["short"], du["long"]
    if s["g"] >= 5 and lg["g"] >= 5 and s["wr"] is not None and lg["wr"] is not None and abs(lg["wr"] - s["wr"]) >= 0.15:
        add("Tendances", "info", "WR < 25 min / > 32 min", f"{_pct(s['wr'])} / {_pct(lg['wr'])}",
            "meilleur en late" if lg["wr"] > s["wr"] else "meilleur en early")
    if p["games"] >= 10:
        share = p["roleGames"] / p["games"]
        if share < 0.6:
            others = sorted(((r, n) for r, n in p["roles"].items() if r != role and r in ROLE_FR), key=lambda x: -x[1])[:2]
            add("Tendances", "info", f"Games au rôle {ROLE_FR.get(role)}", _pct(share),
                ", ".join(f"{ROLE_FR[r]} ×{n}" for r, n in others))
    sd = p["side"]
    if sd["blue"]["g"] >= 8 and sd["red"]["g"] >= 8 and abs(sd["blue"]["wr"] - sd["red"]["wr"]) >= 0.15:
        add("Tendances", "info", "WR bleu / rouge", f"{_pct(sd['blue']['wr'])} / {_pct(sd['red']['wr'])}")
    su = p["surrender"]
    if su["ahead20"] >= 6 and su["throws"] / su["ahead20"] >= 0.3:
        add("Tendances", "bad", "Avances perdues (+3k @20)", f"{su['throws']}/{su['ahead20']}")
    if su["behind20"] >= 6 and su["comebacks"] / su["behind20"] >= 0.35:
        add("Tendances", "good", "Remontées (−3k @20)", f"{su['comebacks']}/{su['behind20']}")

    # ---- role specific
    mv = p.get("movement") or {}
    if jg and mv:
        if mv.get("invade1") is not None and mv["invade1"] >= 0.15:
            add("Jungle", "info", "Invade niv. 1", _pct(mv["invade1"]))
        if mv.get("scuttle34") is not None and mv["scuttle34"] >= 0.35:
            add("Jungle", "info", "Scuttle 3-4 min", _pct(mv["scuttle34"]))
        if mv.get("firstLane"):
            l, n, m = mv["firstLane"][0]
            add("Jungle", "info", "1re lane visitée", l.replace("Lane ", ""), f"{n}/{mv['games']} g · ≈ {_num(m, 0)} min")
        if mv.get("firstTakedown"):
            l, n, t = mv["firstTakedown"][0]
            add("Jungle", "info", "1er kill/assist", l, f"{n}/{mv['games']} g · ≈ {_num(t)} min")
        if mv.get("startSide"):
            sidex, n = mv["startSide"][0]
            if mv["games"] >= 6 and n / mv["games"] >= 0.7:
                add("Jungle", "info", "Côté de départ", sidex, f"{n}/{mv['games']} g")
        jgx = p.get("jungle") or {}
        if jgx.get("enemyCamps") and jgx["enemyCamps"] >= 6:
            add("Jungle", "info", "Camps adverses volés", f"{_num(jgx['enemyCamps'])} / game")
    if role == "MIDDLE" and mv.get("roamRate") is not None and (mv["roamRate"] >= 0.5 or mv["roamRate"] <= 0.25):
        add("Roams", "info", "Roam 3-14 min", _pct(mv["roamRate"]),
            f"1er ≈ {_num(mv.get('firstRoam'), 0)} min" if mv.get("firstRoam") else "")
        o = mv.get("outside") or {}
        if o.get("of", 0) >= 15:
            add("Roams", "info", "Kills/assists hors mid", _pct(o["n"] / o["of"]), f"{o['n']}/{o['of']}")
    if role == "UTILITY":
        v = st.get("vspm")
        if v is not None and (v < 2.2 or v >= 2.8):
            add("Support", "bad" if v < 2.2 else "good", "Vision / min", _num(v, 2))
        if mv.get("roamRate") is not None and (mv["roamRate"] <= 0.3 or mv["roamRate"] >= 0.55):
            add("Support", "info", "Roam < 14 min", _pct(mv["roamRate"]))
    if role == "BOTTOM" and st.get("dmgShare") and st["dmgShare"] >= 0.3:
        add("Style", "good", "Part des dégâts", _pct(st["dmgShare"]))
    return out


def botlane_signals(b: dict) -> list:
    out = []
    if not b or b["duo"]["g"] == 0:
        return out
    duo, a = b["duo"], b["adcSolo"]
    if a["g"] >= 5 and duo["g"] >= 3 and abs(duo["wr"] - a["wr"]) >= 0.1:
        out.append({"tone": "good" if duo["wr"] > a["wr"] else "bad", "label": "WR duo vs ADC sans support",
                    "value": f"{_pct(duo['wr'])} / {_pct(a['wr'])}"})
    if b.get("botGd15") is not None:
        out.append({"tone": "good" if b["botGd15"] > 0 else "bad", "label": "GD bot @15 en duo", "value": _signed(b["botGd15"])})
    return out
