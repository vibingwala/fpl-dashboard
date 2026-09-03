# FPL squad view

A colorful pitch view of your Fantasy Premier League squad, pulling live data
directly from the official FPL API (no login required for team picks).

## Running this in PyCharm

1. Open this folder (`fpl_dashboard`) as a project in PyCharm.
2. Open the built-in terminal (View → Tool Windows → Terminal).
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run the app:
   ```
   streamlit run app.py
   ```
5. It will open in your browser automatically at `http://localhost:8501`.
   Leave the terminal running — closing it stops the app.

## Using it

- Enter your FPL team ID in the sidebar (defaults to yours: 3486295).
- The pitch shows your current gameweek's starting XI with team crests,
  price, and points. Captain (C) and vice-captain (V) are badged in orange
  and gray. A red "!" badge means the player has an injury/fitness flag.
- Bench players are listed in a strip below the pitch.
- Data refreshes automatically once an hour (player data) or every 10
  minutes (your picks/live scores) — restart the app to force an immediate
  refresh.

## Transfers and chips page

Once the app is running, use the sidebar page picker to open
"Transfers and chips". It shows four tabs — template, differential,
aggressive, conservative — each with its own transfer suggestions and chip
timing call, all respecting your actual bank balance and free transfers.

**Important caveat on free transfers:** FPL's public API doesn't expose your
real free-transfer count (only the authenticated in-app view does). This
page estimates it from your transfer history using the standard rules
(+1 per week, capped at 5, chip weeks exempt). If it's ever wrong, check the
"Override estimated free transfers" box in the sidebar and enter the real
number — every recommendation depends on this being right, so don't skip
correcting it if it drifts.

**Known simplification:** blank/double gameweek detection for the Free Hit
recommendation isn't wired up yet (it's hardcoded off) — that needs parsing
the fixtures list for weeks where teams play 0 or 2 games, which is planned
for the next iteration.

## Agent briefing page

A third page, "Agent Briefing," brings the standalone email agent's AI
analysis into the app itself. It only unlocks within a configurable window
before the deadline (default 24 hours) -- outside that window it just shows
a countdown, since the underlying Claude API call has a real cost and isn't
useful far out from the deadline anyway.

**Setting your API key:** paste it into the sidebar for a quick local test,
or -- better, especially once this is deployed publicly on Streamlit
Cloud -- set `ANTHROPIC_API_KEY` in the app's Secrets (Settings -> Secrets
in the Streamlit Cloud dashboard). See `.streamlit/secrets.toml.example`.
Never commit a real key to the GitHub repo.

**Cost control:** generating (or regenerating) the briefing requires an
explicit button click -- it does not fire automatically on page load or on
every rerun, and the result is cached per gameweek for your session so
navigating around the app doesn't trigger repeat paid calls.

**Note:** the email agent (in the separate `fpl_agent` project) still runs
independently on its own schedule -- this page doesn't replace it, it's an
additional on-demand way to see the same kind of analysis.

## What's next

Planned next: real blank/double gameweek detection for Free Hit timing,
shared across both the app and the standalone agent.
