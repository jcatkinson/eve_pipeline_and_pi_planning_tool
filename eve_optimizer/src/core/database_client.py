"""
src/core/database_client.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Supabase client singletons for the EVE PI Profit Engine.

Two clients are exposed:
  get_db()       — anon/public client, safe for read operations in the UI
  get_admin_db() — service-role client, used server-side for all writes
                   (subscriptions, payments, session management)
                   NEVER expose the service-role key to the browser.

Both clients are module-level singletons — the first call initialises them,
subsequent calls return the cached instance.

Configuration is read from environment variables (or Streamlit secrets when
running on Streamlit Community Cloud). See src/config.py for variable names.
"""

from __future__ import annotations

from supabase import Client, create_client

from src.config import SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

_db: Client | None = None
_admin_db: Client | None = None


def get_db() -> Client:
    """
    Return the anon Supabase client (read-only, public-safe).

    Raises RuntimeError if SUPABASE_URL or SUPABASE_ANON_KEY are not set.
    """
    global _db
    if _db is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment "
                "or Streamlit secrets before calling get_db()."
            )
        _db = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _db


def get_admin_db() -> Client:
    """
    Return the service-role Supabase client (full read/write, server-side only).

    Raises RuntimeError if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY are not set.
    """
    global _admin_db
    if _admin_db is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment "
                "or Streamlit secrets before calling get_admin_db()."
            )
        _admin_db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _admin_db


def reset_clients() -> None:
    """
    Reset cached client singletons. Used in tests to inject fresh clients
    between test cases without module reload.
    """
    global _db, _admin_db
    _db = None
    _admin_db = None
