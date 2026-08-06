"""SSO policy for the Bitovi fork.

Upstream enforces a 5-user non-premium SSO limit. Bitovi disables that gate.
Keep the call site in ui_sso / enterprise endpoints as a one-liner so syncs
re-introduce the upstream check behind this policy instead of deleting blocks.
"""


def should_enforce_non_premium_sso_user_limit() -> bool:
    """Return True to keep upstream's non-premium SSO user cap.

    Bitovi always returns False so SSO works for the whole org without
    ``LITELLM_LICENSE``.
    """
    return False
