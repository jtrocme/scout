"""Summoner's Rift geometry: which zone a coordinate belongs to.

Blue base is bottom-left (0,0), red base top-right. Top lane runs up the left
edge then along the top edge, bot lane along the bottom edge then up the right
edge, mid lane is the main diagonal, the river is the anti-diagonal.

Zones are expressed relative to the player's team ("jungle alliée/ennemie").
"""
from __future__ import annotations

S = 14870.0
DRAGON = (9866, 4414)
BARON = (5007, 10471)

LANE_TOP = "Lane Top"
LANE_MID = "Lane Mid"
LANE_BOT = "Lane Bot"
RIVER_TOP = "Rivière top"
RIVER_BOT = "Rivière bot"
BASE = "Base"
ENEMY_BASE = "Base ennemie"
JG_ALLY_TOP = "Jungle alliée côté top"
JG_ALLY_BOT = "Jungle alliée côté bot"
JG_ENEMY_TOP = "Jungle ennemie côté top"
JG_ENEMY_BOT = "Jungle ennemie côté bot"

LANES = (LANE_TOP, LANE_MID, LANE_BOT)
RIVERS = (RIVER_TOP, RIVER_BOT)
ENEMY_JUNGLE = (JG_ENEMY_TOP, JG_ENEMY_BOT)
ALLY_JUNGLE = (JG_ALLY_TOP, JG_ALLY_BOT)


def zone(x: float, y: float, team_id: int) -> str:
    s = x + y
    if s < 5600:
        return BASE if team_id == 100 else ENEMY_BASE
    if s > 2 * S - 5600:
        return BASE if team_id == 200 else ENEMY_BASE
    if x < 2100 or y > S - 2100:
        return LANE_TOP
    if y < 2100 or x > S - 2100:
        return LANE_BOT
    if abs(x - y) < 1500:
        return LANE_MID
    top_side = y > x
    if abs(s - S) < 1400:
        return RIVER_TOP if top_side else RIVER_BOT
    blue_half = s < S
    ally = blue_half if team_id == 100 else not blue_half
    if ally:
        return JG_ALLY_TOP if top_side else JG_ALLY_BOT
    return JG_ENEMY_TOP if top_side else JG_ENEMY_BOT


def side(x: float, y: float) -> str:
    """'top' or 'bot' half of the map (split by the mid diagonal)."""
    return "top" if y > x else "bot"


def near(p, center, radius=1700) -> bool:
    return (p[0] - center[0]) ** 2 + (p[1] - center[1]) ** 2 <= radius * radius


def at_pit(x, y) -> str | None:
    if near((x, y), DRAGON):
        return "Drake"
    if near((x, y), BARON):
        return "Nashor"
    return None


def mirror(x: float, y: float, team_id: int):
    """Put red-side games on the blue side while keeping lanes in place
    (reflection across the river)."""
    if team_id == 200:
        return S - y, S - x
    return x, y
