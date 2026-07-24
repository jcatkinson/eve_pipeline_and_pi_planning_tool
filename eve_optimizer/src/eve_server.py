# DEPRECATED — use src.core.esi_client instead.
# This shim preserves backward compatibility for scripts using the old import path.
from src.core.esi_client import *  # noqa: F401, F403
from src.core.esi_client import ESIClient, CorpWalletClient, decode_sso_token  # noqa: F401
