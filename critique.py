"""
M4 -- Self-critique.

Deterministic (free, no API call) validation of the structured recommendation
against hard facts the model might get wrong: free transfer count, chips
already used, captain must be an actual squad member. This is exactly the
class of bug we hit before (the "use both transfers" incident) -- catching
it in code every time, rather than hoping the prompt is followed.
"""


def validate_recommendation(rec: dict, context: dict, squad_player_names: list) -> str | None:
    """Returns None if the recommendation is valid, or a specific violation
    string describing exactly what's wrong (fed back to the model for one
    corrective retry)."""

    free_transfers = context.get("free_transfers") or 0
    chips_used = set(c.lower().replace(" ", "") for c in (context.get("chips_used") or []))

    transfer_action = rec.get("transfer", {}).get("action", "").lower()
    if free_transfers <= 0 and "->" in transfer_action and "hit" not in transfer_action and "-4" not in transfer_action:
        return (
            f"free_transfers is {free_transfers}, but the transfer recommendation "
            f"('{rec['transfer']['action']}') doesn't mention taking a hit. Either "
            f"change the recommendation to 'Bank it', or explicitly justify the -4 hit."
        )

    chip_action = rec.get("chip", {}).get("action", "").lower().replace(" ", "")
    for used in chips_used:
        if used and used in chip_action and "hold" not in chip_action:
            return (
                f"The chip recommendation ('{rec['chip']['action']}') suggests a chip "
                f"that chips_used shows is already played this season. Recommend "
                f"'Hold all chips' or a different, unused chip instead."
            )

    captain_name = rec.get("captain", {}).get("action", "")
    if squad_player_names and not any(
        captain_name.lower() in name.lower() or name.lower() in captain_name.lower()
        for name in squad_player_names
    ):
        return (
            f"The captain recommendation ('{captain_name}') doesn't match any player "
            f"actually in the squad ({', '.join(squad_player_names)}). Pick a real "
            f"squad member."
        )

    for field in ("transfer", "chip", "captain"):
        conf = rec.get(field, {}).get("confidence")
        if conf is None or not (0 <= conf <= 1):
            return f"'{field}.confidence' must be a number between 0 and 1, got {conf!r}."

    return None
