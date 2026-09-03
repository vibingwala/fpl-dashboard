"""
Calls the Claude API to generate the narrative analysis: performance review,
structural comparison to the rival, and a final synthesized recommendation
across all four strategy profiles, judged against the season-long target.
"""

import json
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


class ClaudeAPIError(Exception):
    """Raised with a human-readable explanation instead of a bare HTTP error."""
    pass


def _extract_text(content_blocks):
    return "\n".join(b["text"] for b in content_blocks if b.get("type") == "text")


def generate_weekly_analysis(api_key, context: dict) -> str:
    """
    context should include: gameweek, my_total, rival_total, points_trend
    (per-gameweek you-vs-rival history), bank, free_transfers_estimated,
    transfer_suggestions (by profile), chip_suggestions (by profile),
    chips_used (list already played), squad_status_flags.
    Returns a plain-text/markdown narrative ready to drop into the email
    or app page.

    Raises ClaudeAPIError with a specific, actionable message on failure,
    instead of letting a generic HTTP error surface.
    """
    if not api_key or not api_key.startswith("sk-ant-"):
        raise ClaudeAPIError(
            "That doesn't look like a valid Anthropic API key (should start with "
            "'sk-ant-'). Check console.anthropic.com and make sure you copied the "
            "full key, and that it's set correctly in Streamlit Secrets."
        )

    prompt = f"""You are a sharp, concise FPL (Fantasy Premier League) analyst writing a
weekly briefing for a manager who is a mathematician and dislikes walls of text.
Use short paragraphs and bullet points. Be direct about what actually matters.

The manager's season-long goal is explicit and singular: finish the season with a
higher total than their tracked rival (the benchmark in this data). Every
recommendation you make should be judged against that goal, not just this week
in isolation.

Here is this week's data as JSON:
{json.dumps(context, indent=2)}

You have been given FOUR separate strategy profiles (template, differential,
aggressive, conservative), each with their own transfer and chip suggestion
computed independently. Your job is NOT to just report all four -- it's to reason
across them and commit to ONE recommendation, the way a single decisive analyst
would.

To decide, weigh:
- Trend direction: is the gap to the rival closing or widening across recent
  gameweeks (see points_trend)? If widening, favor the more aggressive or
  differential options -- protecting a lead that doesn't exist yet is the wrong
  instinct. If the gap is small or closing, a safer template/conservative move
  that avoids unforced errors may serve the season target better.
- Chips already used (see chips_used) -- never recommend a chip that's already
  been played this season. If unsure how many of each chip remain available
  under the current season's rules, use web search to check rather than assume.
- Squad health -- use web search for any current injury/rotation news on flagged
  players (squad_status_flags) or on players mentioned in the transfer options,
  beyond your training data cutoff.
- Hit cost discipline -- a -4 hit needs to clearly pay for itself against the
  season target, not just this week's fixture.

Write a briefing with these sections:
1. Where you stand -- one or two sentences on the trend (closing/widening), not
   just this week's score.
2. Squad health -- flag any real injury/rotation risk found via web search.
3. The one transfer to make this week -- name it explicitly (or say "bank it"),
   and explain briefly why it beats the other profiles' suggestions for the
   season-long goal specifically, not just this gameweek.
4. The one chip call -- same treatment, or explicitly say "hold all chips" if
   nothing clears the bar and none should be forced.
5. Your captain pick -- from captain_options, name who to captain this week and
   why, weighing their projected_ev against fixture and rotation risk. If the
   safest, highest-owned pick and the highest-ceiling differential pick genuinely
   differ, say so briefly rather than picking without acknowledging the trade-off.

Keep the whole thing under 250 words. Do not repeat the raw numbers already in
the charts the manager will see alongside this text -- interpret them, don't
restate them."""

    payload = {
        "model": MODEL,
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise ClaudeAPIError(f"Network error reaching the Claude API: {e}")

    if response.status_code == 401:
        raise ClaudeAPIError(
            "Authentication failed (401) -- the API key was rejected. "
            "Double-check it's copied correctly and hasn't been revoked."
        )
    if response.status_code == 404:
        raise ClaudeAPIError(
            f"Model not found (404) -- '{MODEL}' may have been retired. "
            "Check console.anthropic.com/docs for the current model list."
        )
    if response.status_code == 429:
        raise ClaudeAPIError(
            "Rate limited (429) -- too many requests, or your account needs "
            "billing credit added. Check console.anthropic.com's usage page."
        )
    if response.status_code >= 400:
        # Surface the real body instead of a generic message -- this is what
        # actually tells us what went wrong.
        raise ClaudeAPIError(
            f"Claude API returned HTTP {response.status_code}. Response body: "
            f"{response.text[:500]}"
        )

    data = response.json()
    text = _extract_text(data.get("content", []))
    if not text:
        raise ClaudeAPIError(
            f"Got a 200 response but no text content back. Raw response: "
            f"{json.dumps(data)[:500]}"
        )
    return text
