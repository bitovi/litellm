"""Enterprise SSO seat display is covered by premium unlock; do not re-patch enterprise/.

Upstream ``available_enterprise_users`` injects ``max_users=5`` only when
``not premium_user`` and SSO is configured. Bitovi ``resolve_premium_user`` keeps
``premium_user`` True, so that branch never runs. The enterprise file must stay
upstream-identical (no ``litellm_bitovi`` import).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from litellm.proxy import proxy_server as proxy_server_module
from litellm_bitovi.proxy.license.policy import resolve_premium_user
from litellm_enterprise.proxy.management_endpoints.internal_user_endpoints import router

_ENTERPRISE_INTERNAL_USER_ENDPOINTS = (
    Path(__file__).resolve().parents[4]
    / "enterprise"
    / "litellm_enterprise"
    / "proxy"
    / "management_endpoints"
    / "internal_user_endpoints.py"
)


def test_enterprise_internal_user_endpoints_has_no_bitovi_import() -> None:
    source = _ENTERPRISE_INTERNAL_USER_ENDPOINTS.read_text(encoding="utf-8")
    assert "litellm_bitovi" not in source
    assert "should_enforce_non_premium_sso_user_limit" not in source


def test_premium_unlock_makes_enterprise_sso_seat_branch_unreachable() -> None:
    assert resolve_premium_user(False) is True
    assert proxy_server_module._resolve_premium_user(False) is True


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _user_count(total: int, deactivated: int = 0):
    async def _count(*args, where=None, **kwargs):
        return deactivated if where is not None else total

    return _count


@pytest.mark.asyncio
async def test_available_users_skips_sso_five_seat_cap_when_premium_unlocked(
    client: TestClient,
) -> None:
    mock_prisma = MagicMock()
    mock_prisma.db.litellm_usertable.count = _user_count(12)
    mock_prisma.db.litellm_teamtable.count = AsyncMock(return_value=1)

    with (
        patch("litellm.proxy.proxy_server.prisma_client", mock_prisma),
        patch(
            "litellm.proxy.proxy_server.premium_user",
            proxy_server_module._resolve_premium_user(False),
        ),
        patch("litellm.proxy.proxy_server.premium_user_data", None),
        patch(
            "litellm.proxy.auth.auth_utils._has_user_setup_sso",
            return_value=True,
        ),
        patch(
            "litellm_enterprise.proxy.management_endpoints.internal_user_endpoints.user_api_key_auth",
            return_value={"user_id": "test_user", "api_key": "test_key"},
        ),
    ):
        response = client.get("/user/available_users")

    assert response.status_code == 200
    data = response.json()
    assert data["total_users"] is None
    assert data["total_users_remaining"] is None
    assert data["total_users_used"] == 12
