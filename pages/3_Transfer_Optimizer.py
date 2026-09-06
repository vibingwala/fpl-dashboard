"""
Transfer Optimizer -- maximizes aggregate points-per-value of incoming
players for a target number of transfers, with excess-transfer hit cost
folded in as a market-rate value inflation. Login is not currently viable
(see fpl_auth.py) -- selling price is approximated as current price, which
is imperfect but the best available without it.
"""

import streamlit as st

from fpl_data import (
    get_bootstrap, get_fixtures, get_current_event, get_picks, build_player_lookup,
    build_team_strength, minutes_probability,
)
from ui_components import THEME_CSS, render_squad_diff
from settings import settings_sidebar, get_settings
from optimizer import optimize_transfers, OptimizerError

st.set_page_config(page_title="Transfer Optimizer", page_icon="\U0001f9ee", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.title("Transfer optimizer")
st.caption("Maximizes total points \u00f7 total value of incoming players for a target transfer count.")

settings_sidebar()
cfg = get_settings()

st.warning(
    "Selling prices are approximated as current price (login isn't currently "
    "available -- see sidebar). This is WRONG whenever a player has risen in "
    "value since you bought them, since FPL's 50% profit-sell rule means you'd "
    "actually get less back than their current price. Budget results here may "
    "be slightly optimistic as a result."
)

if not cfg["team_id"].strip().isdigit():
    st.warning("Enter a numeric team ID in the sidebar.")
    st.stop()

entry_id = int(cfg["team_id"])

try:
    bootstrap = get_bootstrap()
    fixtures = get_fixtures()
except Exception as e:
    st.error(f"Couldn't reach the FPL API: {e}")
    st.stop()

current_event = get_current_event(bootstrap)
next_event = current_event + 1
players = build_player_lookup(bootstrap)
team_strength = build_team_strength(bootstrap)

try:
    my_picks_data = get_picks(entry_id, current_event)
except Exception as e:
    st.error(f"Couldn't reach the FPL API: {e}")
    st.stop()

squad_picks = my_picks_data["picks"]  # full 15-man squad, not just the starting XI
bank = my_picks_data["entry_history"]["bank"] / 10
free_transfers = cfg["ft_override"] if cfg["ft_override"] is not None else 1

target_transfers = st.number_input("Target number of transfers", min_value=1, max_value=5, value=1)

hit_pts_preview = 4 * max(0, target_transfers - free_transfers)
st.caption(
    f"Free transfers: {free_transfers} \u00b7 Bank: \u00a3{bank:.1f}m \u00b7 "
    + (f"{hit_pts_preview} pt hit equivalent will be folded into the ratio" if hit_pts_preview else "No hit cost")
)

if st.button("Find optimal transfers"):
    with st.spinner("Searching..."):
        try:
            candidate_players = [
                p for p in players.values() if minutes_probability(p) > 0
            ]
            result = optimize_transfers(
                squad_picks=squad_picks,
                players=players,
                fixtures=fixtures,
                from_event=next_event,
                team_strength=team_strength,
                target_transfers=target_transfers,
                bank=bank,
                free_transfers=free_transfers,
                all_candidate_players=candidate_players,
            )
            st.session_state["_optimizer_result"] = result
        except OptimizerError as e:
            st.error(str(e))
            st.session_state["_optimizer_result"] = None

result = st.session_state.get("_optimizer_result")
if result:
    buy_names = [players[pid]["name"] for pid in result["buy_ids"]]
    sell_names = [players[pid]["name"] for pid in result["sell_ids"]]

    st.subheader(" & ".join(sell_names) + "  \u2192  " + " & ".join(buy_names))

    col1, col2, col3 = st.columns(3)
    col1.metric("Ratio (pts per \u00a3m)", f"{result['ratio']:.2f}")
    col2.metric("New bank", f"\u00a3{result['new_bank']:.1f}m")
    col3.metric("Hit cost", f"-{result['hit_cost_points']} pts" if result["hit_cost_points"] else "None")

    with st.expander("Full calculation detail"):
        st.write(f"Incoming projected points (next 4 GWs): {result['incoming_points']:.2f}")
        st.write(f"Incoming total value: \u00a3{result['incoming_value']:.1f}m")
        st.write(f"Market rate (\u03bb, pts per \u00a3m across candidate pool): {result['lambda_rate']:.3f}")
        st.write(f"Hit-cost value inflation (\u0394V): \u00a3{result['delta_v_hit']:.2f}m")
        st.write(f"Points forfeited by selling: {result['forfeited_points']:.2f}")
        st.write(f"Dinkelbach iterations to convergence: {result['dinkelbach_iterations']}")
        st.caption("Solved exactly via PuLP/CBC across the full candidate pool -- no shortlist bound.")
        if result.get("approximated_selling_price"):
            st.caption("\u26a0\ufe0f Selling prices were approximated as current price (see warning above).")

    st.subheader("Current vs proposed squad")
    current_picks_shape = [
        {"element": p["element"], "multiplier": 1} for p in squad_picks
    ]
    proposed_ids = ({p["element"] for p in squad_picks} - set(result["sell_ids"])) | set(result["buy_ids"])
    diff_html = render_squad_diff(current_picks_shape, proposed_ids, players)
    st.markdown(f'<div class="sheet">{diff_html}</div>', unsafe_allow_html=True)
