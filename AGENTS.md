Read @CLAUDE.md for coding guidelines

# Bitovi fork override (wins over CLAUDE.md)

**DO NOT COMMIT OR PUSH.** Never `git commit`, `git push`, or open a PR unless the user explicitly asks in the current message. Leave changes for the user to review

## Default: write Bitovi features in `litellm_bitovi`

Prefer `bitovi/litellm_bitovi/` (proxy/auth/budget/SSO/observability) and `ui/litellm-dashboard/src/components/bitovi/` (dashboard). Wire upstream with a thin seam only (config hook, one-line call-out, or `app.include_router(...)`). Do not grow logic in `litellm/proxy/proxy_server.py` or other high-churn upstream files when an owned module can hold it. Tests: `tests/test_litellm/bitovi/`

Also see [FORK.md](FORK.md), [bitovi/litellm_bitovi/README.md](bitovi/litellm_bitovi/README.md), and `.cursor/rules/litellm-bitovi-thin-layer.mdc`
