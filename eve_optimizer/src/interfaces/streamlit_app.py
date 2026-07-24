"""
src/interfaces/streamlit_app.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Streamlit web frontend for the EVE PI Profit Engine.

Run locally:
    streamlit run src/interfaces/streamlit_app.py

Architecture:
  - EVE SSO is the only authentication method (no email/password)
  - Session tokens are persisted in Supabase sessions table (24h TTL)
  - The active character's skill levels drive ProfitEngine calculations
  - Three subscription tiers: free (2 chars), premium (10), corporate (unlimited)
  - Payment verification polls the Moonpack Associates corp wallet on demand

Pages / panels:
  login_page()         — SSO login link + ?code= callback handler
  dashboard()          — main authenticated view
    _sidebar_authenticated() — char switcher, tier status, upgrade CTA, logout
    character_panel()  — add/remove alts, SSO flow for alts
    upgrade_panel()    — tier comparison, payment instructions, check payment
    analysis_panel()   — PI profit table with per-char skill levels
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# IMPORTANT: inject Streamlit secrets into os.environ BEFORE any other
# import so that src/config.py (which reads os.environ) gets the real values
# on Streamlit Community Cloud and in local dev with .streamlit/secrets.toml.
# ---------------------------------------------------------------------------
import os

try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for _k, _v in st.secrets.items():
            # Only inject flat string values — nested TOML sections are dicts
            if isinstance(_v, str):
                os.environ.setdefault(_k, _v)
except Exception:
    pass  # st not available yet (e.g. during pytest import)

# ---------------------------------------------------------------------------
# Now safe to import Streamlit fully and load the rest of the app
# ---------------------------------------------------------------------------
import time
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

# Load .env for local development (no-op if vars already set via secrets above)
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env")

# ---------------------------------------------------------------------------
# Page config — must be the FIRST st.* call after import
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="EVE PI Profit Engine",
    page_icon="🪐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Core imports — wrapped so the app shows a friendly error if misconfigured
# ---------------------------------------------------------------------------
try:
    from src.config import (
        CORP_API_CHARACTER_ID,
        CORP_PAYMENT_AMOUNT_CORPORATE,
        CORP_PAYMENT_AMOUNT_PREMIUM,
        MOONPACK_CORP_ID,
        PLANET_TYPES,
        SUPABASE_URL,
        TIER_CHAR_LIMITS,
        TRANSPORT_RISK_FACTOR,
    )
    from src.core.database_client import get_admin_db
    from src.core.esi_client import (
        CorpWalletClient,
        ESIClient,
        character_id_from_token,
        character_name_from_token,
    )
    from src.core.payment_verifier import PaymentVerifier, VerificationResult
    from src.core.profit_engine import ProfitEngine
    from src.core.user_service import CharacterLimitError, UserService, is_admin
    from src.utils.helpers import format_isk

    _CONFIG_OK = bool(SUPABASE_URL)
    _cfg_err_msg = ""
except Exception as _cfg_err:
    _CONFIG_OK = False
    _cfg_err_msg = str(_cfg_err)


# ---------------------------------------------------------------------------
# Admin session helper
# ---------------------------------------------------------------------------

def _apply_admin_override(user: "User") -> None:
    """If *user* is the app owner, force session tier to 'admin' (in-memory only)."""
    try:
        if is_admin(user):
            st.session_state["tier"] = "admin"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tier display helpers
# ---------------------------------------------------------------------------

_TIER_BADGE = {
    "free":      "FREE",
    "premium":   "⭐ PREMIUM",
    "corporate": "🏢 CORPORATE",
    "admin":     "🔑 ADMIN",
}

_TIER_COLOUR = {
    "free":      "#6b7280",
    "premium":   "#d97706",
    "corporate": "#7c3aed",
    "admin":     "#dc2626",
}


def _tier_badge(tier: str) -> str:
    return _TIER_BADGE.get(tier, tier.upper())


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _get_user_service() -> "UserService":
    return UserService(get_admin_db())


def _is_authenticated() -> bool:
    return bool(st.session_state.get("user_id"))


def _logout() -> None:
    token = st.session_state.get("session_token")
    if token:
        try:
            _get_user_service().delete_session(token)
        except Exception:
            pass
    for key in ["user_id", "character_id", "character_name", "session_token",
                "active_character_id", "tier"]:
        st.session_state.pop(key, None)
    st.rerun()


# ---------------------------------------------------------------------------
# Session restoration on page load
# ---------------------------------------------------------------------------

def _restore_session() -> None:
    """Try to restore a previously authenticated session from session_state."""
    if _is_authenticated():
        return  # already loaded this run

    token = st.session_state.get("session_token")
    if not token:
        return

    try:
        svc = _get_user_service()
        user_id = svc.validate_session(token)
        if not user_id:
            st.session_state.pop("session_token", None)
            return

        user = svc.get_user_by_id(user_id)
        if not user:
            return

        st.session_state["user_id"]            = user.id
        st.session_state["character_id"]       = user.character_id
        st.session_state["character_name"]     = user.character_name
        st.session_state["tier"]               = user.tier
        _apply_admin_override(user)
        if "active_character_id" not in st.session_state:
            st.session_state["active_character_id"] = user.character_id
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SSO callback handler
# ---------------------------------------------------------------------------

def _handle_sso_callback(code: str, state: str) -> None:
    """
    Exchange the OAuth code for tokens, extract character info from the JWT,
    upsert the user/character in Supabase, and create a session.
    """
    svc = _get_user_service()

    try:
        esi = ESIClient()
        payload = esi.exchange_code(code)
        access_token  = payload["access_token"]
        refresh_token = payload.get("refresh_token", "")
        expires_in    = payload.get("expires_in", 1200)
        token_expiry  = time.time() + expires_in - 60

        char_id   = character_id_from_token(access_token)
        char_name = character_name_from_token(access_token)

        if state == "add_character":
            # Adding an alt — user must already be logged in
            user_id = st.session_state.get("user_id")
            if not user_id:
                st.error("Session expired. Please log in again before adding a character.")
                return
            try:
                svc.add_character(
                    user_id=user_id,
                    character_id=char_id,
                    character_name=char_name,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expiry=token_expiry,
                )
                st.success(f"✅ Character **{char_name}** added successfully.")
            except CharacterLimitError as e:
                st.warning(str(e))
            except ValueError as e:
                st.info(str(e))  # already linked
        else:
            # Primary login
            user = svc.get_or_create_user(char_id, char_name)

            # Update primary character tokens
            svc.update_character_tokens(char_id, access_token, refresh_token, token_expiry)

            # Create session
            session_token = svc.create_session(user.id)

            st.session_state["user_id"]             = user.id
            st.session_state["character_id"]        = char_id
            st.session_state["character_name"]      = char_name
            st.session_state["session_token"]       = session_token
            st.session_state["tier"]                = user.tier
            _apply_admin_override(user)
            st.session_state["active_character_id"] = char_id

        # Expire stale subscriptions on login (lightweight check)
        svc.expire_subscriptions()

        # Clear query params and rerun to clean the URL
        st.query_params.clear()
        st.rerun()

    except Exception as e:
        st.error(f"Authentication failed: {e}")


# ---------------------------------------------------------------------------
# Cached engine runner — defined at module level so @st.cache_data is only
# registered once, not re-registered on every Streamlit rerun.
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner="Fetching market prices...")
def _cached_run_engine(
    char_id: int,
    access_token: str,
    refresh_token: str,
    token_expiry: float,
    accounting: int,
    broker: int,
    min_tier: int,
    planet_filter: tuple,
    top_n: int,
    poco_tax: float,
) -> list:
    esi = ESIClient(
        character_id=char_id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
    )
    engine = ProfitEngine(
        esi_client=esi,
        accounting_level=accounting,
        broker_relations_level=broker,
        planet_type_filter=list(planet_filter) if planet_filter else None,
        transport_risk_factor=TRANSPORT_RISK_FACTOR,
        poco_tax=poco_tax,
    )
    results = engine.run(min_tier=min_tier)
    if top_n:
        results = results[:top_n]
    return results


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def login_page() -> None:
    """Unauthenticated landing page with EVE SSO login."""
    st.title("🪐 EVE PI Profit Engine")
    st.markdown("---")

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown(
            "### Multi-character PI profit analysis\n"
            "Analyse sell-raw vs. manufacture decisions across all your PI characters, "
            "with real-time Jita market pricing and skill-adjusted margins.\n\n"
            "**Free tier**: 2 characters  \n"
            "**Premium** (500M ISK/yr): up to 10 characters  \n"
            "**Corporate** (1B ISK/yr): unlimited characters"
        )
    with col2:
        st.markdown("### Sign in")
        auth_url = ESIClient.build_auth_url(state="login")
        st.link_button("🔐 Login with EVE Online", auth_url, use_container_width=True)
        st.caption("We only request read-only scopes. We never read your mail or assets.")


def _sidebar_authenticated() -> str:
    """Render the authenticated sidebar and return the selected nav page."""
    svc = _get_user_service()

    user_id   = st.session_state["user_id"]
    char_name = st.session_state.get("character_name", "Unknown")
    tier      = st.session_state.get("tier", "free")

    st.sidebar.markdown(f"### {char_name}")
    badge_colour = _TIER_COLOUR.get(tier, "#6b7280")
    st.sidebar.markdown(
        f'<span style="background:{badge_colour};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:12px;font-weight:600">{_tier_badge(tier)}</span>',
        unsafe_allow_html=True,
    )

    # Days remaining for paid tiers
    if tier in ("premium", "corporate"):
        sub = svc.get_active_subscription(user_id)
        if sub:
            days = sub.days_remaining
            if days <= 30:
                st.sidebar.warning(f"⏳ {days} days remaining")
            else:
                st.sidebar.info(f"✅ {days} days remaining")
        else:
            # Sub expired between page loads — reset to free and rerun
            svc.expire_subscriptions()
            st.session_state["tier"] = "free"
            st.rerun()

    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "Navigate",
        ["📊 PI Analysis", "👥 Characters", "⭐ Upgrade"],
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        _logout()

    return page  # type: ignore[return-value]


def character_panel() -> None:
    """Character management panel — add/remove alts."""
    svc     = _get_user_service()
    user_id = st.session_state["user_id"]
    tier    = st.session_state.get("tier", "free")

    st.header("👥 Character Management")

    characters = svc.get_characters(user_id)
    active_id  = st.session_state.get("active_character_id")

    st.subheader("Your Characters")
    for char in characters:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            label = f"**{char.character_name}**"
            if char.is_primary:
                label += " *(Primary)*"
            st.markdown(label)
        with col2:
            if st.button("Set Active", key=f"active_{char.character_id}",
                         disabled=(char.character_id == active_id)):
                st.session_state["active_character_id"] = char.character_id
                st.rerun()
        with col3:
            if not char.is_primary:
                if st.button("Remove", key=f"remove_{char.character_id}", type="secondary"):
                    svc.remove_character(user_id, char.character_id)
                    if active_id == char.character_id:
                        st.session_state["active_character_id"] = st.session_state["character_id"]
                    st.rerun()

    st.markdown("---")

    # Add character
    limit    = TIER_CHAR_LIMITS.get(tier)
    at_limit = (limit is not None) and (len(characters) >= limit) and tier != "admin"

    st.subheader("Add Character")
    if at_limit:
        limit_msg = {
            "free":    "Free tier allows 2 characters. Upgrade to **Premium** for up to 10.",
            "premium": "Premium tier allows 10 characters. Upgrade to **Corporate** for unlimited.",
        }.get(tier, "Upgrade to add more characters.")
        st.warning(f"🚫 Character limit reached. {limit_msg}")
        if st.button("⭐ View Upgrade Options"):
            st.session_state["_nav"] = "⭐ Upgrade"
            st.rerun()
    else:
        remaining = (limit - len(characters)) if limit else "unlimited"
        st.caption(
            f"Slots used: {len(characters)} / {'∞' if limit is None else limit}"
            f"  ({remaining} remaining)"
        )
        add_url = ESIClient.build_auth_url(state="add_character")
        st.link_button("➕ Add EVE Character via SSO", add_url, use_container_width=True)
        st.caption("You'll be asked to log in as the alt character in the EVE SSO window.")


def upgrade_panel() -> None:
    """Premium upgrade flow — tier comparison, payment instructions, check payment."""
    svc     = _get_user_service()
    user_id = st.session_state["user_id"]
    char_id = st.session_state.get("active_character_id") or st.session_state["character_id"]
    tier    = st.session_state.get("tier", "free")

    st.header("⭐ Upgrade Your Plan")

    # If already on a paid tier, just show current status
    if tier == "admin":
        st.success("🔑 You are the admin — no payment required.")
        return

    if tier != "free":
        sub = svc.get_active_subscription(user_id)
        if sub:
            st.success(
                f"✅ You have an active **{_tier_badge(tier)}** subscription — "
                f"**{sub.days_remaining} days** remaining (expires {sub.expires_at[:10]})."
            )
            return

    # Tier comparison
    st.subheader("Plans")
    col_free, col_premium, col_corp = st.columns(3)
    with col_free:
        st.markdown(
            "#### FREE\n"
            "- 2 characters\n"
            "- Full PI analysis\n"
            "- ∞ market refreshes\n\n"
            "**0 ISK / year**"
        )
    with col_premium:
        st.markdown(
            "#### ⭐ PREMIUM\n"
            "- 10 characters\n"
            "- Full PI analysis\n"
            "- Priority support\n\n"
            f"**{CORP_PAYMENT_AMOUNT_PREMIUM // 1_000_000:,}M ISK / year**"
        )
    with col_corp:
        st.markdown(
            "#### 🏢 CORPORATE\n"
            "- Unlimited characters\n"
            "- Full PI analysis\n"
            "- Priority support\n\n"
            f"**{CORP_PAYMENT_AMOUNT_CORPORATE // 1_000_000_000:,}B ISK / year**"
        )

    st.markdown("---")

    with st.expander("💰 How to Pay", expanded=True):
        st.markdown(
            "1. Log into **EVE Online** with the character you want to pay from\n"
            "2. Open your **Wallet** → **Transfer ISK**\n"
            "3. **Recipient**: `Moonpack Associates` *(corporation)*\n"
            f"4. **Premium amount**: `{CORP_PAYMENT_AMOUNT_PREMIUM:,} ISK`\n"
            f"5. **Corporate amount**: `{CORP_PAYMENT_AMOUNT_CORPORATE:,} ISK`\n"
            "6. The **character name** you pay from is used for automatic verification — "
            "make sure it is one of your linked characters listed on the Characters page.\n"
            "7. After sending, click **Check My Payment** below."
        )

    st.markdown("---")

    st.subheader("Check My Payment")
    st.caption(
        f"Checking for a payment from character ID **{char_id}**. "
        "If you paid from a different character, switch to that character first."
    )

    if st.button("🔍 Check My Payment", type="primary", use_container_width=True):
        with st.spinner("Checking Moonpack Associates wallet..."):
            result = _run_payment_check(user_id, char_id)

        if result == VerificationResult.GRANTED:
            st.success("🎉 Payment verified! Your subscription has been activated.")
            user = svc.get_user_by_id(user_id)
            if user:
                st.session_state["tier"] = user.tier
            st.rerun()
        elif result == VerificationResult.ALREADY_ACTIVE:
            st.info("ℹ️ You already have an active subscription.")
        elif result == VerificationResult.DUPLICATE:
            st.info("ℹ️ This payment has already been processed.")
        elif result == VerificationResult.NOT_FOUND:
            st.warning(
                "⏳ No qualifying payment found in the recent wallet journal. "
                "Transfers can take a few minutes to appear — please try again shortly."
            )
        else:
            st.error("⚠️ Verification failed due to an unexpected error. Please try again.")


def _run_payment_check(user_id: str, character_id: int) -> "VerificationResult":
    """Instantiate CorpWalletClient and PaymentVerifier, then run check()."""
    try:
        svc = _get_user_service()

        corp_char = svc.get_character(CORP_API_CHARACTER_ID)
        if corp_char is None or not corp_char.access_token:
            st.error(
                "Corp API character not configured. "
                "Please contact the administrator to set up the corp wallet connection."
            )
            return VerificationResult.ERROR

        wallet = CorpWalletClient(
            access_token=corp_char.access_token,
            refresh_token=corp_char.refresh_token or "",
            token_expiry=corp_char.token_expiry or 0.0,
        )
        verifier = PaymentVerifier(corp_wallet=wallet, user_service=svc)
        return verifier.check(user_id=user_id, character_id=character_id)

    except Exception as e:
        st.error(f"Payment check error: {e}")
        return VerificationResult.ERROR


def analysis_panel() -> None:
    """PI profit analysis panel — the core engine output as an interactive table."""
    import pandas as pd

    svc            = _get_user_service()
    user_id        = st.session_state["user_id"]
    active_char_id = st.session_state.get("active_character_id") or st.session_state["character_id"]

    char      = svc.get_character(active_char_id)
    char_name = char.character_name if char else "Unknown"

    st.header(f"📊 PI Profit Analysis — {char_name}")

    # --- Sidebar filters ---
    with st.sidebar:
        st.markdown("#### Analysis Filters")
        min_tier     = st.selectbox("Minimum Tier", [1, 2, 3, 4], index=2)
        planet_filter = st.multiselect("Planet Types", PLANET_TYPES, default=[])
        top_n        = st.number_input("Top N Results", min_value=1, max_value=200, value=20)
        # Slider value is 0–25 (whole %) displayed as percent; divide by 100 for engine
        poco_pct     = st.slider("POCO Tax %", min_value=0, max_value=25, value=5, step=1,
                                 help="Planetary Customs Office export tax rate")
        poco_tax     = poco_pct / 100.0
        refresh      = st.button("🔄 Refresh Market Data", use_container_width=True)

    if refresh:
        st.cache_data.clear()

    if not char or not char.access_token:
        st.warning(
            "This character has no stored ESI tokens. "
            "Please remove and re-add the character to refresh authorisation."
        )
        return

    with st.spinner("Loading PI chain data..."):
        try:
            results = _cached_run_engine(
                char_id=active_char_id,
                access_token=char.access_token,
                refresh_token=char.refresh_token or "",
                token_expiry=char.token_expiry or 0.0,
                accounting=char.accounting_level,
                broker=char.broker_level,
                min_tier=min_tier,
                planet_filter=tuple(planet_filter),
                top_n=int(top_n),
                poco_tax=poco_tax,
            )
        except Exception as e:
            st.error(f"Failed to load market data: {e}")
            return

    if not results:
        st.info("No chains matched the current filters.")
        return

    # --- Build DataFrame ---
    rows = []
    for r in results:
        raw_missing  = any(inp.price_source == "none" for inp in r.inputs)
        raw_history  = any(inp.price_source == "history" for inp in r.inputs)
        proc_missing = r.output_price_source == "none"
        proc_history = r.output_price_source == "history"
        rows.append({
            "Tier":           f"P{r.output_tier}",
            "Product":        r.output_name,
            "Planets":        ", ".join(r.planet_types),
            "Sell Raw (net)": r.sell_raw_net_isk,
            "Process (net)":  r.process_net_isk,
            "Delta":          r.delta_isk,
            "ISK/m³ (in)":    r.input_isk_per_m3,
            "ISK/m³ (out)":   r.output_isk_per_m3,
            "Action":         "✔ PROCESS" if r.recommendation == "PROCESS & MANUFACTURE" else "SELL RAW",
            "_raw_missing":   raw_missing,
            "_raw_history":   raw_history,
            "_proc_missing":  proc_missing,
            "_proc_history":  proc_history,
        })

    df         = pd.DataFrame(rows)
    isk_cols   = ["Sell Raw (net)", "Process (net)", "Delta", "ISK/m³ (in)", "ISK/m³ (out)"]
    display_df = df.drop(columns=["_raw_missing", "_raw_history", "_proc_missing", "_proc_history"]).copy()

    for col in isk_cols:
        display_df[col] = display_df[col].apply(format_isk)

    # --- Conditional row highlighting via Styler on the raw-values df ---
    def _highlight(row: "pd.Series") -> list[str]:
        styles  = [""] * len(row)
        cols    = df.columns.tolist()
        delta_i = cols.index("Delta")
        raw_i   = cols.index("Sell Raw (net)")
        proc_i  = cols.index("Process (net)")

        if row["Delta"] > 0:
            styles[delta_i] = "color: #16a34a; font-weight: 600"
        elif row["Delta"] < 0:
            styles[delta_i] = "color: #dc2626; font-weight: 600"
        if row["_raw_missing"]:
            styles[raw_i] = "background-color: #fef3c7"
        elif row["_raw_history"]:
            styles[raw_i] = "background-color: #eff6ff"   # light blue = history estimate
        if row["_proc_missing"]:
            styles[proc_i] = "background-color: #fef3c7"
        elif row["_proc_history"]:
            styles[proc_i] = "background-color: #eff6ff"
        return styles

    styled = (
        df.style
        .apply(_highlight, axis=1)
        .format({c: format_isk for c in isk_cols})
        .hide(axis="index")
    )

    # --- Summary metrics ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Chains shown", len(results))
    m2.metric("Best delta", format_isk(results[0].delta_isk))
    m3.metric("POCO Tax", f"{poco_tax:.0%}")
    m4.metric(
        "Tax + Broker",
        f"{results[0].applied_sales_tax + results[0].applied_broker_fee:.2%}",
    )

    st.dataframe(styled, use_container_width=True)

    missing_count = sum(
        1 for r in results
        if any(i.price_source == "none" for i in r.inputs) or r.output_price_source == "none"
    )
    history_count = sum(
        1 for r in results
        if any(i.price_source == "history" for i in r.inputs) or r.output_price_source == "history"
    )
    if missing_count:
        st.caption(
            f"⚠ {missing_count} chain(s) have items with no orders and no history — "
            "ISK shown as 0. Highlighted in amber."
        )
    if history_count:
        st.caption(
            f"🔵 {history_count} chain(s) have items priced from 5-day market history "
            "(no live sell orders). Highlighted in blue."
        )


def dashboard() -> None:
    """Main authenticated dashboard — sidebar nav routes between panels."""
    try:
        svc  = _get_user_service()
        svc.expire_subscriptions()
        user = svc.get_user_by_id(st.session_state["user_id"])
        # Never let the DB value overwrite an in-memory "admin" override
        if user and st.session_state.get("tier") != "admin" and user.tier != st.session_state.get("tier"):
            st.session_state["tier"] = user.tier
    except Exception:
        pass

    page = _sidebar_authenticated()
    nav  = st.session_state.pop("_nav", None) or page

    if nav == "📊 PI Analysis":
        analysis_panel()
    elif nav == "👥 Characters":
        character_panel()
    elif nav == "⭐ Upgrade":
        upgrade_panel()


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    if not _CONFIG_OK:
        st.error(
            "⚠️ Configuration error — Supabase credentials are not set. "
            f"Detail: {_cfg_err_msg}\n\n"
            "Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to `.streamlit/secrets.toml` "
            "or your environment variables."
        )
        st.stop()

    # Handle OAuth callback from EVE SSO redirect
    params = st.query_params
    if "code" in params:
        _handle_sso_callback(
            code=params["code"],
            state=params.get("state", "login"),
        )
        return

    # Try to restore an existing session
    _restore_session()

    if _is_authenticated():
        dashboard()
    else:
        login_page()


if __name__ == "__main__":
    main()
