"""
Centralized settings, shared across all pages.

Persistence strategy: values live in st.session_state (so navigating between
pages in the same session never re-asks), and are mirrored into the URL's
query params (so bookmarking/home-screening the page -- with settings
already applied -- survives closing and reopening the app, since Streamlit
Cloud has no safe server-side file storage on a shared instance).

FPL login was attempted here previously but has been REVERTED: the
reverse-engineered endpoint it depended on (users.premierleague.com) no
longer exists -- confirmed dead even from a normal browser, not a Streamlit
Cloud network restriction. FPL has moved to a different, currently
undocumented login system. Everything below runs on public-data estimates
and the manual free-transfer override instead. See fpl_auth.py's docstring
for the history if this is ever revisited with a correct current endpoint.

Usage in any page:
    from settings import get_settings, settings_sidebar
    settings_sidebar()          # renders the shared inputs once
    cfg = get_settings()        # dict: team_id, rival_id, rival_mode, ft_override,
                                 #       is_logged_in (always False), free_transfers,
                                 #       bank, chips_used, live_picks (all None), auth_error
"""

import streamlit as st

DEFAULTS = {
    "team_id": "3486295",
    "rival_id": "7491201",
    "rival_mode": "Season-long (beat their cumulative total)",
    "ft_override_enabled": False,
    "ft_override_value": 1,
}

RIVAL_MODES = [
    "Season-long (beat their cumulative total)",
    "Head-to-head (beat them this gameweek only)",
]


def _init_from_query_params():
    """On first load of a session, seed session_state from the URL if present,
    else from Secrets (the true "set once" layer), else hardcoded defaults.
    Only runs once per session. Uses `or` rather than dict.get's default arg
    throughout, so an empty string (present but blank) falls through to the
    real default instead of silently sticking as "" -- that gap was exactly
    what caused team_id to go blank on some page navigations."""
    if st.session_state.get("_settings_initialized"):
        return
    qp = st.query_params
    st.session_state["team_id"] = qp.get("team_id") or st.secrets.get("DEFAULT_TEAM_ID") or DEFAULTS["team_id"]
    st.session_state["rival_id"] = qp.get("rival_id") or st.secrets.get("DEFAULT_RIVAL_ID") or DEFAULTS["rival_id"]
    st.session_state["rival_mode"] = qp.get("rival_mode") or DEFAULTS["rival_mode"]
    st.session_state["ft_override_enabled"] = qp.get("ft_override_enabled", "0") == "1"
    st.session_state["ft_override_value"] = int(qp.get("ft_override_value") or DEFAULTS["ft_override_value"])
    st.session_state["_settings_initialized"] = True


def _sync_query_params():
    st.query_params["team_id"] = st.session_state["team_id"]
    st.query_params["rival_id"] = st.session_state["rival_id"]
    st.query_params["rival_mode"] = st.session_state["rival_mode"]
    st.query_params["ft_override_enabled"] = "1" if st.session_state["ft_override_enabled"] else "0"
    st.query_params["ft_override_value"] = str(st.session_state["ft_override_value"])


def settings_sidebar():
    """Renders the shared settings controls in the sidebar. Call this once
    at the top of every page, before reading get_settings()."""
    _init_from_query_params()

    with st.sidebar:
        st.header("Settings")
        st.text_input("Your FPL team ID", key="team_id")
        st.text_input("Rival team ID (your benchmark)", key="rival_id")
        st.radio("Rival objective", RIVAL_MODES, key="rival_mode")

        # Guard against a blank value sticking (e.g. from a dropped query
        # string on page navigation) -- restore the default rather than
        # let every other page fail the numeric-ID check.
        if not st.session_state["team_id"].strip():
            st.session_state["team_id"] = st.secrets.get("DEFAULT_TEAM_ID") or DEFAULTS["team_id"]
        if not st.session_state["rival_id"].strip():
            st.session_state["rival_id"] = st.secrets.get("DEFAULT_RIVAL_ID") or DEFAULTS["rival_id"]

        st.divider()

        # FPL login is not currently viable: the reverse-engineered endpoint
        # this was built against (users.premierleague.com) no longer exists --
        # FPL has moved to a different, undocumented login system since. Not
        # attempting it any more here avoids a wasted, always-failing network
        # call on every single page load. Everything runs on public-data
        # estimates instead. See fpl_auth.py's docstring for the history if
        # this is ever revisited with a correct current endpoint.
        st.caption(
            "Live FPL login isn't currently available (the endpoint this was built "
            "against has been retired by FPL). Free transfers are estimated below -- "
            "override if it looks wrong."
        )
        st.session_state["_live_fpl_state"] = None
        st.session_state["_live_fpl_error"] = None

        st.divider()
        st.checkbox("Override estimated free transfers", key="ft_override_enabled")
        if st.session_state["ft_override_enabled"]:
            st.number_input(
                "Free transfers available", min_value=0, max_value=5, key="ft_override_value"
            )

        st.divider()
        if st.button("Save as home screen link", use_container_width=True):
            _sync_query_params()
            st.success(
                "Settings saved to the URL. Now bookmark this page / re-add it to "
                "your home screen so the saved link carries these settings forward."
            )

    _sync_query_params()


def get_settings():
    """Returns the current settings as a plain dict for use in page logic."""
    live = st.session_state.get("_live_fpl_state")
    return {
        "team_id": st.session_state.get("team_id") or DEFAULTS["team_id"],
        "rival_id": st.session_state.get("rival_id") or DEFAULTS["rival_id"],
        "rival_mode": st.session_state.get("rival_mode") or DEFAULTS["rival_mode"],
        "ft_override": (
            st.session_state.get("ft_override_value")
            if st.session_state.get("ft_override_enabled") else None
        ),
        "is_logged_in": live is not None,
        "free_transfers": live["free_transfers"] if live else None,
        "bank": live["bank"] if live else None,
        "chips_used": live["chips_used"] if live else None,
        "live_picks": live["picks"] if live else None,
        "auth_error": st.session_state.get("_live_fpl_error"),
    }
