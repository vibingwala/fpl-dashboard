"""
FPL login, using the same (unofficial, community-reverse-engineered) flow the
official mobile app itself uses. There is no official public login API --
this POSTs credentials to FPL's real login endpoint and reuses the resulting
session cookie. It can break if FPL changes their login flow without notice.

Once logged in, /api/my-team/{id}/ returns AUTHORITATIVE data your own public
API calls cannot get: exact free transfers remaining, which chips are already
used, and your live provisional squad for the upcoming (not yet locked)
gameweek -- replacing the estimates used elsewhere in this app.
"""

import requests

LOGIN_URL = "https://users.premierleague.com/accounts/login/"
MY_TEAM_URL = "https://fantasy.premierleague.com/api/my-team/{team_id}/"


class FPLLoginError(Exception):
    pass


def login(email: str, password: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    payload = {
        "login": email,
        "password": password,
        "app": "plfpl-web",
        "redirect_uri": "https://fantasy.premierleague.com/",
    }
    try:
        response = session.post(LOGIN_URL, data=payload, allow_redirects=True, timeout=15)
    except requests.RequestException as e:
        raise FPLLoginError(
            f"Couldn't reach FPL's login page (network error: {e}). This may be "
            f"transient -- try again in a moment. If it keeps happening, FPL may be "
            f"blocking Streamlit Cloud's outbound requests, or their login endpoint "
            f"has changed."
        )

    # A failed login redirects back to a page containing an error state;
    # a successful one lands on fantasy.premierleague.com with auth cookies set.
    if "pl_profile" not in session.cookies.get_dict() or "login" in response.url:
        raise FPLLoginError(
            "FPL login failed -- check the email/password in Secrets are correct. "
            "If they are, FPL may have changed their login flow since this was written."
        )
    return session


def get_my_team(session: requests.Session, team_id: int) -> dict:
    try:
        response = session.get(MY_TEAM_URL.format(team_id=team_id), timeout=15)
    except requests.RequestException as e:
        raise FPLLoginError(f"Network error fetching my-team: {e}")
    if response.status_code == 403:
        raise FPLLoginError(
            "Got a 403 fetching my-team -- the session may have expired, or this "
            "team ID doesn't belong to the logged-in account (my-team only works "
            "for your OWN team, not a rival's)."
        )
    response.raise_for_status()
    return response.json()


def extract_authoritative_state(my_team_data: dict) -> dict:
    """Pulls out exactly the facts that were previously estimated elsewhere:
    free transfers, bank, and which chips are already used."""
    transfers = my_team_data.get("transfers", {})
    chips = my_team_data.get("chips", [])
    return {
        "free_transfers": transfers.get("limit"),
        "bank": (transfers.get("bank") or 0) / 10,
        "chips_used": [c["name"] for c in chips if c.get("status") == "played"],
        "picks": my_team_data.get("picks", []),
    }


TRANSFERS_URL = "https://fantasy.premierleague.com/api/transfers/"


def submit_transfers(session: requests.Session, team_id: int, event_id: int,
                      transfers: list, chip: str = None, dry_run: bool = True) -> dict:
    """
    M7 -- executes a real transfer via FPL's transfer-submission endpoint.

    ** THIS IS UNOFFICIAL AND UNDOCUMENTED. ** The payload shape below is
    reconstructed from community reverse-engineering (last publicly
    confirmed ~2021-2025 era), not from any FPL-published spec. It can
    silently stop working if FPL changes their internal API, and there is
    NO UNDO once a real (non-dry-run) submission succeeds.

    transfers: list of {"element_in": id, "element_out": id,
                         "purchase_price": price_in_tenths,
                         "selling_price": price_in_tenths}
    chip: FPL's internal chip code (e.g. "3xc", "bboost", "freehit",
          "wildcard") or None.
    dry_run: when True (the default, and it should stay the default unless
             the caller has an explicit, deliberate reason not to), this
             builds and returns the exact payload WITHOUT sending it --
             for review before ever risking a real submission.
    """
    payload = {
        "transfers": transfers,
        "chip": chip,
        "entry": str(team_id),
        "event": event_id,
    }

    if dry_run:
        return {"dry_run": True, "payload": payload, "submitted": False}

    headers = {
        "content-type": "application/json",
        "origin": "https://fantasy.premierleague.com",
        "referer": "https://fantasy.premierleague.com/transfers",
    }
    response = session.post(TRANSFERS_URL, json=payload, headers=headers, timeout=20)

    if response.status_code not in (200, 201):
        raise FPLLoginError(
            f"Transfer submission failed ({response.status_code}): {response.text[:400]}. "
            f"Nothing should have changed on your FPL team if this failed, but verify "
            f"manually in the app before assuming that."
        )

    try:
        result = response.json()
    except ValueError:
        result = {}
    return {"dry_run": False, "payload": payload, "submitted": True, "response": result}
