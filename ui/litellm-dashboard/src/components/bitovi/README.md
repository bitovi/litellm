# Bitovi UI mount notes

Put new Bitovi dashboard panels under this folder (or the existing owned
folders listed in `bitovi/litellm_bitovi/README.md`). Mount them from upstream
pages with a short import only.

Live usage page entry: `app/(dashboard)/usage/page.tsx` ->
`@/components/UsagePage/components/UsagePageView`.

Headroom savings:

- `HeadroomCompressionPanel.tsx` — mounted from Logs `LogDetailContent`
- `HeadroomSavingsView.tsx` — mounted from Usage view `headroom`

Key cycle budgets:

- `KeyCycleBudgetsView.tsx` — mounted from Usage view `key-budgets`

Member budget policy (config teams):

- `MemberBudgetPolicyForm.tsx` — mounted from Team edit-member modal when `is_from_config`
