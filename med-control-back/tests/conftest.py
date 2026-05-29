"""
Test configuration.

Provides a lightweight stub for the `supabase` package so tests can import
core modules (scheduler, tools) without a live Supabase installation.
The stub is only installed when the real package is absent, so tests still
work normally in environments where supabase is installed.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock


def _install_supabase_stub() -> None:
    """Insert minimal supabase stubs into sys.modules."""
    if "supabase" in sys.modules:
        return  # real package present — nothing to do

    # Top-level package
    supabase_mod = types.ModuleType("supabase")

    # supabase._async.client — what supabase_client.py imports
    async_pkg = types.ModuleType("supabase._async")
    async_client_mod = types.ModuleType("supabase._async.client")
    async_client_mod.AsyncClient = MagicMock()
    async_client_mod.create_client = AsyncMock(return_value=MagicMock())

    supabase_mod.create_client = async_client_mod.create_client
    supabase_mod.Client = MagicMock()

    sys.modules["supabase"] = supabase_mod
    sys.modules["supabase._async"] = async_pkg
    sys.modules["supabase._async.client"] = async_client_mod


_install_supabase_stub()
