"""
Decision Log -- the upgraded Agent Briefing page.

M1 memory + M2/M3 structured iterative research + M4 self-critique +
M5 confidence signaling + M6 this UI + M7 gated action-taking.
"""

import difflib
from datetime import datetime, timezone

import streamlit as st

from fpl_data import (
    get_bootstrap, get_fixtures, get_entry_history, get_picks,
    get_current_event, get_next_deadline, estimate_free_transfers,
    build_player_lookup, get_chips_used, build_team_strength, minutes_probability,
)
from ui_components import THEME_CSS, render_squad_diff
from strategy import suggest_transfers, suggest_chip, suggest_captain, PROFILES
from orchestrator import run_agent
from claude_reasoner import ClaudeAPIError
from settings import settings_sidebar, get_settings
import memory
from memory import MemoryError
from fpl_auth import submit_transfers, FPLLoginError
from optimizer import optimize_transfers, OptimizerError

st.set_page_config(page_title="FPL Decision Log", page_icon="\U0001f4dd", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.title("Decision log")
st.caption("Iterative research, self-checked against your actual constraints, with a memory of what happened last time.")

settings_sidebar()
cfg = get_settings()

with st.sidebar:
    threshold_hours = st.number_input(
        "Unlock window (hours before deadline)", min_value=1, max_value=168, value=24,
    )
    st.divider()
    api_key = st.text_input(
        "Anthropic API key", value=st.secrets.get("ANTHROPIC_API_KEY", ""), type="password",
    )
    github_token = st.secrets.get("GITHUB_TOKEN")
    github_repo = st.secrets.get("GITHUB_REPO")
    memory_enabled = bool(github_token and github_repo)
    if memory_enabled:
        st.caption("Memory: connected (GitHub)")
    else:
        st.caption("Memory: not configured -- add GITHUB_TOKEN and GITHUB_REPO to Secrets "
                   "to log decisions and see your track record.")

if not cfg["team_id"].strip().isdigit() or not cfg["rival_id"].strip().isdigit():
    st.warning("Enter numeric team IDs in the sidebar.")
    st.stop()

entry_id, rival_id = int(cfg["team_id"]), int(cfg["rival_id"])

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

# ---------- Past decisions (M1 + M6) ----------

st.subheader("Track record")
if memory_enabled:
    try:
        past = memory.get_recent(github_token, github_repo, n=5)
    except MemoryError as e:
        past = []
        st.warning(f"Couldn't load memory: {e}")

    if not past:
        st.caption("No decisions logged yet -- your first generated recommendation will start the record.")
    for record in past:
        outcome = record.get("outcome", {})
        if outcome.get("resolved"):
            pts = outcome.get("actual_points_gained")
            badge_class = "correct" if (pts or 0) >= 0 else "wrong"
            badge_text = f"{'+' if (pts or 0) >= 0 else ''}{pts} pts vs. the alternative" if pts is not None else "Resolved"
        else:
            badge_class, badge_text = "pending", "Pending"
        st.markdown(
            f'<div style="background:#121815;border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
            f'<span style="font-family:monospace;font-size:11px;color:#7A8580;">GW{record["gameweek"]}</span> '
            f'<span class="outcome-badge {badge_class}">{badge_text}</span>'
            f'<div style="font-size:14px;margin-top:4px;">{record["recommendation"].get("bottom_line", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
else:
    st.caption("Connect memory (sidebar) to see past weeks' calls and whether they paid off.")

st.divider()

# ---------- This week ----------

if hours_remaining > threshold_hours:
    st.info(
        f"This week's briefing unlocks {threshold_hours:.0f} hours before deadline "
        f"(in about {hours_remaining - threshold_hours:.1f}h). Lower the window in the "
        f"sidebar if you want it earlier."
    )
    st.stop()

if cfg["is_logged_in"]:
    free_transfers, bank, chips_used = cfg["free_transfers"], cfg["bank"], cfg["chips_used"]
    ft_source = "Live, from your logged-in FPL account"
else:
    try:
        _hist = get_entry_history(entry_id)
        _est_ft = estimate_free_transfers(_hist)
        chips_used = get_chips_used(_hist)
    except Exception:
        _est_ft, chips_used = None, []
    free_transfers = cfg["ft_override"] if cfg["ft_override"] is not None else _est_ft
    bank = None
    ft_source = "Manually overridden" if cfg["ft_override"] is not None else "Estimated -- verify before generating"

colA, colB = st.columns(2)
colA.metric("Free transfers", free_transfers if free_transfers is not None else "?")
colB.caption(ft_source)

cache_key = f"decision_{entry_id}_{rival_id}_{next_event}_ft{free_transfers}"
if cache_key not in st.session_state:
    st.session_state[cache_key] = None

if st.session_state[cache_key] is None:
    generate = st.button("Generate this week's recommendation")
    if not generate:
        st.stop()
    if not api_key:
        st.error("Enter your Anthropic API key in the sidebar first.")
        st.stop()

    with st.spinner("Researching and drafting..."):
        try:
            fixtures = get_fixtures()
            players = build_player_lookup(bootstrap)
            team_strength = build_team_strength(bootstrap)
            current_event = get_current_event(bootstrap)

            my_history = get_entry_history(entry_id)
            rival_history = get_entry_history(rival_id)
            my_picks = get_picks(entry_id, current_event)
            if bank is None:
                bank = my_picks["entry_history"]["bank"] / 10

            squad_players = [players[p["element"]] for p in my_picks["picks"] if p["multiplier"] > 0]
            bench_players = [players[p["element"]] for p in my_picks["picks"] if p["multiplier"] == 0]
            squad_player_names = [p["name"] for p in squad_players]

            suggestions_by_profile, chips_by_profile = {}, {}
            ev_trend = [gw["points"] for gw in my_history["current"][-5:]]

            for profile in PROFILES:
                suggestions_by_profile[profile] = suggest_transfers(
                    profile, squad_players, players, fixtures, next_event, bank, free_transfers,
                    team_strength=team_strength,
                )
                chip, reason = suggest_chip(
                    profile, squad_players, bench_players, fixtures, next_event, ev_trend,
                    is_blank_or_double_soon=False, team_strength=team_strength, chips_used=chips_used,
                )
                chips_by_profile[profile] = {"chip": chip, "reason": reason}

            captain_options = suggest_captain(squad_players, fixtures, next_event, team_strength=team_strength)

            # Fifth input: the mathematically-exact optimizer, for the free-transfer
            # count as a natural default target. Login isn't currently viable (see
            # fpl_auth.py), so selling price is approximated as current price --
            # flagged in the summary rather than hidden.
            optimizer_summary = {"available": False, "reason": "No free transfers available to target."}
            if free_transfers and free_transfers > 0:
                try:
                    all_candidates = [p for p in players.values() if minutes_probability(p) > 0]
                    opt_result = optimize_transfers(
                        squad_picks=my_picks["picks"], players=players, fixtures=fixtures,
                        from_event=next_event, team_strength=team_strength,
                        target_transfers=free_transfers, bank=bank, free_transfers=free_transfers,
                        all_candidate_players=all_candidates,
                    )
                    optimizer_summary = {
                        "available": True,
                        "target_transfers": free_transfers,
                        "buy": [players[pid]["name"] for pid in opt_result["buy_ids"]],
                        "sell": [players[pid]["name"] for pid in opt_result["sell_ids"]],
                        "ratio_points_per_value": round(opt_result["ratio"], 3),
                        "new_bank": opt_result["new_bank"],
                        "note": "Selling price approximated as current price -- login isn't currently available.",
                    }
                except OptimizerError as e:
                    optimizer_summary = {"available": False, "reason": str(e)}

            context = {
                "gameweek": next_event,
                "my_total": my_history["current"][-1]["total_points"],
                "rival_total": rival_history["current"][-1]["total_points"],
                "rival_mode": cfg["rival_mode"],
                "points_trend": [
                    {"gw": mg["event"], "you": mg["total_points"], "rival": rg["total_points"]}
                    for mg, rg in zip(my_history["current"][-6:], rival_history["current"][-6:])
                ],
                "chips_used": chips_used,
                "bank": bank,
                "free_transfers": free_transfers,
                "transfer_suggestions": {p: suggestions_by_profile[p][:2] for p in PROFILES},
                "chip_suggestions": chips_by_profile,
                "captain_options": [{"name": p["name"], "projected_ev": ev} for p, ev in captain_options],
                "optimizer_suggestion": optimizer_summary,
                "squad_status_flags": [
                    {"name": pl["name"], "status": pl["status"], "news": pl["news"]}
                    for pl in squad_players if pl["status"] != "a"
                ],
            }

            result = run_agent(api_key, context, squad_player_names)

            if memory_enabled:
                try:
                    memory.append_decision(github_token, github_repo, {
                        "gameweek": next_event,
                        "logged_at": datetime.now(timezone.utc).isoformat(),
                        "recommendation": result["recommendation"],
                    })
                except MemoryError as e:
                    st.warning(f"Recommendation generated, but couldn't log to memory: {e}")

            st.session_state[cache_key] = {
                "result": result, "players": players, "squad_players": squad_players,
                "current_picks": my_picks["picks"], "bank": bank, "event_id": next_event,
                "team_id": entry_id,
            }
        except ClaudeAPIError as e:
            st.error(f"AI generation failed: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Generation failed: {e}")
            st.stop()

# ---------- Display this week's result ----------

state = st.session_state[cache_key]
if state:
    rec = state["result"]["recommendation"]
    players = state["players"]

    if not state["result"]["validation_passed"]:
        st.error(
            f"Self-critique caught a problem this couldn't auto-fix: "
            f"{state['result']['validation_error']} -- treat this recommendation with caution."
        )
    elif state["result"]["retries_used"] > 0:
        st.caption(f"(Self-corrected once before passing validation.)")

    st.markdown(f"### {rec['bottom_line']}")

    for field, label in [("transfer", "Transfer"), ("chip", "Chip"), ("captain", "Captain")]:
        item = rec.get(field, {})
        conf_pct = int((item.get("confidence") or 0) * 100)
        st.markdown(
            f'<div class="conf-row"><span class="conf-label">{label}</span>'
            f'<div class="conf-bar-bg"><div class="conf-bar-fill" style="width:{conf_pct}%"></div></div>'
            f'<span style="font-family:monospace;font-size:11px;color:#7A8580;">{conf_pct}%</span></div>',
            unsafe_allow_html=True,
        )
        st.caption(f"**{item.get('action', '')}** -- {item.get('rationale', '')}")

    if rec.get("sources_reconciled"):
        st.info(f"**How the five inputs reconciled:** {rec['sources_reconciled']}")

    if rec.get("watch_outs"):
        st.markdown("**Watch-outs**")
        for w in rec["watch_outs"]:
            st.write(f"- {w}")

    if rec.get("sources"):
        st.caption("Sources checked: " + " · ".join(rec["sources"]))

    # ---------- Squad diff (the visual ask) ----------
    st.subheader("Current vs proposed squad")
    action = rec.get("transfer", {}).get("action", "")
    out_name, in_name = None, None
    for sep in ["->", "\u2192", " to "]:
        if sep in action:
            parts = action.split(sep)
            out_name, in_name = parts[0].strip(), parts[1].strip()
            break

    proposed_ids = {p["element"] for p in state["current_picks"] if p["multiplier"] > 0}
    if out_name and in_name:
        all_names = {pid: p["name"] for pid, p in players.items()}
        out_match = difflib.get_close_matches(out_name, all_names.values(), n=1, cutoff=0.5)
        in_match = difflib.get_close_matches(in_name, all_names.values(), n=1, cutoff=0.5)
        out_id = next((pid for pid, n in all_names.items() if out_match and n == out_match[0]), None)
        in_id = next((pid for pid, n in all_names.items() if in_match and n == in_match[0]), None)
        if out_id in proposed_ids and in_id:
            proposed_ids = (proposed_ids - {out_id}) | {in_id}
        else:
            st.caption("(Couldn't confidently match the transfer text to squad players for the visual diff -- shown unchanged below.)")

    captain_id = next((p["element"] for p in state["current_picks"]
                        if players[p["element"]]["name"].lower() in rec.get("captain", {}).get("action", "").lower()), None)
    vice_id = next((p["element"] for p in state["current_picks"] if p["is_vice_captain"]), None)
    is_tc = "triple" in rec.get("chip", {}).get("action", "").lower()

    diff_html = render_squad_diff(
        state["current_picks"], proposed_ids, players,
        captain_id=captain_id, vice_id=vice_id, captain_multiplier=3 if is_tc else 1,
    )
    st.markdown(f'<div class="sheet">{diff_html}</div>', unsafe_allow_html=True)

    # ---------- M7: gated action-taking ----------
    st.divider()
    st.subheader("Execute (optional)")
    st.warning(
        "This uses an UNOFFICIAL, undocumented FPL endpoint. It can fail silently or "
        "behave unexpectedly if FPL has changed anything since this was last verified. "
        "There is NO UNDO once a real submission succeeds. A dry run below shows exactly "
        "what would be sent, without sending it."
    )

    dry_run_clicked = st.button("Preview exact payload (dry run -- sends nothing)")
    if dry_run_clicked:
        if not (cfg["is_logged_in"] and out_id and in_id):
            st.error("Requires: logged in via Secrets, and a successfully matched transfer above.")
        else:
            out_price = int(players[out_id]["price"] * 10)
            in_price = int(players[in_id]["price"] * 10)
            preview = submit_transfers(
                st.session_state["fpl_session"], state["team_id"], state["event_id"],
                transfers=[{"element_in": in_id, "element_out": out_id,
                            "purchase_price": in_price, "selling_price": out_price}],
                dry_run=True,
            )
            st.json(preview["payload"])
            st.session_state["_last_dry_run_payload"] = preview["payload"]

    if st.session_state.get("_last_dry_run_payload"):
        st.markdown("**Only after reviewing the payload above:**")
        confirm1 = st.checkbox("I've reviewed the exact payload and it matches what I want")
        confirm2 = st.checkbox("I understand this cannot be undone if it succeeds")
        if confirm1 and confirm2:
            if st.button("Submit for real", type="primary"):
                try:
                    live_result = submit_transfers(
                        st.session_state["fpl_session"], state["team_id"], state["event_id"],
                        transfers=st.session_state["_last_dry_run_payload"]["transfers"],
                        chip=st.session_state["_last_dry_run_payload"]["chip"],
                        dry_run=False,
                    )
                    st.success("Submitted. Verify in the FPL app that it applied as expected.")
                    st.json(live_result)
                except FPLLoginError as e:
                    st.error(f"Submission failed: {e}")

    if st.button("Regenerate (calls the API again)"):
        st.session_state[cache_key] = None
        st.session_state.pop("_last_dry_run_payload", None)
        st.rerun()
