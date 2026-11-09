"""Riot API client.

- Rate limiting follows the limits Riot sends back (X-App-Rate-Limit /
  X-Method-Rate-Limit), so a development key (20/1s, 100/2min) and a production
  key both work without tuning.
- Match and timeline payloads never change once a game is over, so they are
  cached on disk (gzip) forever. Everything else is fetched fresh.
- The key is read from the RIOT_API_KEY env var or key.txt (gitignored).
"""
from __future__ import annotations

import gzip
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"

PLATFORMS = {
    "euw": "euw1", "eune": "eun1", "na": "na1", "kr": "kr", "br": "br1",
    "lan": "la1", "las": "la2", "oce": "oc1", "tr": "tr1", "ru": "ru",
    "jp": "jp1", "ph": "ph2", "sg": "sg2", "th": "th2", "tw": "tw2",
    "vn": "vn2", "me": "me1",
}
REGIONAL = {
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea",
    "kr": "asia", "jp1": "asia",
}


class RiotError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        self.status = status
        self.url = url
        msg = {
            401: "clé API absente ou invalide",
            403: "clé API refusée ou expirée (les clés de dev expirent toutes les 24h)",
            404: "introuvable",
        }.get(status, body[:160])
        super().__init__(f"HTTP {status} — {msg}")


def load_key() -> str:
    env = os.environ.get("RIOT_API_KEY")
    if env and env.strip():
        return env.strip()
    fp = ROOT / "key.txt"
    if fp.exists():
        k = fp.read_text(encoding="utf-8").strip()
        if k:
            return k
    raise RuntimeError("Pas de clé Riot : mets-la dans key.txt ou dans la variable RIOT_API_KEY.")


class _Window:
    """Sliding window limiter for one 'N requests per S seconds' rule."""

    def __init__(self, limit: int, seconds: int):
        self.limit = limit
        self.seconds = seconds
        self.stamps: deque[float] = deque()

    def wait_time(self, now: float) -> float:
        while self.stamps and now - self.stamps[0] >= self.seconds:
            self.stamps.popleft()
        if len(self.stamps) < self.limit:
            return 0.0
        return self.seconds - (now - self.stamps[0]) + 0.05

    def sync(self, server_count: int, now: float):
        # Server saw more requests than we did (another process, earlier run):
        # pad so we don't burst into a 429.
        while len(self.stamps) < min(server_count, self.limit):
            self.stamps.append(now)


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        # conservative defaults = development key, replaced by headers
        self.windows = {(20, 1): _Window(20, 1), (100, 120): _Window(100, 120)}
        self.blocked_until = 0.0

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                wait = max([w.wait_time(now) for w in self.windows.values()] + [self.blocked_until - now])
                if wait <= 0:
                    for w in self.windows.values():
                        w.stamps.append(now)
                    return
            time.sleep(min(wait, 2.0))

    def update(self, headers):
        spec = headers.get("X-App-Rate-Limit")
        counts = headers.get("X-App-Rate-Limit-Count", "")
        if not spec:
            return
        with self.lock:
            now = time.monotonic()
            rules = []
            for part in spec.split(","):
                n, s = part.split(":")
                rules.append((int(n), int(s)))
            for r in rules:
                if r not in self.windows:
                    self.windows[r] = _Window(*r)
            for r in list(self.windows):
                if r not in rules:
                    del self.windows[r]
            for part in counts.split(","):
                if ":" in part:
                    c, s = part.split(":")
                    for (n, sec), w in self.windows.items():
                        if sec == int(s):
                            w.sync(int(c), now)

    def block(self, seconds: float):
        with self.lock:
            self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)

    def per_second(self) -> float:
        """Sustained throughput the current limits allow."""
        return min(n / s for (n, s) in self.windows) if self.windows else 1.0


