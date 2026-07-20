"""Regression: Bitovi unlocks Enterprise guardrails without LITELLM_LICENSE.

Upstream `_premium_user_check("guardrails")` 403s when `premium_user` is False.
The Bitovi license policy forces premium via `resolve_premium_user`, wired into
`proxy_server.premium_user`. This test fails if that seam is removed.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from litellm.proxy import proxy_server as proxy_server_module
from litellm.proxy.utils import _premium_user_check
from litellm_bitovi.proxy.license.policy import is_premium_unlocked, resolve_premium_user


def test_bitovi_unlocks_premium_without_license() -> None:
    assert is_premium_unlocked() is True
    assert resolve_premium_user(False) is True
    assert resolve_premium_user(True) is True


def test_proxy_server_premium_user_uses_bitovi_resolve() -> None:
    assert callable(proxy_server_module._resolve_premium_user)
    assert proxy_server_module._resolve_premium_user(False) is True
    assert proxy_server_module.premium_user is True


def test_premium_user_check_allows_guardrails_when_license_is_false() -> None:
    unlocked = proxy_server_module._resolve_premium_user(False)
    assert unlocked is True
    with patch.object(proxy_server_module, "premium_user", unlocked):
        _premium_user_check("guardrails")


def test_premium_user_check_still_blocks_when_premium_user_is_false() -> None:
    with patch.object(proxy_server_module, "premium_user", False):
        with pytest.raises(HTTPException) as exc_info:
            _premium_user_check("guardrails")
    assert exc_info.value.status_code == 403
    assert "guardrails" in str(exc_info.value.detail)
