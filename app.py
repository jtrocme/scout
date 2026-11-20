"""Local web app: enter five Riot IDs, get a scouting report.

    python app.py            -> http://127.0.0.1:5057
"""
from __future__ import annotations

import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from scoutlib import counters, report
from scoutlib.collect import Progress
from scoutlib.riot import RiotClient, RiotError, load_key

WEB = Path(__file__).resolve().parent / "web"
app = Flask(__name__, static_folder=None)
JOBS: dict[str, dict] = {}


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:name>")
def assets(name):
    resp = send_from_directory(WEB, name)
    resp.headers["Cache-Control"] = "no-cache"  # always pick up UI updates
    return resp


@app.get("/api/status")
def status():
    try:
        load_key()
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)})
    try:
        c = RiotClient(request.args.get("region", "euw"))
        c.get(c.platform, "/lol/status/v4/platform-data")
        dev = any(n == 100 and s == 120 for (n, s) in c.limiter.windows)
        return jsonify({"ok": True, "dev": dev, "perSecond": c.limiter.per_second()})
    except RiotError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Riot injoignable : {e}"})


@app.post("/api/analyze")
def analyze():
    params = request.get_json(force=True)
    params.pop("replace", None)  # only the refresh route may overwrite a report
    params.pop("puuids", None)
    params.pop("fullRefresh", None)
    players = params.get("players") or {}
    if not any(v.strip() for v in players.values()):
        return jsonify({"error": "Ajoute au moins un joueur."}), 400
    return jsonify({"job": start_job(params)})


@app.post("/api/reports/<name>/refresh")
def refresh_report(name):
    """Run a saved report again with the same roster and settings, overwriting it."""
    body = request.get_json(silent=True) or {}
    params = report.refresh_params(name, full=bool(body.get("full")))
    if params is None:
        abort(404)
    if not any((v or "").strip() for v in params["players"].values()):
        return jsonify({"error": "Ce rapport ne contient aucun joueur à relancer."}), 400
    return jsonify({"job": start_job(params)})


def start_job(params: dict) -> str:
    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "status": "running", "progress": {}, "started": time.time(), "report": None, "error": None}
    JOBS[job_id] = job

    def cb(state):
        job["progress"] = state

    def work():
        try:
            rep = report.run(params, Progress(cb))
            job["report"] = rep["file"]
            job["status"] = "done"
        except Exception as e:  # shown to the user as-is
            job["error"] = str(e)
            job["status"] = "error"

    threading.Thread(target=work, daemon=True).start()
    return job_id


@app.get("/api/jobs/<job_id>")
def job(job_id):
    j = JOBS.get(job_id)
    if not j:
        abort(404)
    return jsonify({**j, "elapsed": round(time.time() - j["started"])})


@app.get("/api/counters")
def counters_route():
    """Lane matchups of one champion (u.gg), for the draft helper."""
    try:
        champ = int(request.args.get("champ", ""))
    except ValueError:
        return jsonify({"error": "Champion invalide."}), 400
    role = request.args.get("role", "")
    if role not in counters.ROLE_ID:
        return jsonify({"error": "Rôle invalide."}), 400
    try:
        return jsonify(counters.matchups(champ, role, request.args.get("tier", "emerald_plus")))
    except Exception as e:
        return jsonify({"error": f"Counters indisponibles : {e}"}), 502


@app.get("/api/reports")
def reports():
    return jsonify(report.list_reports())


@app.get("/api/reports/<name>")
def one_report(name):
    data = report.load_report(name)
    if data is None:
        abort(404)
    return jsonify(data)


@app.patch("/api/reports/<name>")
def rename_report(name):
    team = (request.get_json(force=True) or {}).get("team", "")
    if not team.strip():
        return jsonify({"error": "Nom vide."}), 400
    if not report.rename_report(name, team):
        abort(404)
    return jsonify({"ok": True})


@app.delete("/api/reports/<name>")
def delete_report(name):
    if not report.delete_report(name):
        abort(404)
    return jsonify({"ok": True})


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    url = "http://127.0.0.1:5057"
    if _port_in_use(5057):
        # Windows lets a second server bind the same port; the old one would
        # keep answering with outdated code.
        raise SystemExit("Scout tourne déjà sur le port 5057 : ferme l'ancienne fenêtre (Ctrl+C) puis relance.")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Scout tourne sur {url}  (Ctrl+C pour arrêter)")
    app.run(host="127.0.0.1", port=5057, debug=False, threaded=True)
