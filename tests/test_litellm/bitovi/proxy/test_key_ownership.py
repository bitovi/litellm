from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from litellm.proxy._types import GenerateKeyRequest
from litellm_bitovi.proxy.key_hooks.ownership import apply_user_team_id_from_membership


@pytest.mark.asyncio
async def test_apply_user_team_id_from_single_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    data = GenerateKeyRequest(user_id="u1")
    mock_user = MagicMock()
    mock_user.teams = ["team-only"]

    mock_repo = MagicMock()
    mock_repo.return_value.table.find_unique = AsyncMock(return_value=mock_user)
    monkeypatch.setattr(
        "litellm_bitovi.proxy.key_hooks.ownership.UserRepository",
        mock_repo,
    )

    await apply_user_team_id_from_membership(data=data, prisma_client=MagicMock())
    assert data.team_id == "team-only"


@pytest.mark.asyncio
async def test_apply_user_team_id_rejects_multiple_memberships(monkeypatch: pytest.MonkeyPatch) -> None:
    data = GenerateKeyRequest(user_id="u1")
    mock_user = MagicMock()
    mock_user.teams = ["team-a", "team-b"]

    mock_repo = MagicMock()
    mock_repo.return_value.table.find_unique = AsyncMock(return_value=mock_user)
    monkeypatch.setattr(
        "litellm_bitovi.proxy.key_hooks.ownership.UserRepository",
        mock_repo,
    )

    with pytest.raises(HTTPException) as exc:
        await apply_user_team_id_from_membership(data=data, prisma_client=MagicMock())
    assert exc.value.status_code == 400
    assert "multiple teams" in str(exc.value.detail)
