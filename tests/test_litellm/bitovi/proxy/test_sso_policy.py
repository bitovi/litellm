from litellm_bitovi.proxy.sso.policy import should_enforce_non_premium_sso_user_limit


def test_bitovi_disables_non_premium_sso_user_limit() -> None:
    assert should_enforce_non_premium_sso_user_limit() is False
