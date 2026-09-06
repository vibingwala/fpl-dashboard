"""
Shared squad-rendering UI components. Used by app.py (Squad View) and
pages/2_Agent_Briefing.py (Decision Log) so the visual language -- and the
markdown-indentation gotcha fix -- lives in exactly one place.
"""

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

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


def _flatten(html: str) -> str:
    """Strip leading whitespace from every line. Markdown treats 4+ leading
    spaces as a code block regardless of unsafe_allow_html, which silently
    turns rendered HTML into literal displayed text -- this prevents that."""
    return "\n".join(line.strip() for line in html.strip().split("\n"))


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


def player_row_html(player, is_captain=False, is_vice=False, multiplier=1):
    accent = team_color(player["team_short"])
    tag = ""
    if is_captain:
        tag = f'<span class="tag captain">C{" ×3" if multiplier == 3 else ""}</span>'
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


def diff_row_html(player, status="unchanged", is_captain=False, is_vice=False, bench_num=None):
    """M6: a squad row that highlights whether this player is leaving (OUT),
    arriving (IN), or unchanged -- for the current-vs-proposed diff view."""
    accent = team_color(player["team_short"])
    css_class = {"out": "prow-out", "in": "prow-in", "unchanged": ""}[status]
    name_class = {"out": "pname-out", "in": "pname-in", "unchanged": "pname"}[status]

    tag = ""
    if is_captain:
        tag = f'<span class="tag captain">C{" ×3" if is_captain == "triple" else ""}</span>'
    elif is_vice:
        tag = '<span class="tag vice">V</span>'

    diff_tag = ""
    if status == "out":
        diff_tag = '<span class="diff-tag out-tag">OUT</span>'
    elif status == "in":
        diff_tag = '<span class="diff-tag in-tag">IN</span>'

    bench_label = f'<span class="bench-num">{bench_num}</span>' if bench_num else ""

    return _flatten(f"""
    <div class="prow {css_class}" style="border-left-color:{accent};">
        <div class="prow-main">
            {bench_label}
            <span class="{name_class}">{player['name']}</span>
            {tag}
            <span class="pteam">{player['team_short']}</span>
        </div>
        <div class="prow-stats">
            {diff_tag}
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


def render_squad_diff(current_picks, proposed_element_ids, players, captain_id=None, vice_id=None, captain_multiplier=1):
    """M6: renders the full squad with OUT/IN highlighting for whichever
    element IDs differ between current_picks and proposed_element_ids."""
    current_ids = {p["element"] for p in current_picks if p["multiplier"] > 0}
    proposed_ids = set(proposed_element_ids)

    out_ids = current_ids - proposed_ids
    in_ids = proposed_ids - current_ids

    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    all_ids = current_ids | in_ids
    for pid in all_ids:
        player = players[pid]
        status = "out" if pid in out_ids else ("in" if pid in in_ids else "unchanged")
        by_pos[player["position"]].append((pid, player, status))

    section_labels = {"GKP": "Goalkeeper", "DEF": "Defence", "MID": "Midfield", "FWD": "Attack"}
    sections_html = ""
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        rows = "".join(
            diff_row_html(
                player,
                status=status,
                is_captain=("triple" if captain_multiplier == 3 else True) if pid == captain_id else False,
                is_vice=(pid == vice_id),
            )
            for pid, player, status in by_pos[pos]
        )
        if rows:
            sections_html += _flatten(f"""
            <div class="section">
                <div class="section-label">{section_labels[pos]}</div>
                {rows}
            </div>
            """)
    return sections_html


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
.prow-out { opacity: 0.5; }
.prow-in { background: #1a2a1f; }
.prow-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pname, .pname-in {
    font-size: 14px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.pname { color: #EDEDE8; }
.pname-out { color: #7A8580; text-decoration: line-through; font-size: 14px; }
.pname-in { color: #4C9A6A; font-weight: 600; }
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
.diff-tag {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9.5px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 3px;
}
.diff-tag.out-tag { background: rgba(193,68,59,0.2); color: #C1443B; }
.diff-tag.in-tag { background: rgba(76,154,106,0.2); color: #4C9A6A; }
.bench-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #7A8580;
    width: 16px;
    flex-shrink: 0;
}
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

.conf-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.conf-label { font-size: 11px; color: #7A8580; width: 90px; flex-shrink: 0; }
.conf-bar-bg { flex: 1; height: 6px; background: #182019; border-radius: 3px; overflow: hidden; }
.conf-bar-fill { height: 100%; background: #C9A24B; }

.outcome-badge { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 10px; }
.outcome-badge.correct { background: rgba(76,154,106,0.15); color: #4C9A6A; }
.outcome-badge.wrong { background: rgba(193,68,59,0.15); color: #C1443B; }
.outcome-badge.pending { background: rgba(201,162,75,0.15); color: #C9A24B; }
</style>
"""
