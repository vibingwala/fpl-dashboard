"""
Agent briefing page -- the in-app version of the standalone email agent.
Only generates content within a configurable window before the deadline
(default 24 hours), since the AI call has a real cost and isn't useful
far out from the deadline anyway.
"""

from datetime import datetime, timezone

import streamlit as st

from fpl_data import (
    get_bootstrap, get_fixtures, get_entry_history, get_picks,
    get_current_event, get_next_deadline, estimate_free_transfers,
    build_player_lookup, get_chips_used, build_team_strength,
)
from strategy import suggest_transfers, suggest_chip, suggest_captain, PROFILES
from visuals import cumulative_points_chart, gap_bar_chart, transfer_options_chart
from claude_reasoner import generate_weekly_analysis, ClaudeAPIError

st.set_page_config(page_title="FPL Agent Briefing", page_icon="\U0001f916", layout="wide")
st.title("Agent briefing")
st.caption("The same analysis the email agent sends -- generated on demand, right here.")

with st.sidebar:
    st.header("Settings")
    entry_id = st.text_input("Your FPL team ID", value="3486295")
    rival_id = st.text_input("Rival team ID (your benchmark, e.g. rank 1)", value="7491201")
    threshold_hours = st.number_input(
        "Unlock window (hours before deadline)", min_value=1, max_value=168, value=24,
    )
    st.divider()
    st.caption("Free transfers are estimated (the public API doesn't expose this). "
               "Verify it below before generating -- a wrong number here wastes a "
               "paid API call on bad facts.")
    ft_override = st.checkbox("Override estimated free transfers")
    ft_manual = st.number_input("Free transfers available", min_value=0, max_value=5, value=1) \
        if ft_override else None
    st.divider()
    api_key = st.text_input(
        "Anthropic API key", value=st.secrets.get("ANTHROPIC_API_KEY", ""), type="password",
    )
    st.caption("Stored only for this session -- not saved anywhere. "
               "On Streamlit Cloud, set ANTHROPIC_API_KEY in the app's Secrets "
               "instead so you don't have to paste it each visit.")

if not entry_id.strip().isdigit() or not rival_id.strip().isdigit():
    st.warning("Enter numeric team IDs in the sidebar.")
    st.stop()

entry_id, rival_id = int(entry_id), int(rival_id)

try:
    bootstrap = get_bootstrap()
except Exception as e:
    st.error(f"Couldn't reach the FPL API: {e}")
    st.stop()

next_event, deadline_iso = get_next_deadline(bootstrap)

if next_event is None:
    st.info("No upcoming deadline found -- the season may be over, or between seasons.")
    st.stop()

deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
hours_remaining = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600

col1, col2 = st.columns(2)
col1.metric("Next deadline", deadline.strftime("%a %d %b, %H:%M UTC"))
col2.metric("Time remaining", f"{hours_remaining:.1f}h")

if hours_remaining > threshold_hours:
    st.info(
        f"The agent briefing unlocks {threshold_hours:.0f} hours before deadline. "
        f"That's in about {hours_remaining - threshold_hours:.1f} more hours -- check back then, "
        f"or lower the unlock window in the sidebar if you want it earlier."
    )
    st.stop()

st.success(f"Within the {threshold_hours:.0f}-hour window -- briefing available.")

try:
    _preview_history = get_entry_history(entry_id)
    _estimated_ft = estimate_free_transfers(_preview_history)
except Exception:
    _estimated_ft = None

free_transfers = ft_manual if ft_manual is not None else _estimated_ft

col3, col4 = st.columns(2)
col3.metric(
    "Free transfers going into this briefing",
    free_transfers if free_transfers is not None else "?",
)
col4.caption(
    "Manually overridden in sidebar" if ft_manual is not None
    else "Estimated -- check this against the app before generating"
)

cache_key = f"briefing_{entry_id}_{rival_id}_{next_event}_ft{free_transfers}"

if cache_key not in st.session_state:
    st.session_state[cache_key] = None

if st.session_state[cache_key] is None:
    st.write("Nothing generated yet for this gameweek.")
    generate = st.button("Generate AI briefing (calls the Claude API -- small cost)")
    if not generate:
        st.stop()
    if not api_key:
        st.error("Enter your Anthropic API key in the sidebar first.")
        st.stop()

    with st.spinner("Pulling data and generating the briefing..."):
        try:
            fixtures = get_fixtures()
            players = build_player_lookup(bootstrap)
            team_strength = build_team_strength(bootstrap)
            current_event = get_current_event(bootstrap)

            my_history = get_entry_history(entry_id)
            rival_history = get_entry_history(rival_id)
            my_picks = get_picks(entry_id, current_event)

            bank = my_picks["entry_history"]["bank"] / 10

            squad_players = [players[p["element"]] for p in my_picks["picks"] if p["multiplier"] > 0]
            bench_players = [players[p["element"]] for p in my_picks["picks"] if p["multiplier"] == 0]

            suggestions_by_profile, chips_by_profile = {}, {}
            ev_trend = [gw["points"] for gw in my_history["current"][-5:]]

            for profile in PROFILES:
                suggestions_by_profile[profile] = suggest_transfers(
                    profile, squad_players, players, fixtures, next_event, bank, free_transfers,
                    team_strength=team_strength,
                )
                chip, reason = suggest_chip(
                    profile, squad_players, bench_players, fixtures, next_event, ev_trend,
                    is_blank_or_double_soon=False, team_strength=team_strength,
                )
                chips_by_profile[profile] = {"chip": chip, "reason": reason}

            captain_options = suggest_captain(squad_players, fixtures, next_event, team_strength=team_strength)

            context = {
                "gameweek": next_event,
                "my_total": my_history["current"][-1]["total_points"],
                "rival_total": rival_history["current"][-1]["total_points"],
                "points_trend": [
                    {
                        "gw": my_gw["event"],
                        "you": my_gw["total_points"],
                        "rival": rival_gw["total_points"],
                    }
                    for my_gw, rival_gw in zip(
                        my_history["current"][-6:], rival_history["current"][-6:]
                    )
                ],
                "chips_used": get_chips_used(my_history),
                "bank": bank,
                "free_transfers": free_transfers,
                "transfer_suggestions": {p: suggestions_by_profile[p][:2] for p in PROFILES},
                "chip_suggestions": chips_by_profile,
                "captain_options": [
                    {"name": p["name"], "projected_ev": ev} for p, ev in captain_options
                ],
                "squad_status_flags": [
                    {"name": pl["name"], "status": pl["status"], "news": pl["news"]}
                    for pl in squad_players if pl["status"] != "a"
                ],
            }

            narrative = generate_weekly_analysis(api_key, context)
            charts = {
                "cumulative": cumulative_points_chart(my_history, rival_history),
                "gap": gap_bar_chart(my_history, rival_history),
                "transfers": transfer_options_chart(suggestions_by_profile),
            }
            st.session_state[cache_key] = {"narrative": narrative, "charts": charts}
        except ClaudeAPIError as e:
            st.error(f"AI briefing failed: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Briefing generation failed: {e}")
            st.stop()

result = st.session_state[cache_key]
if result:
    st.markdown(result["narrative"])
    st.image(result["charts"]["cumulative"])
    st.image(result["charts"]["gap"])
    st.image(result["charts"]["transfers"])
    if st.button("Regenerate (calls the API again -- another small cost)"):
        st.session_state[cache_key] = None
        st.rerun()
