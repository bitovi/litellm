"""Premium / Enterprise license policy for the Bitovi fork.

Upstream gates management features (including key/team ``guardrails``) behind
``premium_user``, which is set from ``LITELLM_LICENSE``. Bitovi unlocks that
flag so platform features work without purchasing a LiteLLM Enterprise key.

Keep call sites as one-liners through ``resolve_premium_user`` so weekly syncs
re-introduce upstream license assignment behind this policy.
"""


def is_premium_unlocked() -> bool:
    """Return True when the Bitovi fork should treat the proxy as premium.

    Enables Enterprise-gated features we run on the platform (guardrails /
    Headroom, policies, tags, etc.) without ``LITELLM_LICENSE``.
    """
    return True


def resolve_premium_user(license_says_premium: bool) -> bool:
    """Map LicenseCheck.is_premium() to the effective premium_user flag."""
    if is_premium_unlocked():
        return True
    return license_says_premium
