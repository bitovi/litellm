# Bitovi LiteLLM Fork

**Agents: DO NOT COMMIT OR PUSH** unless the user explicitly asks in the current message. See `AGENTS.md` and `.cursor/rules/no-auto-git.mdc`

Bitovi fork of [BerriAI/litellm](https://github.com/BerriAI/litellm). We keep upstream LiteLLM stable releases while carrying Bitovi-specific features and platform deploy config.

Related ops docs: [DEPLOYMENT.md](DEPLOYMENT.md), [DB_RESET.md](DB_RESET.md). Feature ownership package: [bitovi/litellm_bitovi/README.md](bitovi/litellm_bitovi/README.md)

## Local Docker (recommended for testing)

One command brings up proxy + Admin UI + Postgres + Redis with demo team budgets:

```bash
# optional: put OPENAI_API_KEY / ANTHROPIC_API_KEY in docker/local.env
cp docker/local.env.example docker/local.env
make local-up
```

Then:

- API + baked UI: http://localhost:4000/ui/ (login `admin` / `sk-1234`)
- UI hot-reload: http://localhost:3000 (Next.js; calls the proxy on :4000)
- Stop: `make local-down`

The theme / networking "Failed to fetch" error means only the Next.js UI is running without the proxy. Use `make local-up` instead of `npm run dev` alone

Config: `docker/local_ui_verify_config.yaml`. Details: [docker/README.md](docker/README.md). Includes an opt-in Headroom sidecar on `:8787` (`headroom-compression` guardrail)

## Remotes and branches

| Remote / branch | Purpose |
|-----------------|---------|
| `origin` | `https://github.com/bitovi/litellm.git` |
| `upstream` | `https://github.com/BerriAI/litellm.git` |
| `litellm_internal_staging` (ours) | Working base for all Bitovi work and PRs (our trunk) |
| BerriAI `litellm_internal_staging` | Their internal integration branch; **do not sync from it** (name collision is coincidental) |
| `upstream/main` | Their development tip (nightlies / `dev`); **do not sync from it** |

One-time setup:

```bash
git remote add upstream https://github.com/BerriAI/litellm.git
git fetch upstream --tags
```

## Compose vs fork (read this before changing code)

Upstream moves weekly. Bitovi features that **edit the same shared files** conflict forever. Features that **live in owned paths** and call into LiteLLM through thin seams usually merge cleanly.

```text
Upstream LiteLLM (moves fast)
        |
        |  thin seams (config hooks / one-line call-outs)
        v
bitovi/litellm_bitovi/  + owned UI folders  (edit freely; rarely conflict)
```

**Rename storms** (upstream moves a page tree) still hurt once; wrappers do not fix renames. They stop you from re-solving the same VK/budget hunks every tag.

### Where new code goes (agents: default here)

**Assume new Bitovi work belongs in `bitovi/litellm_bitovi/` first.** Treat edits to `proxy_server.py` and other shared LiteLLM modules as a last resort (thin call-out only)

1. Prefer `bitovi/litellm_bitovi/...` for proxy/auth/budget/SSO/observability logic
2. Prefer `ui/litellm-dashboard/src/components/bitovi/` or existing owned UI folders for dashboard panels
3. Wire with config hooks (`custom_key_generate`, `callbacks`, …) or a **short** call-out / `include_router` in an upstream file
4. Tests under `tests/test_litellm/bitovi/`
5. Only expand a shared upstream file when a seam is impossible; document why in the PR and update the seam table below

### Owned paths (low conflict)

| Area | Where |
|------|-------|
| Bitovi extension package | `bitovi/litellm_bitovi/**` |
| Config teams / YAML budgets | `bitovi/litellm_bitovi/proxy/config_teams/` (shims under old litellm paths) |
| VK ownership defaults | `bitovi/litellm_bitovi/proxy/key_hooks/` |
| Model budget windows | `bitovi/litellm_bitovi/proxy/budget/` |
| SSO user-cap policy | `bitovi/litellm_bitovi/proxy/sso/` |
| Premium / guardrails unlock | `bitovi/litellm_bitovi/proxy/license/` |
| Headroom savings observability | `bitovi/litellm_bitovi/proxy/headroom/` |
| Usage / my-budgets UI | `ui/litellm-dashboard/src/components/UsagePage/**` |
| Per-model budget UI | `ui/.../key_team_helpers/ModelMaxBudget*` |
| Platform deploy | `deploy/values.yaml`, `.github/workflows/publish-*.yml` |
| Fork CI / sync | `.github/workflows/fork-compatibility-check.yml`, `test.yml` |
| Mantle SigV4 delta | `litellm/llms/bedrock_mantle/common_utils.py` (provider itself is upstream; keep Bitovi `service_name`) |

### Intentional shared-file seams (keep short; ratchet down)

| Seam | Upstream call site | Owned module |
|------|--------------------|--------------|
| Config teams parse + sync | `litellm/proxy/proxy_server.py` | `litellm_bitovi.proxy.config_teams` |
| Config team locks | `team_endpoints.py` | same |
| Config team member budget inheritance | `team_endpoints.py`, `auth_checks.py` | `litellm_bitovi.proxy.config_teams.member_budget_inheritance` |
| Config team member budget policy API | `proxy_server.py` (`include_router`) | `litellm_bitovi.proxy.config_teams.endpoints` |
| VK auto-assign | `key_management_endpoints.py` | `litellm_bitovi.proxy.key_hooks` |
| Budget window helpers | `hooks/model_max_budget_limiter.py` | `litellm_bitovi.proxy.budget` |
| SSO 5-user gate (login path) | `ui_sso.py` only | `litellm_bitovi.proxy.sso.policy` |
| Premium unlock | `proxy_server.py` (`premium_user`) | `litellm_bitovi.proxy.license.policy` |

Enterprise `internal_user_endpoints.py` (`/user/available_users` SSO 5-seat display) stays **byte-identical to upstream**. Bitovi `resolve_premium_user` keeps `premium_user` True, so upstream's `if not premium_user:` seat injection never runs; do not re-patch that file.
| Headroom savings API mount | `proxy_server.py` (`include_router`) | `litellm_bitovi.proxy.headroom.endpoints` |
| Headroom savings record | `guardrail_hooks/headroom/headroom.py` (one call) | `litellm_bitovi.proxy.headroom.savings` |
| Redis datetime JSON | `redis_cache.py`, `cache_pydantic_utils.py` | keep tiny; prefer upstream PR |

`proxy_server.py` note: the bottom `app.include_router(...)` block churns whenever upstream adds a router. Bitovi lines there should stay **import + include only**. On sync conflicts in that block, keep **both** sides' router lines (upstream routers + Bitovi `bitovi_headroom_router` / any future Bitovi routers)

### Upstream PR candidates vs keep-fork-local

| Prefer upstreaming | Keep Bitovi-local |
|--------------------|-------------------|
| Mantle SigV4 `service_name` | Config teams YAML sync |
| Redis datetime cache serialization | Windowed model budgets, VK auto-assign |
| | SSO non-premium unlock, my-budgets UI |

## Sync source: stable tags only

Sync from the latest upstream **stable** git tag matching `^v[0-9]+\.[0-9]+\.[0-9]+$` (for example `v1.93.0`).

Do **not** sync from `upstream/main`, BerriAI’s `litellm_internal_staging`, or tags with `-dev` / `-rc` / `nightly`.

```bash
make fork-sync-status
```

## Day-to-day feature work

Branch from **current** `litellm_internal_staging`. Open PRs **into** `litellm_internal_staging`.

```bash
make fork-branch NAME=litellm_my_change
# implement under bitovi/litellm_bitovi or owned UI paths
# push, open PR with base litellm_internal_staging
```

Branch names: `litellm_<short_description>`, no `/` in the branch name.

## Upstream sync

### Automated (preferred)

`.github/workflows/fork-compatibility-check.yml` opens `sync/upstream-vX.Y.Z` PRs into `litellm_internal_staging` when a newer stable tag exists. It never merges for you.

**Merge the sync PR with a merge commit** (do not squash or rebase the sync PR). That preserves conflict resolution ancestry for the next tag.

### Junior review guide (sync PRs)

Do not merge while GitHub shows **This branch has conflicts that must be resolved**.

| Path pattern | Prefer |
|--------------|--------|
| `bitovi/**` | Bitovi |
| `litellm/llms/bedrock_mantle/**` | Bitovi (SigV4 contract) |
| `litellm/proxy/auth/**`, key/team/budget call-outs | Bitovi when both changed; read both sides |
| `litellm/proxy/proxy_server.py` (`include_router` / premium / config_teams seams) | Keep both router lines; keep Bitovi call-outs; prefer upstream for unrelated hunks |
| `tests/test_litellm/bitovi/**`, `tests/e2e/quota_management/budgets/**` | Bitovi |
| `ui/**/UsagePage/**`, `ui/**/bitovi/**`, `ModelMaxBudget*` | Bitovi |
| `deploy/**`, Bitovi `.github/workflows/publish-*.yml`, `test.yml`, `fork-compatibility-check.yml` | Bitovi |
| `ui/**/eslint-metrics.json`, `litellm/proxy/_experimental/out/**` | Upstream / regenerate |
| Everything else | Prefer upstream unless you know it is a Bitovi seam |

### Required: `FORK_SYNC_TOKEN`

See workflow comments; classic PAT with `repo` + `workflow` (or fine-grained Contents / PRs / Issues / Actions write). Optional: `SLACK_WEBHOOK_URL`.

### Manual fallback

```bash
git fetch upstream --tags
git checkout litellm_internal_staging
git pull origin litellm_internal_staging
git merge --no-ff vX.Y.Z
# resolve per table above
# smoke (below), then push
```

### Post-sync smoke

```bash
pytest tests/test_litellm/llms/bedrock_mantle/ -q
pytest tests/test_litellm/bitovi/ -q
pytest tests/test_litellm/proxy/common_utils/test_cache_codec.py -q  # if present
# optional: usage UI typecheck / vitest for UsagePage if UI conflicted
```

After sync lands: deploy via Bitovi publish/tag workflows.

## CI note

Bitovi does not run BerriAI’s full Actions set. Active workflows live under `.github/workflows/` (`test.yml`, publish, fork sync). Upstream copies may appear under `.github/workflows-backup/` and should not be adopted.

## Contribute back to BerriAI (rare)

```bash
make upstream-branch NAME=litellm_upstream_fix
```

Branch from clean `upstream/main` so the PR does not include Bitovi-only commits. Prefer upstreaming Mantle SigV4 and Redis datetime fixes when possible.
