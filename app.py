"""
FPL Manager Dashboard - Squad View
Run with: streamlit run app.py
"""

import streamlit as st
import requests

from settings import settings_sidebar, get_settings
from ui_components import build_player_lookup, render_pitch, THEME_CSS

st.set_page_config(page_title="FPL Squad View", page_icon="⚽", layout="wide")

FPL_BASE = "https://fantasy.premierleague.com/api"


# ---------- Data fetching ----------

@st.cache_data(ttl=3600)
def get_bootstrap():
    r = requests.get(f"{FPL_BASE}/bootstrap-static/", timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=600)
def get_current_event(bootstrap):
    for event in bootstrap["events"]:
        if event["is_current"]:
            return event["id"]
    for event in bootstrap["events"]:
        if event["is_next"]:
            return event["id"] - 1
    return 1


@st.cache_data(ttl=600)
def get_next_event(bootstrap):
    for event in bootstrap["events"]:
        if event["is_next"]:
            return event["id"]
    return None


@st.cache_data(ttl=600)
def get_picks(entry_id, event_id):
    r = requests.get(f"{FPL_BASE}/entry/{entry_id}/event/{event_id}/picks/", timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600)
def get_entry_info(entry_id):
    r = requests.get(f"{FPL_BASE}/entry/{entry_id}/", timeout=10)
    r.raise_for_status()
    return r.json()


def main():
    st.title("My squad")

    settings_sidebar()
    cfg = get_settings()
    entry_id = cfg["team_id"]

    if not entry_id.strip().isdigit():
        st.warning("Enter a numeric team ID in the sidebar.")
        return

    entry_id = int(entry_id)

    try:
        bootstrap = get_bootstrap()
        entry_info = get_entry_info(entry_id)
        current_event = get_current_event(bootstrap)
        next_event = get_next_event(bootstrap)
    except requests.RequestException as e:
        st.error(f"Couldn't reach the FPL API: {e}")
        return

    view_options = [f"Current (GW{current_event}, locked)"]
    if next_event:
        view_options.append(f"Upcoming (GW{next_event}, still editable)")

    view_choice = st.radio("Viewing", view_options, horizontal=True)
    event_id = next_event if "Upcoming" in view_choice else current_event
    viewing_upcoming = "Upcoming" in view_choice

    if viewing_upcoming and cfg["is_logged_in"] and cfg["live_picks"]:
        picks_data = {
            "picks": cfg["live_picks"],
            "entry_history": {
                "points": 0, "total_points": entry_info.get("summary_overall_points", 0),
                "bank": int(cfg["bank"] * 10), "overall_rank": entry_info.get("summary_overall_rank", 0),
            },
        }
        st.caption(
            "This is your live provisional squad for next gameweek, pulled from "
            "your logged-in FPL account -- reflects transfers you've made but "
            "haven't locked in yet."
        )
    else:
        try:
            picks_data = get_picks(entry_id, event_id)
        except requests.RequestException as e:
            if viewing_upcoming:
                st.warning(
                    "FPL's public API doesn't expose your squad for an upcoming, "
                    "not-yet-locked gameweek -- only finalized ones. " +
                    ("Login is configured but wasn't able to fetch this -- check "
                     "the sidebar for the auth error. " if cfg["auth_error"] else
                     "Add FPL_EMAIL and FPL_PASSWORD to Secrets to see this live. ") +
                    "Showing your current locked squad instead."
                )
                event_id = current_event
                viewing_upcoming = False
                try:
                    picks_data = get_picks(entry_id, event_id)
                except requests.RequestException as e2:
                    st.error(f"Couldn't reach the FPL API: {e2}")
                    return
            else:
                st.error(f"Couldn't reach the FPL API: {e}")
                return

        if viewing_upcoming:
            st.caption(
                "This is your provisional squad for next gameweek -- it reflects "
                "transfers you've made but haven't locked in yet, and can still change."
            )

    players = build_player_lookup(bootstrap)

    team_name = entry_info.get("name", "Your team")
    manager_name = f"{entry_info.get('player_first_name', '')} {entry_info.get('player_last_name', '')}".strip()

    hist = picks_data["entry_history"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Team", team_name)
    col2.metric(f"GW{event_id} points", hist["points"])
    col3.metric("Total points", hist["total_points"])
    col4.metric("Bank", f"£{hist['bank'] / 10:.1f}m")

    st.caption(f"Manager: {manager_name} · Overall rank: {hist['overall_rank']:,}")

    st.markdown(THEME_CSS, unsafe_allow_html=True)

    sections_html, bench_rows = render_pitch(picks_data["picks"], players)
    st.markdown(f'<div class="sheet">{sections_html}</div>', unsafe_allow_html=True)

    st.markdown('<div class="bench-label">Bench</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sheet"><div class="section">{bench_rows}</div></div>', unsafe_allow_html=True)

    with st.expander("Player status flags (injuries/doubts)"):
        squad_ids = {pick["element"] for pick in picks_data["picks"]}
        squad_flagged = [players[pid] for pid in squad_ids if players[pid]["status"] != "a"]
        if squad_flagged:
            for p in squad_flagged:
                st.write(f"**{p['name']}** — {p['news']}")
        else:
            st.write("No flagged players in your squad.")


if __name__ == "__main__":
    main()
