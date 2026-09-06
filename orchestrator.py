"""
Orchestrator -- runs M2/M3 (generate) -> M4 (validate) -> retry once if
invalid -> M1 (log to memory), as a single callable used by the Decision
Log page.
"""

from claude_reasoner import generate_recommendation, ClaudeAPIError
from critique import validate_recommendation


def run_agent(api_key, context, squad_player_names, max_retries=1):
    """
    Returns:
        {
            "recommendation": dict (matches the submit_recommendation schema),
            "validation_passed": bool,
            "validation_error": str | None,   # only set if still failing after retries
            "retries_used": int,
        }
    Raises ClaudeAPIError if the underlying API call itself fails (not a
    validation failure -- an actual request/auth/network problem).
    """
    rec = generate_recommendation(api_key, context)
    retries_used = 0

    for _ in range(max_retries):
        violation = validate_recommendation(rec, context, squad_player_names)
        if violation is None:
            return {"recommendation": rec, "validation_passed": True, "validation_error": None, "retries_used": retries_used}
        rec = generate_recommendation(api_key, context, validation_feedback=violation)
        retries_used += 1

    final_violation = validate_recommendation(rec, context, squad_player_names)
    return {
        "recommendation": rec,
        "validation_passed": final_violation is None,
        "validation_error": final_violation,
        "retries_used": retries_used,
    }
