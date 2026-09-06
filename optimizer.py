"""
Multi-transfer optimizer -- exact solve via PuLP/CBC + Dinkelbach's algorithm.

The objective R(I) = sum(p_j) / (sum(v_j) + delta_V_hit) is a ratio, which
MILP solvers can't optimize directly. Dinkelbach's algorithm (1967) reduces
this to a sequence of ordinary LINEAR problems: for a trial ratio q, solve
    F(q) = max sum(x_j * p_j) - q * sum(x_j * v_j)
subject to the real constraints, then update q to the ratio actually
achieved and repeat until it stops changing. This is exact, not a heuristic,
and removes the need to bound the candidate pool -- CBC searches every
real eligible player.

REQUIRES LOGIN: accurate budget math needs each outgoing player's real
selling_price (see fpl_auth.py) -- refuses to run without it.
"""

import pulp

from fpl_data import expected_value

POSITIONS = ["GKP", "DEF", "MID", "FWD"]
MAX_DINKELBACH_ITERATIONS = 20
CONVERGENCE_TOLERANCE = 1e-6


class OptimizerError(Exception):
    pass


def compute_market_rate(candidate_points_values):
    """lambda = mean(points/value) across the candidate pool."""
    ratios = [pv["points"] / pv["value"] for pv in candidate_points_values if pv["value"] > 0]
    if not ratios:
        raise OptimizerError("No candidates available to compute a market rate from.")
    return sum(ratios) / len(ratios)


def _solve_milp(q, squad_entries, candidate_entries, T, bank, current_club_counts):
    """One Dinkelbach iteration: an ordinary linear MILP solve for trial
    ratio q. Returns (chosen_buy_ids, chosen_sell_ids) or None if infeasible."""
    prob = pulp.LpProblem("transfer_optimizer", pulp.LpMaximize)

    x = {c["id"]: pulp.LpVariable(f"x_{c['id']}", cat="Binary") for c in candidate_entries}
    y = {s["id"]: pulp.LpVariable(f"y_{s['id']}", cat="Binary") for s in squad_entries}

    prob += (
        pulp.lpSum(x[c["id"]] * c["points"] for c in candidate_entries)
        - q * pulp.lpSum(x[c["id"]] * c["value"] for c in candidate_entries)
    )

    prob += pulp.lpSum(x.values()) == T
    prob += pulp.lpSum(y.values()) == T

    for pos in POSITIONS:
        cand_ids = [c["id"] for c in candidate_entries if c["position"] == pos]
        squad_ids = [s["id"] for s in squad_entries if s["position"] == pos]
        prob += pulp.lpSum(x[cid] for cid in cand_ids) == pulp.lpSum(y[sid] for sid in squad_ids)

    prob += (
        bank
        + pulp.lpSum(y[s["id"]] * s["selling_price"] for s in squad_entries)
        - pulp.lpSum(x[c["id"]] * c["value"] for c in candidate_entries)
        >= 0
    )

    all_clubs = set(current_club_counts) | {c["team_id"] for c in candidate_entries}
    for club in all_clubs:
        squad_club_ids = [s["id"] for s in squad_entries if s["team_id"] == club]
        cand_club_ids = [c["id"] for c in candidate_entries if c["team_id"] == club]
        prob += (
            current_club_counts.get(club, 0)
            - pulp.lpSum(y[sid] for sid in squad_club_ids)
            + pulp.lpSum(x[cid] for cid in cand_club_ids)
            <= 3
        )

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if pulp.LpStatus[prob.status] != "Optimal":
        return None

    buy_ids = [c["id"] for c in candidate_entries if pulp.value(x[c["id"]]) > 0.5]
    sell_ids = [s["id"] for s in squad_entries if pulp.value(y[s["id"]]) > 0.5]
    return buy_ids, sell_ids


