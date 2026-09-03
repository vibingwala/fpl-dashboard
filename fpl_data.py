"""
Shared FPL data fetching, player valuation, and budget/free-transfer estimation.
"""

import requests
import streamlit as st

FPL_BASE = "https://fantasy.premierleague.com/api"
POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
MAX_SAVED_FTS = 5  # 2025/26 rule: free transfers can bank up to 5


@st.cache_data(ttl=3600)
def get_bootstrap():
    r = requests.get(f"{FPL_BASE}/bootstrap-static/", timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600)
def get_fixtures():
    r = requests.get(f"{FPL_BASE}/fixtures/", timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=600)
def get_entry_history(entry_id):
    r = requests.get(f"{FPL_BASE}/entry/{entry_id}/history/", timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=600)
def get_picks(entry_id, event_id):
    r = requests.get(f"{FPL_BASE}/entry/{entry_id}/event/{event_id}/picks/", timeout=10)
    r.raise_for_status()
    return r.json()


def get_current_event(bootstrap):
    for event in bootstrap["events"]:
        if event["is_current"]:
            return event["id"]
    for event in bootstrap["events"]:
        if event["is_next"]:
            return max(event["id"] - 1, 1)
    return 1


def get_next_deadline(bootstrap):
    """Returns (next_event_id, deadline_iso_string) or (None, None) if season's done."""
    for event in bootstrap["events"]:
        if event["is_next"]:
            return event["id"], event["deadline_time"]
    return None, None


def estimate_free_transfers(history):
    """
    Best-effort reconstruction of free transfers available, since FPL's public
    API doesn't expose this directly (only the authenticated my-team endpoint
    does). Assumes standard rules: +1 FT per gameweek, capped at 5 saved,
    wildcard/free-hit weeks are exempt from the transfer-cost calc entirely.
    This is an ESTIMATE — verify against the app and correct via the sidebar
    override if it drifts.
    """
    ft = 1
    for gw in history["current"]:
        chip = gw.get("active_chip")
        if chip in ("wildcard", "freehit"):
            # chip week: doesn't consume or grant FT progress
            continue
        transfers_used = gw["event_transfers"]
        ft = max(ft - transfers_used, 0)
        ft = min(ft + 1, MAX_SAVED_FTS)
    return ft


def get_chips_used(history):
    """List of chips already played this season, in order."""
    return [gw["active_chip"] for gw in history["current"] if gw.get("active_chip")]


def build_player_lookup(bootstrap):
    teams = {t["id"]: t for t in bootstrap["teams"]}
    players = {}
    for p in bootstrap["elements"]:
        team = teams.get(p["team"], {})
        players[p["id"]] = {
            "id": p["id"],
            "name": p["web_name"],
            "position": POSITION_NAMES.get(p["element_type"], "?"),
            "element_type": p["element_type"],
            "team_id": p["team"],
            "team_name": team.get("short_name", ""),
            "price": p["now_cost"] / 10,
            "form": float(p.get("form") or 0),
            "selected_by_percent": float(p.get("selected_by_percent") or 0),
            "status": p.get("status", "a"),
            "news": p.get("news", ""),
            "total_points": p.get("total_points", 0),
            "minutes": p.get("minutes", 0),
        }
    return players


def minutes_probability(player):
    status_map = {"a": 1.0, "d": 0.5, "i": 0.0, "s": 0.0, "u": 0.0, "n": 0.75}
    return status_map.get(player["status"], 0.75)


def fixture_ease_lookahead(team_id, fixtures, from_event, n=4):
    """Average FDR-based ease (lower FDR = easier = higher ease score) over
    the next n fixtures for a team, starting from from_event."""
    relevant = [
        f for f in fixtures
        if f["event"] and f["event"] >= from_event
        and (f["team_h"] == team_id or f["team_a"] == team_id)
    ]
    relevant = sorted(relevant, key=lambda f: f["event"])[:n]
    if not relevant:
        return 0.6  # neutral default
    eases = []
    for f in relevant:
        fdr = f["team_h_difficulty"] if f["team_h"] == team_id else f["team_a_difficulty"]
        eases.append((6 - fdr) / 5)  # FDR 1-5 -> ease 1.0-0.2
    return sum(eases) / len(eases)


def expected_value(player, fixtures, from_event, n=4):
    """EV = form x fixture ease x minutes probability, projected over n games."""
    ease = fixture_ease_lookahead(player["team_id"], fixtures, from_event, n)
    prob = minutes_probability(player)
    return round(player["form"] * ease * prob * n / 4, 2)
