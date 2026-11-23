"""Run a full scouting job and produce the report JSON the UI renders."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import insights, smurf, team
from .collect import ROLES, Progress, collect, collect_extra, resolve_account
from .stats import wr_block
from .player import analyze
from .riot import RiotClient
from .static import get_static

DATA = Path(__file__).resolve().parent.parent / "data"
REPORTS = DATA / "reports"


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.UNICODE).strip().replace(" ", "-")
    return s[:60] or "equipe"


def run(params: dict, progress: Progress) -> dict:
    t0 = time.time()
    static = get_static()
    client = RiotClient(region=params.get("region", "euw"))
    client.force_refresh = bool(params.get("fullRefresh"))
    if client.force_refresh:
        progress.log("Rafraîchissement complet : toutes les games sont retéléchargées (cache ignoré).")
    roster = {r: params["players"].get(r, "") for r in ROLES}
    days = int(params.get("days", 90))
    max_games = int(params.get("maxGames", 150))
    timelines = bool(params.get("timelines", True))
    team_name = (params.get("team") or "Équipe adverse").strip()

    # checked first, so a typo in a smurf's Riot ID fails before the long download
    manual = resolve_manual_smurfs(client, roster, params.get("manualSmurfs"), progress)
    raw = collect(client, static, roster, days, max_games, timelines, progress, params.get("puuids"))
    # keep the current Riot IDs, so a renamed player shows (and refreshes) under the new name
    roster = {r: f"{p['name']}#{p['tag']}" if r in raw["players"] else roster[r]
              for r, p in ((r, raw["players"].get(r, {})) for r in ROLES)}
    now_ms = int(time.time() * 1000)

    progress.log("Analyse joueur par joueur…")
    analysed = []
    for role in ROLES:
        if role in raw["players"]:
            analysed.append(analyze(raw["players"][role], static, role, now_ms))

    for p in analysed:
        p["signals"] = insights.player_signals(p)

    progress.log("Botlane, premades et games en stack…")
    bot = team.botlane(raw["players"], static)
    prem = team.premades(raw["players"], raw["summaries"])
    stack = team.stack_games(raw["players"], raw["summaries"], static)

    sm = {"enabled": False}
    depth = params.get("smurf", "normal")
    if depth and depth != "off":
        try:
            sm = smurf.detect(client, raw, prem, depth, progress)
        except Exception as e:  # never lose the whole report over this part
            progress.log(f"Détection de smurfs interrompue : {e}")
            sm = {"enabled": True, "error": str(e), "players": {}}

    smurf_players = analyse_smurfs(client, static, raw, sm, manual, max_games, timelines, now_ms, progress)

    prem.pop("_outsiders", None)
    prem.pop("_roster_role", None)

    report = {
        "version": 2,
        "team": team_name,
        "region": params.get("region", "euw"),
        "generated": now_ms,
        "params": {"days": days, "maxGames": max_games, "timelines": timelines, "smurf": depth,
                   "manualSmurfs": manual_params(manual)},
        "roster": {r: roster[r] for r in ROLES if roster[r]},
        "players": analysed,
        "smurfPlayers": smurf_players,
        "teamBans": team.team_bans(analysed + smurf_players),
        "botlane": bot,
        "botlaneSignals": insights.botlane_signals(bot),
        "premades": prem,
        "stack": stack,
        "smurf": sm,
        "static": {
            "version": static.version,
            "champs": {cid: [c["key"], c["name"], c["classes"]] for cid, c in static.champs.items()},
            "items": {iid: it["name"] for iid, it in static.items.items()},
            "runes": {rid: [r["name"], r["icon"]] for rid, r in static.runes.items()},
            "spells": {sid: [s["name"], s["key"]] for sid, s in static.spells.items()},
        },
        "stats": {"requests": client.requests_made, "cacheHits": client.cache_hits,
                  "staleRefetched": client.stale_refetched,
                  "seconds": round(time.time() - t0), "games": len(raw["summaries"])},
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    # A refresh rewrites the same file so links and face-à-face picks keep working.
    fname = params.get("replace") if _report_path(params.get("replace") or "") else None
    fname = fname or f"{time.strftime('%Y%m%d-%H%M')}-{slugify(team_name)}.json"
    tmp = REPORTS / (fname + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(REPORTS / fname)
    report["file"] = fname
    progress.log(f"Terminé en {report['stats']['seconds']} s ({client.requests_made} requêtes, {client.cache_hits} lues en cache).")
    return report


SMURF_THRESHOLD = 80


ROLE_FR = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}


def manual_smurf_entries(raw) -> dict[str, list[dict]]:
    """Smurfs added by hand, as sent by the UI or saved in a report:
    role -> list of "Name#TAG" or {"id": "Name#TAG", "puuid": ...}."""
    out: dict[str, list[dict]] = {}
    for role, items in (raw or {}).items():
        if role not in ROLES:
            continue
        if isinstance(items, (str, dict)):
            items = [items]
        for it in items or []:
            e = {"id": it} if isinstance(it, str) else {"id": str(it.get("id") or ""), "puuid": it.get("puuid")}
            if e["id"].strip():
                out.setdefault(role, []).append(e)
    return out


def resolve_manual_smurfs(client, roster: dict, raw, progress: Progress) -> dict[str, list[dict]]:
    """role -> [{puuid, name, tag}] for the smurfs added by hand. Raises ValueError
    (shown to the user) for a malformed or unknown Riot ID."""
    out: dict[str, list[dict]] = {}
    seen = set()
    for role, items in manual_smurf_entries(raw).items():
        if not (roster.get(role) or "").strip():
            raise ValueError(f"Smurf « {items[0]['id'].strip()} » : il n'y a pas de joueur {ROLE_FR[role]} dans l'équipe.")
        for e in items:
            try:
                acc = resolve_account(client, e["id"], progress, e.get("puuid"))
            except ValueError as err:
                raise ValueError(f"Smurf {ROLE_FR[role]} : {err}") from None
            if acc["puuid"] not in seen:
                seen.add(acc["puuid"])
                out.setdefault(role, []).append(acc)
    return out


def manual_params(manual: dict) -> dict:
    """What the report keeps of the manual smurfs, to show and refresh them."""
    return {role: [{"id": f"{a['name']}#{a['tag']}", "puuid": a["puuid"]} for a in accs]
            for role, accs in manual.items()}


def analyse_smurfs(client, static, raw, sm, manual, max_games, timelines, now_ms, progress) -> list:
    """Accounts scored >= 80, and the ones added by hand, get the same full
    analysis as a roster player."""
    picks: dict[str, dict] = {}  # puuid -> account to analyse
    if sm.get("enabled"):
        for role, res in (sm.get("players") or {}).items():
            for sus in res.get("suspects", []):
                if sus["score"] >= SMURF_THRESHOLD:
                    name, _, tag = sus["name"].rpartition("#")
                    picks.setdefault(sus["puuid"], {"role": role, "puuid": sus["puuid"], "name": name.strip(),
                                                    "tag": tag, "score": sus["score"]})
    for role, accs in (manual or {}).items():
        for acc in accs:  # the user's word wins over the detection
            picks[acc["puuid"]] = {"role": role, **acc, "score": None, "manual": True}
    roster_puuids = {p["puuid"] for p in raw["players"].values()}

    out = []
    start_time = raw["start_time"]
    for pick in picks.values():
        role = pick["role"]
        main = raw["players"].get(role)
        label = f"{pick['name']}#{pick['tag']}"
        if main is None or pick["puuid"] in roster_puuids:
            if pick.get("manual"):
                progress.log(f"{label} ignoré : c'est déjà un joueur de l'équipe.")
            continue
        why = "ajouté manuellement comme smurf" if pick.get("manual") else "compte secondaire probable"
        progress.log(f"Analyse complète de {label} ({why} de {main['name']})…")
        extra = {"role": role, "puuid": pick["puuid"], "name": pick["name"], "tag": pick["tag"]}
        try:
            collect_extra(client, static, extra, start_time, max_games, timelines, progress, raw["summaries"])
        except Exception as e:
            progress.log(f"  impossible : {e}")
            continue
        if not extra["records"]:
            progress.log(f"  aucune game classée sur la période pour {label}.")
            continue
        a = analyze(extra, static, role, now_ms)
        a["signals"] = insights.player_signals(a)
        a["smurfOf"] = {"role": role, "name": f"{main['name']}#{main['tag']}", "score": pick["score"],
                        "manual": bool(pick.get("manual"))}
        a["combined"] = combined_pool(main["records"], extra["records"])
        out.append(a)
    out.sort(key=lambda a: ROLES.index(a["role"]))
    return out


def combined_pool(main_recs: list, smurf_recs: list) -> list:
    champs = {}
    for who, recs in (("main", main_recs), ("smurf", smurf_recs)):
        for r in recs:
            c = champs.setdefault(r["champ"], {"main": [], "smurf": []})
            c[who].append(r)
    rows = []
    for cid, d in champs.items():
        both = d["main"] + d["smurf"]
        rows.append({"champ": cid, "gMain": len(d["main"]), "gSmurf": len(d["smurf"]),
                     "wrMain": wr_block(d["main"])["wr"], "wrSmurf": wr_block(d["smurf"])["wr"],
                     "g": len(both), "wr": wr_block(both)["wr"]})
    rows.sort(key=lambda x: -x["g"])
    return rows[:15]


def list_reports() -> list:
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = []
    for fp in sorted(REPORTS.glob("*.json"), reverse=True):
        try:
            with fp.open(encoding="utf-8") as f:
                head = json.load(f)
            out.append({
                "file": fp.name, "team": head.get("team"), "region": head.get("region"),
                "generated": head.get("generated"),
                "players": [f"{p['name']}#{p['tag']}" for p in head.get("players", [])],
            })
        except Exception:
            continue
    return out


def _report_path(name: str) -> Path | None:
    """Resolve a report file name, refusing anything outside data/reports."""
    fp = (REPORTS / name).resolve()
    if fp.parent != REPORTS.resolve() or fp.suffix != ".json" or not fp.exists():
        return None
    return fp


def refresh_params(name: str, full: bool = False) -> dict | None:
    """Rebuild the analysis parameters of a saved report, to run it again."""
    fp = _report_path(name)
    if fp is None:
        return None
    data = json.loads(fp.read_text(encoding="utf-8"))
    prm = data.get("params") or {}
    puuids = {p["role"]: p["puuid"] for p in data.get("players", []) if p.get("role") and p.get("puuid")}
    return {
        "players": data.get("roster") or {}, "puuids": puuids, "team": data.get("team"), "region": data.get("region", "euw"),
        "days": prm.get("days", 90), "maxGames": prm.get("maxGames", 150),
        "timelines": prm.get("timelines", True), "smurf": prm.get("smurf", "normal"),
        "manualSmurfs": prm.get("manualSmurfs") or {},
        "replace": name,
        "fullRefresh": bool(full),
    }


def rename_report(name: str, team: str) -> bool:
    """Change the team name shown in the report (the file name stays, so links keep working)."""
    fp = _report_path(name)
    team = (team or "").strip()
    if fp is None or not team:
        return False
    data = json.loads(fp.read_text(encoding="utf-8"))
    data["team"] = team[:80]
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(fp)
    return True


def delete_report(name: str) -> bool:
    fp = _report_path(name)
    if fp is None:
        return False
    fp.unlink()
    return True


def load_report(name: str) -> dict | None:
    fp = _report_path(name)
    if fp is None:
        return None
    data = json.loads(fp.read_text(encoding="utf-8"))
    data["file"] = name
    return data
