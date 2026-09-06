"""
M2 + M3 -- Structured recommendation with iterative research.

Replaces free-text prose with a forced structured output (via Claude's
native tool-use), and lets the model run multiple web searches within the
same call before committing to a final recommendation -- genuine iterative
research instead of one search pass dressed up as one.
"""

import json
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

RECOMMENDATION_TOOL = {
    "name": "submit_recommendation",
    "description": "Submit the final weekly FPL recommendation once research is complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "bottom_line": {"type": "string", "description": "One-sentence governing recommendation."},
            "transfer": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "e.g. 'Kayode -> Gvardiol' or 'Bank it'"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["action", "rationale", "confidence"],
            },
            "chip": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Chip name or 'Hold all chips'"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["action", "rationale", "confidence"],
            },
            "captain": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Player name to captain"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["action", "rationale", "confidence"],
            },
            "watch_outs": {
                "type": "array", "items": {"type": "string"},
                "description": "Real injury/rotation risks found via search. Empty list if none.",
            },
            "sources": {
                "type": "array", "items": {"type": "string"},
                "description": "Brief descriptions of sources actually checked, e.g. 'BBC Sport team news'.",
            },
        },
        "required": ["bottom_line", "transfer", "chip", "captain", "watch_outs", "sources"],
    },
}


class ClaudeAPIError(Exception):
    pass


def _build_prompt(context, validation_feedback=None):
    free_transfers = context.get("free_transfers")
    bank = context.get("bank")
    rival_mode = context.get("rival_mode", "Season-long (beat their cumulative total)")
    is_head_to_head = "Head-to-head" in rival_mode

    goal_statement = (
        "beat their score in THIS gameweek specifically -- a strong week now matters "
        "more than season-long conservatism, since head-to-head resets every week"
        if is_head_to_head else
        "finish the season with a higher cumulative total than theirs -- a single "
        "bad gameweek matters far less than the season-long trend"
    )

    correction_block = ""
    if validation_feedback:
        correction_block = f"""
YOUR PREVIOUS ATTEMPT WAS REJECTED for this specific reason: {validation_feedback}
Fix exactly this issue and resubmit via submit_recommendation. Do not repeat the same mistake.
"""

    return f"""You are a sharp FPL (Fantasy Premier League) analyst. The manager is a
mathematician who dislikes walls of text and wants management-consulting-style output:
decisive, assertion-first, no hedging without cause.

HARD CONSTRAINT: the manager has exactly {free_transfers} free transfer(s) and a bank of
£{bank}m. Any transfer beyond the free count costs -4 points as a hit -- name this cost
explicitly if you recommend it. Never recommend combining transfers from different
strategy profiles without accounting for the total hit cost.

GOAL: {goal_statement} (the rival benchmark in the data below).

Research before you answer: use web_search as many times as genuinely useful -- check
squad injury/rotation news AND the opponent's actual current form (not just their
season-long strength rating) for the transfer and captain decisions. Follow up with a
second search if the first result is ambiguous. Do not guess when you can check.

Once research is sufficient, call submit_recommendation with your final answer. Do not
recommend a chip already in chips_used. Do not write prose outside the tool call --
the tool call IS the answer.
{correction_block}
Data:
{json.dumps(context, indent=2)}"""


def generate_recommendation(api_key, context: dict, validation_feedback=None) -> dict:
    """
    Returns the structured recommendation dict (matching RECOMMENDATION_TOOL's
    schema) plus '_raw_text' (any prose reasoning alongside the tool call, for
    transparency/debugging).

    validation_feedback: if this is a retry after M4's self-critique rejected
    a previous attempt, pass the specific violation here so the model corrects
    it directly rather than starting from scratch.
    """
    if not api_key or not api_key.startswith("sk-ant-"):
        raise ClaudeAPIError(
            "That doesn't look like a valid Anthropic API key (should start with "
            "'sk-ant-'). Check console.anthropic.com and Streamlit Secrets."
        )

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": _build_prompt(context, validation_feedback)}],
        "tools": [
            {"type": "web_search_20250305", "name": "web_search"},
            RECOMMENDATION_TOOL,
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=90)
    except requests.RequestException as e:
        raise ClaudeAPIError(f"Network error reaching the Claude API: {e}")

    if response.status_code == 401:
        raise ClaudeAPIError("Authentication failed (401) -- check the API key.")
    if response.status_code == 404:
        raise ClaudeAPIError(f"Model not found (404) -- '{MODEL}' may have been retired.")
    if response.status_code == 429:
        raise ClaudeAPIError("Rate limited (429) -- check billing/usage at console.anthropic.com.")
    if response.status_code >= 400:
        raise ClaudeAPIError(f"Claude API returned HTTP {response.status_code}: {response.text[:500]}")

    data = response.json()
    content = data.get("content", [])

    tool_call = next((b for b in content if b.get("type") == "tool_use" and b.get("name") == "submit_recommendation"), None)
    if not tool_call:
        raise ClaudeAPIError(
            "Claude didn't call submit_recommendation -- it may have run out of steps "
            "mid-research. Try regenerating."
        )

    raw_text = "\n".join(b["text"] for b in content if b.get("type") == "text")
    result = dict(tool_call["input"])
    result["_raw_text"] = raw_text
    return result
