"""
Centralized settings, shared across all pages.

Persistence strategy: values live in st.session_state (so navigating between
pages in the same session never re-asks), and are mirrored into the URL's
query params (so bookmarking/home-screening the page -- with settings
already applied -- survives closing and reopening the app, since Streamlit
Cloud has no safe server-side file storage on a shared instance).

If FPL_EMAIL and FPL_PASSWORD are set in Streamlit Secrets, this also handles
FPL login once per session and exposes AUTHORITATIVE free transfers, bank,
and chip usage (from the my-team endpoint) instead of estimates -- this is
the real fix for "the free transfer count is wrong", not just an override box.

Usage in any page:
    from settings import get_settings, settings_sidebar
    settings_sidebar()          # renders the shared inputs once
    cfg = get_settings()        # dict: team_id, rival_id, rival_mode, ft_override,
                                 #       is_logged_in, free_transfers, bank,
                                 #       chips_used, live_picks, auth_error
"""

import streamlit as st

from fpl_auth import login, get_my_team, extract_authoritative_state, FPLLoginError

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
    Only runs once per session."""
    if st.session_state.get("_settings_initialized"):
        return
    qp = st.query_params
    st.session_state["team_id"] = qp.get("team_id", st.secrets.get("DEFAULT_TEAM_ID", DEFAULTS["team_id"]))
    st.session_state["rival_id"] = qp.get("rival_id", st.secrets.get("DEFAULT_RIVAL_ID", DEFAULTS["rival_id"]))
    st.session_state["rival_mode"] = qp.get("rival_mode", DEFAULTS["rival_mode"])
    st.session_state["ft_override_enabled"] = qp.get("ft_override_enabled", "0") == "1"
    st.session_state["ft_override_value"] = int(qp.get("ft_override_value", DEFAULTS["ft_override_value"]))
    st.session_state["_settings_initialized"] = True


def _sync_query_params():
    st.query_params["team_id"] = st.session_state["team_id"]
    st.query_params["rival_id"] = st.session_state["rival_id"]
    st.query_params["rival_mode"] = st.session_state["rival_mode"]
    st.query_params["ft_override_enabled"] = "1" if st.session_state["ft_override_enabled"] else "0"
    st.query_params["ft_override_value"] = str(st.session_state["ft_override_value"])


def _try_login_and_fetch(team_id_str):
    """Logs in once per session (cached in session_state) and fetches
    my-team data fresh each call (cheap, no caching needed -- it's the
    whole point that this is live). Any failure here -- network, auth,
    or otherwise -- must NEVER crash the app; login is a nice-to-have
    enhancement, not something Squad View or Transfers should depend on."""
    fpl_email = st.secrets.get("FPL_EMAIL")
    fpl_password = st.secrets.get("FPL_PASSWORD")
    if not (fpl_email and fpl_password):
        return None, None

    if "fpl_session" not in st.session_state:
        try:
            st.session_state["fpl_session"] = login(fpl_email, fpl_password)
            st.session_state["fpl_auth_error"] = None
        except Exception as e:
            st.session_state["fpl_session"] = None
            st.session_state["fpl_auth_error"] = str(e)

    session = st.session_state.get("fpl_session")
    if not session or not team_id_str.strip().isdigit():
        return None, st.session_state.get("fpl_auth_error")

    try:
        my_team = get_my_team(session, int(team_id_str))
        return extract_authoritative_state(my_team), None
    except Exception as e:
        return None, str(e)


def settings_sidebar():
    """Renders the shared settings controls in the sidebar. Call this once
    at the top of every page, before reading get_settings()."""
    _init_from_query_params()

    with st.sidebar:
        st.header("Settings")
        st.text_input("Your FPL team ID", key="team_id")
        st.text_input("Rival team ID (your benchmark)", key="rival_id")
        st.radio("Rival objective", RIVAL_MODES, key="rival_mode")

        st.divider()

        live, auth_error = _try_login_and_fetch(st.session_state["team_id"])
        st.session_state["_live_fpl_state"] = live
        st.session_state["_live_fpl_error"] = auth_error

        if live:
            st.success(
                f"Logged in -- live data: {live['free_transfers']} FT, "
                f"£{live['bank']:.1f}m bank"
            )
        elif auth_error:
            st.warning(f"FPL login not working: {auth_error}")
            st.caption("Falling back to estimated free transfers below.")
        else:
            st.caption(
                "Add FPL_EMAIL and FPL_PASSWORD to Secrets for exact free "
                "transfers, bank, and chip usage instead of estimates."
            )

        if not live:
            st.divider()
            st.caption("Free transfers are estimated (the public API doesn't expose "
                       "this) -- override if it's wrong.")
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
        "team_id": st.session_state.get("team_id", DEFAULTS["team_id"]),
        "rival_id": st.session_state.get("rival_id", DEFAULTS["rival_id"]),
        "rival_mode": st.session_state.get("rival_mode", DEFAULTS["rival_mode"]),
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
