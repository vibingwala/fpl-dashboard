"""
Transfers and chips strategy page.
Run the main app with: streamlit run app.py
Then use the sidebar to navigate here.
"""

import streamlit as st

from fpl_data import (
    get_bootstrap, get_fixtures, get_entry_history, get_picks,
    get_current_event, estimate_free_transfers, build_player_lookup,
)
from strategy import suggest_transfers, suggest_chip, PROFILES, PROFILE_DESCRIPTIONS

st.set_page_config(page_title="FPL Strategy", page_icon="\u26bd", layout="wide")
st.title("Transfer and chip strategy")

with st.sidebar:
    st.header("Settings")
    entry_id = st.text_input("Your FPL team ID", value="3486295")
    st.divider()
    st.caption("Free transfers are estimated (public API doesn't expose this). "
               "Correct it here if it doesn't match what the app shows you.")
    ft_override = st.checkbox("Override estimated free transfers")
    ft_manual = st.number_input("Free transfers available", min_value=0, max_value=5, value=1) \
        if ft_override else None

if not entry_id.strip().isdigit():
    st.warning("Enter a numeric team ID in the sidebar.")
    st.stop()

entry_id = int(entry_id)

try:
    bootstrap = get_bootstrap()
    fixtures = get_fixtures()
    history = get_entry_history(entry_id)
    event_id = get_current_event(bootstrap)
    picks_data = get_picks(entry_id, event_id)
except Exception as e:
    st.error(f"Couldn't reach the FPL API: {e}")
    st.stop()

players = build_player_lookup(bootstrap)
bank = picks_data["entry_history"]["bank"] / 10
free_transfers = ft_manual if ft_manual is not None else estimate_free_transfers(history)

squad_players = [players[p["element"]] for p in picks_data["picks"] if p["multiplier"] > 0]
bench_players = [players[p["element"]] for p in picks_data["picks"] if p["multiplier"] == 0]

col1, col2, col3 = st.columns(3)
col1.metric("Bank", f"\u00a3{bank:.1f}m")
col2.metric("Free transfers (est.)", free_transfers)
col3.metric("Gameweek", event_id)

if ft_manual is None:
    st.caption("Free transfers shown above are estimated from your transfer history. "
               "Tick the override in the sidebar if this looks wrong.")

st.divider()

ev_trend = [gw["points"] for gw in history["current"][-5:]]

tabs = st.tabs([p.capitalize() for p in PROFILES])

for tab, profile in zip(tabs, PROFILES):
    with tab:
        st.caption(PROFILE_DESCRIPTIONS[profile])

        st.subheader("Suggested transfers")
        suggestions = suggest_transfers(
            profile, squad_players, players, fixtures, event_id + 1,
            bank, free_transfers,
        )

        if not suggestions:
            st.write("No transfer clears this profile's bar this week. Bank the free transfer.")
        else:
            for s in suggestions[:3]:
                hit_note = f" (\u22124 hit)" if s["hit_cost"] > 0 else " (free transfer)"
                st.markdown(
                    f"**{s['out']} \u2192 {s['in']}** ({s['position']}){hit_note}"
                )
                mcol1, mcol2, mcol3 = st.columns(3)
                mcol1.metric("Net gain", f"{s['net_gain']:+.1f} pts")
                mcol2.metric("New bank", f"\u00a3{s['new_bank']:.1f}m")
                mcol3.metric("Hit cost", f"-{s['hit_cost']} pts")
                st.divider()

        st.subheader("Chip recommendation")
        chip, reason = suggest_chip(
            profile, squad_players, bench_players, fixtures, event_id,
            ev_trend, is_blank_or_double_soon=False,
        )
        if chip:
            st.success(f"**{chip}** \u2014 {reason}")
        else:
            st.info(reason)
