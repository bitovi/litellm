# Bitovi dashboard notes

React lives under `ui/litellm-dashboard/`. Prefer:

- `src/components/bitovi/` for new panels
- `src/components/UsagePage/` for usage / my-budgets (mounted from `app/(dashboard)/usage/page.tsx`)
- `src/components/key_team_helpers/ModelMaxBudget*` for per-model budget UI

Do not grow Bitovi features under `app/(dashboard)/usage/_components/` (stale upstream colocation; see README there).
