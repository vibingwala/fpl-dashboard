"""
Calls the Claude API to generate the narrative analysis: performance review,
structural comparison to the rival, and a final judgment call on top of the
deterministic transfer/chip suggestions (folding in live news via web search).
"""

import json
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def _extract_text(content_blocks):
    return "\n".join(b["text"] for b in content_blocks if b.get("type") == "text")


def generate_weekly_analysis(api_key, context: dict) -> str:
    """
    context should include: my_team_name, my_total, rival_total, my_gw_history,
    rival_gw_history, squad_summary, rival_squad_summary (if available),
    transfer_suggestions (by profile), chip_suggestions (by profile), gameweek.
    Returns a plain-text/markdown narrative ready to drop into the email.
    """
    prompt = f"""You are a sharp, concise FPL (Fantasy Premier League) analyst writing a
weekly briefing for a manager who is a mathematician and dislikes walls of text.
Use short paragraphs and bullet points. Be direct about what actually matters.

Here is this week's data as JSON:
{json.dumps(context, indent=2)}

Write a briefing with these sections:
1. **Performance vs rank 1** — one or two sentences, structural not just score-based.
2. **Squad health** — flag any injury/rotation risk using current news (use web search
   for anything post your training data, e.g. press conference team news for this gameweek).
3. **Transfer verdict** — given the four profiles' suggestions already computed, tell the
   manager which single profile's suggestion you'd actually make this week and why,
   or say clearly if banking the transfer is better than all four options.
4. **Chip verdict** — same treatment for chip timing.

Keep the whole thing under 250 words. Do not repeat the raw numbers already in the
charts the manager will see alongside this text — interpret them, don't restate them."""

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

    response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return _extract_text(data.get("content", []))
