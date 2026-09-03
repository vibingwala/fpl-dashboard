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


def _flatten(html: str) -> str:
    """Strip leading whitespace from every line. Markdown treats 4+ leading
    spaces as a code block regardless of unsafe_allow_html, which silently
    turns rendered HTML into literal displayed text -- this prevents that."""
    return "\n".join(line.strip() for line in html.strip().split("\n"))


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


# Curated real club colors, shown as a slim accent bar rather than a filled
# badge -- reads as understated club identity, not a cartoon crest.
TEAM_COLORS = {
    "ARS": "#EF0107", "AVL": "#95BFE5", "BOU": "#DA291C", "BRE": "#e30613",
    "BHA": "#0057B8", "BUR": "#6C1D45", "CHE": "#034694", "CRY": "#1B458F",
    "EVE": "#003399", "FUL": "#CCCCCC", "IPS": "#3A64A3", "LEI": "#003090",
    "LEE": "#FFCD00", "LIV": "#C8102E", "MCI": "#6CABDD", "MUN": "#DA291C",
    "NEW": "#8C8C8C", "NFO": "#DD0000", "SOU": "#D71920", "TOT": "#132257",
    "WHU": "#7A263A", "WOL": "#FDB913", "SUN": "#EB172B", "HUL": "#F18A01",
    "COV": "#78D0F7", "MID": "#FF0000",
}
FALLBACK_PALETTE = ["#8B7FD9", "#4FB89A", "#D98A5C", "#C97AA0", "#5C9FD9"]
GOLD = "#C9A24B"


def team_color(short_name):
    if short_name in TEAM_COLORS:
        return TEAM_COLORS[short_name]
    idx = sum(ord(c) for c in short_name) % len(FALLBACK_PALETTE)
    return FALLBACK_PALETTE[idx]


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

def player_row_html(player, is_captain=False, is_vice=False, multiplier=1):
    accent = team_color(player["team_short"])
    tag = ""
    if is_captain:
        tag = '<span class="tag captain">C</span>'
    elif is_vice:
        tag = '<span class="tag vice">V</span>'
    flag = '<span class="flag-dot"></span>' if player["status"] != "a" else ""
    pts = player["points"] * multiplier

    return _flatten(f"""
    <div class="prow" style="border-left-color:{accent};">
        <div class="prow-main">
            <span class="pname">{player['name']}</span>
            {tag}{flag}
            <span class="pteam">{player['team_short']}</span>
        </div>
        <div class="prow-stats">
            <span class="pprice">£{player['price']:.1f}</span>
            <span class="ppoints">{pts}</span>
        </div>
    </div>
    """)


def render_pitch(picks, players):
    starters = [p for p in picks if p["multiplier"] > 0]
    bench = [p for p in picks if p["multiplier"] == 0]

    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for pick in starters:
        player = players[pick["element"]]
        by_pos[player["position"]].append((pick, player))

    section_labels = {"GKP": "Goalkeeper", "DEF": "Defence", "MID": "Midfield", "FWD": "Attack"}
    sections_html = ""
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        rows = "".join(
            player_row_html(player, pick["is_captain"], pick["is_vice_captain"], pick["multiplier"])
            for pick, player in by_pos[pos]
        )
        sections_html += _flatten(f"""
        <div class="section">
            <div class="section-label">{section_labels[pos]}</div>
            {rows}
        </div>
        """)

    bench_rows = "".join(player_row_html(players[p["element"]]) for p in bench)

    return sections_html, bench_rows


THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.sheet {
    background: #121815;
    border-radius: 6px;
    padding: 4px 0 12px;
    border: 1px solid #223028;
}
.section { padding: 10px 16px 4px; }
.section-label {
    font-size: 11px;
    color: #C9A24B;
    font-weight: 600;
    letter-spacing: 0.4px;
    margin: 6px 0 6px;
    border-bottom: 1px solid #223028;
    padding-bottom: 4px;
}
.prow {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 10px;
    margin-bottom: 4px;
    background: #182019;
    border-left: 3px solid #444;
    border-radius: 3px;
}
.prow-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pname {
    color: #EDEDE8;
    font-size: 14px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.pteam {
    color: #7A8580;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    flex-shrink: 0;
}
.tag {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 5px;
    border-radius: 3px;
    flex-shrink: 0;
}
.tag.captain { background: #C9A24B; color: #121815; }
.tag.vice { background: #4A5A50; color: #EDEDE8; }
.flag-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #C1443B; flex-shrink: 0;
}
.prow-stats {
    display: flex;
    gap: 14px;
    font-family: 'IBM Plex Mono', monospace;
    flex-shrink: 0;
}
.pprice { color: #7A8580; font-size: 12px; }
.ppoints { color: #E8E4D8; font-size: 14px; font-weight: 600; min-width: 20px; text-align: right; }

.bench-label {
    font-size: 11px;
    color: #7A8580;
    font-weight: 600;
    letter-spacing: 0.4px;
    margin: 16px 0 6px 4px;
}
</style>
"""


def main():
    st.title("My squad")

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
