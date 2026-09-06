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
            "team_short": team.get("short_name", "?"),  # alias for ui_components.py's expected key
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


def build_team_strength(bootstrap):
    """Per-team attack/defence strength ratings (FPL's own model, roughly
    1000-1400 scale), split home/away. Used to judge fixtures by actual
    opponent quality rather than just the single 1-5 FDR digit."""
    return {
        t["id"]: {
            "attack_home": t["strength_attack_home"],
            "attack_away": t["strength_attack_away"],
            "defence_home": t["strength_defence_home"],
            "defence_away": t["strength_defence_away"],
        }
        for t in bootstrap["teams"]
    }


def _normalize_strength(value, all_values):
    lo, hi = min(all_values), max(all_values)
    if hi == lo:
        return 0.5
    return (value - lo) / (hi - lo)


def fixture_ease_lookahead(team_id, fixtures, from_event, n=4, position=None, team_strength=None):
    """Average ease over the next n fixtures for a team, starting from
    from_event. When team_strength is provided, blends FPL's blunt 1-5 FDR
    with the actual opponent's attack/defence rating relevant to this
    player's position: defenders/keepers care about the opponent's attack
    strength (clean sheet odds), attackers care about the opponent's
    defence strength (goal-scoring odds)."""
    relevant = [
        f for f in fixtures
        if f["event"] and f["event"] >= from_event
        and (f["team_h"] == team_id or f["team_a"] == team_id)
    ]
    relevant = sorted(relevant, key=lambda f: f["event"])[:n]
    if not relevant:
        return 0.6

    eases = []
    for f in relevant:
        is_home = f["team_h"] == team_id
        fdr = f["team_h_difficulty"] if is_home else f["team_a_difficulty"]
        fdr_ease = (6 - fdr) / 5

        if team_strength:
            opponent_id = f["team_a"] if is_home else f["team_h"]
            opp = team_strength.get(opponent_id)
            if opp:
                # opponent's relevant stat, at the venue they're actually playing
                if position in ("GKP", "DEF"):
                    opp_value = opp["attack_away"] if is_home else opp["attack_home"]
                else:
                    opp_value = opp["defence_away"] if is_home else opp["defence_home"]
                all_vals = [
                    (v["attack_away"] if position in ("GKP", "DEF") else v["defence_away"])
                    for v in team_strength.values()
                ]
                opp_strength_ease = 1 - _normalize_strength(opp_value, all_vals)
                eases.append(0.5 * fdr_ease + 0.5 * opp_strength_ease)
                continue

        eases.append(fdr_ease)

    return sum(eases) / len(eases)


def expected_value(player, fixtures, from_event, n=4, team_strength=None):
    """EV = form x fixture ease x minutes probability, projected over n games.
    Fixture ease accounts for actual opponent strength when team_strength
    is supplied, not just the blunt FDR digit."""
    ease = fixture_ease_lookahead(
        player["team_id"], fixtures, from_event, n,
        position=player["position"], team_strength=team_strength,
    )
    prob = minutes_probability(player)
    return round(player["form"] * ease * prob * n / 4, 2)
