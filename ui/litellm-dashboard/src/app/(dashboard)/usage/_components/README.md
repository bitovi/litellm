# Stale upstream Usage colocation

Upstream moved Usage under `app/(dashboard)/usage/_components/`. Bitovi's live
route mounts `@/components/UsagePage` instead (my-budgets and related).

Do not add Bitovi features here. Prefer `src/components/UsagePage/` or
`src/components/bitovi/`. This tree may be deleted once sync noise drops.
