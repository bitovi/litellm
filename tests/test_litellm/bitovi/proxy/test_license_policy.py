from litellm_bitovi.proxy.license.policy import is_premium_unlocked, resolve_premium_user


def test_bitovi_unlocks_premium_without_license() -> None:
    assert is_premium_unlocked() is True
    assert resolve_premium_user(False) is True
    assert resolve_premium_user(True) is True