class RiotClient:
    def __init__(self, region: str = "euw", key: Optional[str] = None):
        region = region.lower().strip()
        self.platform = PLATFORMS.get(region, region)
        self.regional = REGIONAL.get(self.platform)
        if not self.regional:
            raise ValueError(f"Région inconnue : {region}")
        # account-v1 is global; it only accepts americas / asia / europe
        self.account_host = "asia" if self.regional == "sea" else self.regional
        self.key = key or load_key()
        self.limiter = RateLimiter()
        self.local = threading.local()
        self.requests_made = 0
        self.cache_hits = 0
        for sub in ("matches", "timelines", "accounts"):
            (CACHE / sub).mkdir(parents=True, exist_ok=True)

    def _session(self) -> requests.Session:
        s = getattr(self.local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"X-Riot-Token": self.key, "User-Agent": "scout-lol/1.0"})
            self.local.s = s
        return s

    def get(self, host: str, path: str, params: Optional[dict] = None, allow_404: bool = False) -> Any:
        url = f"https://{host}.api.riotgames.com{path}"
        for attempt in range(8):
            self.limiter.acquire()
            try:
                resp = self._session().get(url, params=params, timeout=25)
            except requests.RequestException:
                time.sleep(1.5 * (attempt + 1))
                continue
            self.requests_made += 1
            self.limiter.update(resp.headers)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404 and allow_404:
                return None
            if resp.status_code == 429:
                self.limiter.block(int(resp.headers.get("Retry-After", "5")) + 0.5)
                continue
            if resp.status_code in (500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RiotError(resp.status_code, url, resp.text)
        raise RiotError(429, url, "trop de tentatives")

    # ---- account / profile --------------------------------------------
    def account(self, name: str, tag: str) -> dict:
        key = f"{name}#{tag}".lower()
        fp = CACHE / "accounts" / "by_riot_id.json"
        try:
            known = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            known = {}
        hit = known.get(key)
        if hit and time.time() - hit.get("_t", 0) < 86400:
            return hit
        data = self.get(self.account_host, f"/riot/account/v1/accounts/by-riot-id/{quote(name)}/{quote(tag)}")
        data["_t"] = time.time()
        known[key] = data
        fp.write_text(json.dumps(known), encoding="utf-8")
        return data

    def account_by_puuid(self, puuid: str) -> Optional[dict]:
        return self.get(self.account_host, f"/riot/account/v1/accounts/by-puuid/{puuid}", allow_404=True)

    def summoner(self, puuid: str) -> Optional[dict]:
        return self.get(self.platform, f"/lol/summoner/v4/summoners/by-puuid/{puuid}", allow_404=True)

    def leagues(self, puuid: str) -> list:
        return self.get(self.platform, f"/lol/league/v4/entries/by-puuid/{puuid}", allow_404=True) or []

    def masteries(self, puuid: str) -> list:
        return self.get(self.platform, f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}", allow_404=True) or []

    def challenges(self, puuid: str) -> Optional[dict]:
        return self.get(self.platform, f"/lol/challenges/v1/player-data/{puuid}", allow_404=True)

    def live_game(self, puuid: str) -> Optional[dict]:
        return self.get(self.platform, f"/lol/spectator/v5/active-games/by-summoner/{puuid}", allow_404=True)

    def clash(self, puuid: str) -> list:
        try:
            return self.get(self.platform, f"/lol/clash/v1/players/by-puuid/{puuid}", allow_404=True) or []
        except RiotError:
            return []

    # ---- matches --------------------------------------------------------
    def match_ids(self, puuid: str, start_time: Optional[int] = None, type_: Optional[str] = "ranked",
                  queue: Optional[int] = None, limit: int = 1000) -> list[str]:
        ids: list[str] = []
        start = 0
        while len(ids) < limit:
            count = min(100, limit - len(ids))
            params: dict[str, Any] = {"start": start, "count": count}
            if start_time:
                params["startTime"] = int(start_time)
            if type_:
                params["type"] = type_
            if queue:
                params["queue"] = queue
            page = self.get(self.regional, f"/lol/match/v5/matches/by-puuid/{puuid}/ids", params) or []
            ids.extend(page)
            if len(page) < count:
                break
            start += count
        return ids

    def _cached(self, kind: str, match_id: str, path: str) -> Optional[dict]:
        fp = CACHE / kind / f"{match_id}.json.gz"
        if fp.exists():
            try:
                with gzip.open(fp, "rt", encoding="utf-8") as f:
                    self.cache_hits += 1
                    return json.load(f)
            except Exception:
                pass
        data = self.get(self.regional, path, allow_404=True)
        if data is not None:
            tmp = fp.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            tmp.replace(fp)
        return data

    def is_cached(self, kind: str, match_id: str) -> bool:
        return (CACHE / kind / f"{match_id}.json.gz").exists()

    def match(self, match_id: str) -> Optional[dict]:
        return self._cached("matches", match_id, f"/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id: str) -> Optional[dict]:
        return self._cached("timelines", match_id, f"/lol/match/v5/matches/{match_id}/timeline")
