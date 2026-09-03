"""
FPL Manager Dashboard - Squad View
Run with: streamlit run app.py
"""

import streamlit as st
import requests

st.set_page_config(page_title="FPL Squad View", page_icon="⚽", layout="wide")

FPL_BASE = "https://fantasy.premierleague.com/api"
CREST_URL = "https://resources.premierleague.com/premierleague/badges/70/t{code}.png"

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


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
def get_picks(entry_id, event_id):
    r = requests.get(f"{FPL_BASE}/entry/{entry_id}/event/{event_id}/picks/", timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600)
def get_entry_info(entry_id):
    r = requests.get(f"{FPL_BASE}/entry/{entry_id}/", timeout=10)
    r.raise_for_status()
    return r.json()


# Curated colors for real club badges (short_name -> hex), so we don't depend
# on external crest images that often block hotlinking and show as broken
# images instead. Falls back to a deterministic color for any team not listed.
TEAM_COLORS = {
    "ARS": "#EF0107", "AVL": "#95BFE5", "BOU": "#DA291C", "BRE": "#e30613",
    "BHA": "#0057B8", "BUR": "#6C1D45", "CHE": "#034694", "CRY": "#1B458F",
    "EVE": "#003399", "FUL": "#000000", "IPS": "#3A64A3", "LEI": "#003090",
    "LEE": "#FFCD00", "LIV": "#C8102E", "MCI": "#6CABDD", "MUN": "#DA291C",
    "NEW": "#241F20", "NFO": "#DD0000", "SOU": "#D71920", "TOT": "#132257",
    "WHU": "#7A263A", "WOL": "#FDB913", "SUN": "#EB172B", "HUL": "#F18A01",
    "COV": "#78D0F7", "MID": "#FF0000",
}
FALLBACK_PALETTE = ["#534AB7", "#0F6E56", "#993C1D", "#993556", "#185FA5", "#3B6D11"]


def team_color(short_name):
    if short_name in TEAM_COLORS:
        return TEAM_COLORS[short_name]
    # deterministic fallback so the same team always gets the same color
    idx = sum(ord(c) for c in short_name) % len(FALLBACK_PALETTE)
    return FALLBACK_PALETTE[idx]


def readable_text_color(hex_color):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    return "#111111" if brightness > 150 else "#ffffff"


def build_player_lookup(bootstrap):
    teams = {t["id"]: t for t in bootstrap["teams"]}
    players = {}
    for p in bootstrap["elements"]:
        team = teams.get(p["team"], {})
        players[p["id"]] = {
            "name": p["web_name"],
            "position": POSITION_NAMES.get(p["element_type"], "?"),
            "team_short": team.get("short_name", "?"),
            "team_name": team.get("name", ""),
            "points": p.get("event_points", 0),
            "total_points": p.get("total_points", 0),
            "price": p["now_cost"] / 10,
            "form": p.get("form", "0"),
            "news": p.get("news", ""),
            "status": p.get("status", "a"),
        }
    return players


# ---------- Rendering ----------

def player_card_html(player, is_captain=False, is_vice=False, multiplier=1):
    bg = team_color(player["team_short"])
    fg = readable_text_color(bg)

    badge = ""
    if is_captain:
        badge = '<div class="badge captain">C</div>'
    elif is_vice:
        badge = '<div class="badge vice">V</div>'

    flag = ""
    if player["status"] != "a":
        flag = '<div class="flag">!</div>'

    pts = player["points"] * multiplier

    return f"""
    <div class="player-card">
        {badge}
        {flag}
        <div class="crest" style="background:{bg}; color:{fg};">{player['team_short']}</div>
        <div class="pname">{player['name']}</div>
        <div class="pmeta">£{player['price']:.1f}m</div>
        <div class="ppoints">{pts} pts</div>
    </div>
    """


def render_pitch(picks, players):
    starters = [p for p in picks if p["multiplier"] > 0]
    bench = [p for p in picks if p["multiplier"] == 0]

    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for pick in starters:
        player = players[pick["element"]]
        by_pos[player["position"]].append((pick, player))

    rows_html = ""
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        row_cards = ""
        for pick, player in by_pos[pos]:
            row_cards += player_card_html(
                player,
                is_captain=pick["is_captain"],
                is_vice=pick["is_vice_captain"],
                multiplier=pick["multiplier"],
            )
        rows_html += f'<div class="pitch-row">{row_cards}</div>'

    bench_cards = ""
    for pick in bench:
        player = players[pick["element"]]
        bench_cards += player_card_html(player)

    return rows_html, bench_cards


CSS = """
<style>
.pitch {
    background: linear-gradient(180deg, #1a7a3c 0%, #2ba84a 50%, #1a7a3c 100%);
    border-radius: 16px;
    padding: 24px 12px;
    background-image:
        repeating-linear-gradient(0deg, rgba(255,255,255,0.05) 0px, rgba(255,255,255,0.05) 40px,
        transparent 40px, transparent 80px);
}
.pitch-row {
    display: flex;
    justify-content: center;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.player-card {
    position: relative;
    background: rgba(255,255,255,0.95);
    border-radius: 10px;
    padding: 10px 6px 8px;
    width: 96px;
    text-align: center;
    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    overflow: visible;
}
.crest {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    margin: 0 auto 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.3px;
}
.pname {
    font-weight: 700;
    font-size: 12px;
    color: #111;
    white-space: normal;
    line-height: 1.2;
    min-height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.pmeta {
    font-size: 10px;
    color: #555;
}
.ppoints {
    font-size: 13px;
    font-weight: 700;
    color: #1a7a3c;
    margin-top: 2px;
}
.badge {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    font-size: 11px;
    font-weight: 800;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4);
}
.badge.captain { background: #f5a623; }
.badge.vice { background: #7f8fa6; }
.flag {
    position: absolute;
    top: -6px;
    left: -6px;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: #e74c3c;
    color: white;
    font-size: 12px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
}
.bench-strip {
    display: flex;
    gap: 16px;
    justify-content: flex-start;
    overflow-x: auto;
    padding: 16px 4px;
}
</style>
"""


def main():
    st.title("⚽ My FPL squad")

    with st.sidebar:
        st.header("Settings")
        entry_id = st.text_input("Your FPL team ID", value="3486295")
        st.caption("Find this in the URL when viewing your team on the FPL site.")

    if not entry_id.strip().isdigit():
        st.warning("Enter a numeric team ID in the sidebar.")
        return

    entry_id = int(entry_id)

    try:
        bootstrap = get_bootstrap()
        entry_info = get_entry_info(entry_id)
        event_id = get_current_event(bootstrap)
        picks_data = get_picks(entry_id, event_id)
    except requests.RequestException as e:
        st.error(f"Couldn't reach the FPL API: {e}")
        return

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

    st.markdown(CSS, unsafe_allow_html=True)

    rows_html, bench_cards = render_pitch(picks_data["picks"], players)
    st.markdown(f'<div class="pitch">{rows_html}</div>', unsafe_allow_html=True)

    st.subheader("Bench")
    st.markdown(f'<div class="bench-strip">{bench_cards}</div>', unsafe_allow_html=True)

    with st.expander("Player status flags (injuries/doubts)"):
        flagged = [p for p in players.values() if p["status"] != "a" and p["news"]]
        squad_ids = {pick["element"] for pick in picks_data["picks"]}
        squad_flagged = [players[pid] for pid in squad_ids if players[pid]["status"] != "a"]
        if squad_flagged:
            for p in squad_flagged:
                st.write(f"**{p['name']}** — {p['news']}")
        else:
            st.write("No flagged players in your squad.")


if __name__ == "__main__":
    main()