def optimize_transfers(squad_picks, players, fixtures, from_event, team_strength,
                        target_transfers, bank, free_transfers, all_candidate_players, n=4):
    """
    squad_picks: list of dicts with at minimum 'element'. If 'selling_price'
    is present (from authenticated my-team data), it's used directly -- the
    accurate case. If absent, current price is used as an approximation,
    with 'approximated_selling_price': True flagged in the result so callers
    can warn the user. This approximation is WRONG whenever a player has
    risen in value since being bought (FPL's 50% profit-sell rule), but
    login (the accurate path) isn't currently viable -- see fpl_auth.py.

    Returns a dict describing the exact optimum, or raises OptimizerError.
    """
    T = target_transfers
    if T <= 0:
        raise OptimizerError("target_transfers must be at least 1.")

    approximated_selling_price = not all("selling_price" in p for p in squad_picks)

    squad_ids = {p["element"] for p in squad_picks}

    squad_entries = []
    current_club_counts = {}
    for pick in squad_picks:
        player = players[pick["element"]]
        if "selling_price" in pick:
            selling_price = pick["selling_price"] / 10
        else:
            selling_price = player["price"]  # approximation -- see docstring
        squad_entries.append({
            "id": player["id"], "position": player["position"], "team_id": player["team_id"],
            "selling_price": selling_price,
            "points": expected_value(player, fixtures, from_event, n, team_strength),
        })
        current_club_counts[player["team_id"]] = current_club_counts.get(player["team_id"], 0) + 1

    position_caps = {pos: len([s for s in squad_entries if s["position"] == pos]) for pos in POSITIONS}
    if T > sum(position_caps.values()):
        raise OptimizerError(f"Target of {T} exceeds squad size.")

    # Precompute once -- points/value don't change between Dinkelbach iterations, only q does.
    candidate_entries = []
    for p in all_candidate_players:
        if p["id"] in squad_ids:
            continue
        candidate_entries.append({
            "id": p["id"], "position": p["position"], "team_id": p["team_id"], "value": p["price"],
            "points": expected_value(p, fixtures, from_event, n, team_strength),
        })
    if not candidate_entries:
        raise OptimizerError("No eligible candidates found.")

    lambda_rate = compute_market_rate(candidate_entries)
    delta_v_hit = (4 * max(0, T - free_transfers)) / lambda_rate

    q = 0.0
    result = None
    iterations = 0
    for iterations in range(1, MAX_DINKELBACH_ITERATIONS + 1):
        solved = _solve_milp(q, squad_entries, candidate_entries, T, bank, current_club_counts)
        if solved is None:
            raise OptimizerError(
                f"No feasible transfer combination exists for {T} transfers under your "
                f"current budget and club-limit constraints."
            )
        buy_ids, sell_ids = solved

        buy_points = sum(c["points"] for c in candidate_entries if c["id"] in buy_ids)
        buy_value = sum(c["value"] for c in candidate_entries if c["id"] in buy_ids)
        new_q = buy_points / (buy_value + delta_v_hit) if (buy_value + delta_v_hit) > 0 else 0

        result = {
            "buy_ids": tuple(buy_ids), "sell_ids": tuple(sell_ids),
            "ratio": new_q, "incoming_points": buy_points, "incoming_value": buy_value,
        }
        if abs(new_q - q) < CONVERGENCE_TOLERANCE:
            break
        q = new_q

    sell_value = sum(s["selling_price"] for s in squad_entries if s["id"] in result["sell_ids"])
    forfeited_points = sum(s["points"] for s in squad_entries if s["id"] in result["sell_ids"])

    result.update({
        "forfeited_points": forfeited_points,
        "delta_v_hit": delta_v_hit,
        "lambda_rate": lambda_rate,
        "hit_cost_points": 4 * max(0, T - free_transfers),
        "dinkelbach_iterations": iterations,
        "new_bank": round(bank + sell_value - result["incoming_value"], 1),
        "approximated_selling_price": approximated_selling_price,
    })
    return result
