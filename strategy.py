"""
Strategy engine producing transfer and chip recommendations under four
playstyle profiles: template, differential, aggressive, conservative.

All transfer suggestions respect the manager's actual bank balance and
(estimated) free transfers, and always show the point cost of any hit taken.
"""

from fpl_data import expected_value, minutes_probability

HIT_COST = 4

PROFILES = ["template", "differential", "aggressive", "conservative"]

PROFILE_DESCRIPTIONS = {
    "template": "Follow the highest-owned, safest performers. Low variance.",
    "differential": "Target low-ownership players with strong EV, to gain rank rather than protect it.",
    "aggressive": "Willing to take hits and play chips early if the EV gain clears a low bar.",
    "conservative": "Never takes a hit. Only plays chips on the clearest, highest-confidence weeks.",
}


def _candidates_for_position(all_players, position, exclude_ids, max_price):
    return [
        p for p in all_players.values()
        if p["position"] == position
        and p["id"] not in exclude_ids
        and p["price"] <= max_price
        and minutes_probability(p) > 0
    ]


def suggest_transfers(profile, squad_players, all_players, fixtures, from_event,
                       bank, free_transfers, lookahead=4):
    """
    squad_players: list of player dicts currently in the manager's squad
    Returns a list of suggestion dicts, best first, each with:
        out, in, net_gain, hit_cost, new_bank, transfers_used
    """
    exclude_ids = {p["id"] for p in squad_players}
    suggestions = []

    for out_player in squad_players:
        max_price = out_player["price"] + bank
        candidates = _candidates_for_position(
            all_players, out_player["position"], exclude_ids, max_price
        )
        out_ev = expected_value(out_player, fixtures, from_event, lookahead)

        scored = []
        for cand in candidates:
            cand_ev = expected_value(cand, fixtures, from_event, lookahead)
            gain = round(cand_ev - out_ev, 2)
            scored.append((cand, cand_ev, gain))

        if not scored:
            continue

        if profile == "template":
            scored.sort(key=lambda x: (x[0]["selected_by_percent"], x[1]), reverse=True)
        elif profile == "differential":
            scored = [s for s in scored if s[0]["selected_by_percent"] < 10]
            scored.sort(key=lambda x: x[2], reverse=True)
        else:
            scored.sort(key=lambda x: x[2], reverse=True)

        if not scored:
            continue

        best_cand, best_ev, gain = scored[0]

        transfers_used = 1
        hit_cost = max(0, transfers_used - free_transfers) * HIT_COST
        net_gain = round(gain - hit_cost, 2)

        if profile == "conservative" and (hit_cost > 0 or net_gain <= 0):
            continue
        if profile == "aggressive" and net_gain <= 1:
            continue
        if profile in ("template", "differential") and net_gain <= 0:
            continue

        new_bank = round(bank + out_player["price"] - best_cand["price"], 1)

        suggestions.append({
            "out": out_player["name"],
            "in": best_cand["name"],
            "position": out_player["position"],
            "gain_before_cost": gain,
            "hit_cost": hit_cost,
            "net_gain": net_gain,
            "new_bank": new_bank,
            "transfers_used": transfers_used,
        })

    suggestions.sort(key=lambda s: s["net_gain"], reverse=True)
    return suggestions


def suggest_chip(profile, squad_players, bench_players, fixtures, from_event,
                  gw_ev_trend, is_blank_or_double_soon):
    """
    Returns (chip_name_or_None, reason_string).
    Thresholds tighten from aggressive -> conservative.
    """
    thresholds = {
        "aggressive": {"tc_multiplier": 1.15, "bb_min_prob": 0.6},
        "template": {"tc_multiplier": 1.3, "bb_min_prob": 0.75},
        "differential": {"tc_multiplier": 1.25, "bb_min_prob": 0.7},
        "conservative": {"tc_multiplier": 1.5, "bb_min_prob": 0.9},
    }[profile]

    # Triple captain: best captain candidate's EV vs their own season baseline
    best = max(squad_players, key=lambda p: expected_value(p, fixtures, from_event, 1))
    best_ev = expected_value(best, fixtures, from_event, 1)
    baseline = expected_value(best, fixtures, max(from_event - 4, 1), 4) / 4
    if baseline > 0 and best_ev / baseline >= thresholds["tc_multiplier"]:
        return "Triple Captain", f"{best['name']}'s projected EV this week is {round(best_ev/baseline,2)}x their recent baseline."

    # Bench boost: all bench players clear a minutes-probability bar
    bench_probs = [minutes_probability(p) for p in bench_players]
    if bench_probs and min(bench_probs) >= thresholds["bb_min_prob"]:
        return "Bench Boost", "All four bench players clear the minutes-probability threshold this week."

    # Free hit: blank/double gameweek detected
    if is_blank_or_double_soon:
        return "Free Hit", "A blank or double gameweek is coming up that badly skews your fixture list."

    # Wildcard: sustained downward trend in squad EV
    if len(gw_ev_trend) >= 3 and all(
        gw_ev_trend[i] < gw_ev_trend[i - 1] for i in range(-2, 0)
    ):
        return "Wildcard", "Squad-wide expected value has fallen for 3+ consecutive gameweeks."

    return None, "No chip clears this profile's threshold this week."
