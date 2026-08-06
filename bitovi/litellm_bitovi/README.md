# Bitovi LiteLLM extensions (`litellm_bitovi`)

Owned package for Bitovi fork behavior. **Agents and humans: default here.** Prefer
adding features in this package instead of editing upstream-shared LiteLLM files.
That keeps weekly stable-tag syncs cheaper and makes ownership obvious for new
maintainers.

Root guide: [`FORK.md`](../../FORK.md). Cursor rule: `.cursor/rules/litellm-bitovi-thin-layer.mdc`

## Layout

```text
litellm_bitovi/
  proxy/
    config_teams/   # declarative teams: YAML sync + budget locks
    key_hooks/      # VK auto-assign user/team on generate
    budget/         # calendar model-budget window helpers
    sso/            # non-premium SSO user-cap policy
    license/        # premium_user unlock (guardrails / Enterprise gates)
    headroom/       # compression savings metadata + aggregate API
  ui/               # docs for dashboard mount points (React stays under ui/)
```

## How to add a feature

1. Branch from `litellm_internal_staging` (`make fork-branch NAME=litellm_...`)
2. Put logic under `bitovi/litellm_bitovi/...`
3. Wire with the thinnest seam you can:
   - Config hooks: `general_settings.custom_key_generate`, `custom_auth`, `litellm_settings.callbacks`
   - One-line call-out from an upstream file into this package
   - UI: new components under `ui/litellm-dashboard/src/components/bitovi/` or an existing Bitovi-owned folder; mount with a short import
4. Tests under `tests/test_litellm/bitovi/`
5. In the PR, answer: did this avoid growing a high-churn upstream file?

## Do / don't

| Do | Don't |
|----|-------|
| New module in this package | Large edits to `proxy_server.py`, `team_endpoints.py`, shared Usage pages |
| Thin call-out + owned logic | Copy-paste upstream functions into fork forever |
| Regression tests that fail if the seam regresses | Fork upstream unit tests wholesale |

## Intentional seams (keep short)

| Seam | Location | Bitovi module |
|------|----------|---------------|
| Config teams parse + startup sync | `proxy_server.py` | `proxy.config_teams` |
| Config team budget locks | `team_endpoints.py` | `proxy.config_teams` |
| Config team member budget inheritance | `team_endpoints.py`, `auth_checks.py` | `proxy.config_teams.member_budget_inheritance` |
| Config team member budget policy API | `proxy_server.py` (`include_router`) | `proxy.config_teams.endpoints` |
| VK ownership defaults | `key_management_endpoints.py` | `proxy.key_hooks.ownership` |
| Model budget windows | `hooks/model_max_budget_limiter.py` | `proxy.budget.windows` |
| SSO 5-user gate (login path) | `ui_sso.py` only | `proxy.sso.policy` |
| Premium unlock (guardrails, etc.) | `proxy_server.py` (`premium_user`) | `proxy.license.policy` |

Enterprise `internal_user_endpoints.py` is not a Bitovi seam: keep it upstream-identical. Premium unlock already bypasses its `if not premium_user:` SSO seat display.
| Headroom savings API | `proxy_server.py` (`include_router` only) | `proxy.headroom.endpoints` |
| Headroom savings record | `headroom.py` one-line call + spend metadata field | `proxy.headroom.savings` |

Compatibility shims remain at the old import paths for config teams so gradual migrations do not break.

## UI

Dashboard React code stays under `ui/litellm-dashboard/`. Bitovi-owned panels:

- `src/components/UsagePage/` (my-budgets and related; mounted from `app/(dashboard)/usage/page.tsx`)
- `src/components/key_team_helpers/ModelMaxBudget*`
- `src/components/team/MyUserTab.tsx`
- Prefer new work under `src/components/bitovi/`
- Headroom: `HeadroomCompressionPanel` (Logs) + `HeadroomSavingsView` (Usage → Headroom Savings)

Do not grow features inside upstream-colocated trees under `app/(dashboard)/usage/_components/` (stale duplicate from upstream colocation).
