# Admin Tier Plan

## Overview

Add a hidden "admin" tier for the owner (EVE character ID `ADMIN_CHARACTER_ID). Any character
linked under that owner's Supabase account inherits admin status automatically.

**Key design decisions:**
- The `"admin"` tier is **never persisted to Supabase** — it is an in-memory overlay
  applied at login and session restore. This means `expire_subscriptions()` can never
  strip it, and ordinary users can never observe or obtain it.
- The owner is identified by their **primary EVE character ID** (`ADMIN_CHARACTER_ID`
  env var). Any alts linked under the same Supabase `user_id` inherit the tier.
- The Upgrade panel shows a friendly "Admin — no payment needed" message instead of
  the payment flow.
- Character limit is treated as unlimited (same as corporate).

---

## Sub-Tasks

### Sub-Task 1 — Add `ADMIN_CHARACTER_ID` to config
**Status:** [ ] pending

**Intent:** Expose the admin character ID as a typed constant loaded from the
environment, consistent with how all other secrets are handled in this codebase.

**Expected Outcomes:**
- `ADMIN_CHARACTER_ID` is readable from `src.config`
- `.env.example` documents the variable
- Default is `0` (disabled) when not set

**Todo List:**
1. Add `ADMIN_CHARACTER_ID: int = int(os.environ.get("ADMIN_CHARACTER_ID", "0"))` to
   `src/config.py` (below the existing `CHARACTER_ID` line)
2. Add `ADMIN_CHARACTER_ID=ADMIN_CHARACTER_ID` to `.env` (the real secrets file, not committed)
3. Add `ADMIN_CHARACTER_ID=0  # owner's primary EVE character ID` to `.env.example`

**Relevant Context:**
- `src/config.py` — pattern matches `CHARACTER_ID` line exactly

---

### Sub-Task 2 — Admin detection helper in `UserService`
**Status:** [ ] pending

**Intent:** Centralise the "is this user the admin?" check in one place so the
Streamlit app never duplicates the logic.

**Expected Outcomes:**
- `UserService.is_admin(user: User) -> bool` returns `True` iff
  `user.character_id == ADMIN_CHARACTER_ID` and `ADMIN_CHARACTER_ID != 0`
- `TIER_CHAR_LIMITS` and `expire_subscriptions` are not changed (admin is never in DB)

**Todo List:**
1. Import `ADMIN_CHARACTER_ID` at the top of `src/core/user_service.py`
2. Add a module-level `is_admin(user: User) -> bool` function (or a `UserService`
   staticmethod — keep it a standalone function since it does not need DB access)

**Relevant Context:**
- `src/core/user_service.py` — imports `TIER_CHAR_LIMITS` from `src.config`; same
  pattern for the new import

---

### Sub-Task 3 — Inject admin tier at login and session restore
**Status:** [ ] pending

**Intent:** Force `st.session_state["tier"] = "admin"` whenever the admin owner logs
in or restores a session, so every page already sees the correct tier without touching
Supabase.

**Expected Outcomes:**
- After SSO login as `ADMIN_CHARACTER_ID`, `session_state["tier"] == "admin"`
- After page-reload (session restore via `_restore_session`), tier is still `"admin"`
- `dashboard()` sync block does not overwrite `"admin"` with the DB value `"free"`
- No DB write is made changing the user's tier to `"admin"`

**Todo List:**
1. In `_handle_sso_callback` (primary login branch), after setting
   `st.session_state["tier"] = user.tier`, call a helper `_apply_admin_override(user)`
   that overwrites tier to `"admin"` if `is_admin(user)` is true.
2. In `_restore_session`, after `st.session_state["tier"] = user.tier`, apply the
   same `_apply_admin_override(user)` call.
3. In `dashboard()` sync block, guard the tier re-sync with:
   `if user and user.tier != st.session_state.get("tier") and st.session_state.get("tier") != "admin"`
   so the admin tier is never overwritten by the DB value on rerun.
4. Add `_apply_admin_override(user: User) -> None` as a module-level helper that sets
   `st.session_state["tier"] = "admin"` when `is_admin(user)`.

**Relevant Context:**
- `streamlit_app.py` lines 174, 237, 692-693 — the three places tier is written from
  the DB into session state

---

### Sub-Task 4 — `expire_subscriptions` guard
**Status:** [ ] pending

**Intent:** Prevent `expire_subscriptions()` from downgrading the admin user's DB row
(even though admin tier is not stored, the DB tier starts as `"free"` and we don't
want spurious writes touching the admin row).

**Expected Outcomes:**
- `expire_subscriptions()` skips any user whose `character_id == ADMIN_CHARACTER_ID`
- All existing subscription-expiry tests still pass

**Todo List:**
1. In `UserService.expire_subscriptions()`, after fetching expired rows, skip any
   `row["user_id"]` whose user record has `character_id == ADMIN_CHARACTER_ID`.
   Simplest approach: fetch the admin user's `user_id` from DB once at the top of
   the method and exclude it from the loop.

**Relevant Context:**
- `src/core/user_service.py` lines 371-397 — `expire_subscriptions` implementation

---

### Sub-Task 5 — UI changes for admin tier
**Status:** [ ] pending

**Intent:** Admin users should see a distinctive badge, no subscription expiry warning,
no character limit enforcement, and a friendly "Admin" message on the Upgrade page
instead of the payment flow.

**Expected Outcomes:**
- Sidebar shows a red "🔑 ADMIN" badge
- No "days remaining" block rendered for admin
- Character panel treats admin as unlimited (no "at limit" warning)
- Upgrade panel shows "🔑 You are the admin — no payment required." and returns early
- `_tier_badge("admin")` returns `"🔑 ADMIN"`

**Todo List:**
1. Add `"admin": "🔑 ADMIN"` to `_TIER_BADGE` dict
2. Add `"admin": "#dc2626"` (red) to `_TIER_COLOUR` dict
3. In `_sidebar_authenticated()`, extend the `if tier in ("premium", "corporate"):` guard
   to exclude `"admin"` (i.e. `if tier in ("premium", "corporate"):` stays as-is — admin
   is simply not in the set, so the block is already skipped)
4. In `character_panel()`, update the `at_limit` check so admin is treated as unlimited:
   `at_limit = (limit is not None) and (len(characters) >= limit) and tier != "admin"`
5. In `upgrade_panel()`, add an early-return block at the top:
   `if tier == "admin": st.success("🔑 You are the admin — no payment required."); return`

**Relevant Context:**
- `streamlit_app.py` lines 105-119 — badge/colour dicts and `_tier_badge`
- `streamlit_app.py` lines 331-344 — subscription days block (already skips non-paid tiers)
- `streamlit_app.py` lines 395-408 — `at_limit` logic in character panel
- `streamlit_app.py` lines 425-437 — early-return in upgrade panel for paid tiers

---

### Sub-Task 6 — Tests
**Status:** [ ] pending

**Intent:** Verify the admin detection logic and the session-state override without
touching the DB.

**Expected Outcomes:**
- `is_admin` returns `True` for the admin character, `False` for others
- When `ADMIN_CHARACTER_ID` is `0`, `is_admin` always returns `False`
- `expire_subscriptions` does not reset the admin user's tier

**Todo List:**
1. Add `TestAdminTier` class to `tests/test_main.py` with:
   - `test_is_admin_true` — patches `ADMIN_CHARACTER_ID` to `999`, creates a User with
     `character_id=999`, asserts `is_admin(user)` is `True`
   - `test_is_admin_false` — same setup but user has different character_id, asserts `False`
   - `test_is_admin_disabled_when_zero` — patches `ADMIN_CHARACTER_ID` to `0`, asserts
     always `False`

**Relevant Context:**
- `tests/test_main.py` — all existing tests use `patch` for isolation; same pattern here
- `src/core/user_service.py` — `is_admin` is the only new symbol needing tests
