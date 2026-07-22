import { describe, expect, it } from "vitest";

import type { KeyResponse, Team } from "@/components/key_team_helpers/key_list";
import {
  buildTeamMemberBudgetContext,
  percentOfCycleBudget,
  resolveKeyCycleBudget,
  toKeyCycleBudgetRow,
} from "./KeyCycleBudgetsView";

function makeKey(overrides: Partial<KeyResponse> = {}): KeyResponse {
  return {
    token: "tok",
    token_id: "tid-1",
    key_name: "sk-...abc",
    key_alias: "alice-key",
    spend: 80,
    max_budget: 100,
    expires: "",
    models: [],
    aliases: {},
    config: {},
    user_id: "alice@bitovi.com",
    team_id: "team-1",
    project_id: null,
    max_parallel_requests: 0,
    metadata: {},
    tpm_limit: 0,
    rpm_limit: 0,
    duration: "",
    budget_duration: "30d",
    budget_reset_at: "2026-08-01T00:00:00Z",
    allowed_cache_controls: [],
    allowed_routes: [],
    permissions: {},
    model_spend: {},
    model_max_budget: {},
    soft_budget_cooldown: false,
    blocked: false,
    litellm_budget_table: {},
    organization_id: null,
    created_at: "",
    updated_at: "",
    last_active: null,
    team_spend: 0,
    team_alias: "Bitovi",
    team_tpm_limit: 0,
    team_rpm_limit: 0,
    team_max_budget: 0,
    team_models: [],
    team_blocked: false,
    soft_budget: 0,
    team_model_aliases: {},
    team_member_spend: 0,
    team_metadata: {},
    end_user_id: "",
    end_user_tpm_limit: 0,
    end_user_rpm_limit: 0,
    end_user_max_budget: 0,
    last_refreshed_at: 0,
    api_key: "",
    user_role: "user",
    rpm_limit_per_model: {},
    tpm_limit_per_model: {},
    user_tpm_limit: 0,
    user_rpm_limit: 0,
    user_email: "alice@bitovi.com",
    ...overrides,
  } as KeyResponse;
}

const teams: Team[] = [
  {
    team_id: "team-1",
    team_alias: "Bitovi",
    models: [],
    max_budget: 500,
    budget_duration: "30d",
    tpm_limit: null,
    rpm_limit: null,
    organization_id: "",
    created_at: "",
    keys: [],
    members_with_roles: [],
    spend: 0,
  },
];

describe("percentOfCycleBudget", () => {
  it("returns null when budget is missing or zero", () => {
    expect(percentOfCycleBudget(10, null)).toBeNull();
    expect(percentOfCycleBudget(10, 0)).toBeNull();
  });

  it("computes percent of current cycle", () => {
    expect(percentOfCycleBudget(80, 100)).toBe(80);
    expect(percentOfCycleBudget(100, 100)).toBe(100);
    expect(percentOfCycleBudget(120, 100)).toBe(120);
  });
});

describe("resolveKeyCycleBudget", () => {
  it("prefers key max_budget over team", () => {
    expect(resolveKeyCycleBudget(makeKey({ max_budget: 100 }), teams)).toMatchObject({
      budget: 100,
      budget_source: "key",
    });
  });

  it("falls back to team max_budget when key budget is unset and no member context", () => {
    expect(resolveKeyCycleBudget(makeKey({ max_budget: 0 }), teams)).toMatchObject({
      budget: 500,
      budget_source: "team",
    });
  });

  it("uses effective team member pool including temp boost", () => {
    const contexts = {
      "team-1": buildTeamMemberBudgetContext({
        team_info: {
          team_member_budget_table: {
            max_budget: 100,
            budget_duration: "30d",
            budget_reset_at: "2026-08-01T00:00:00Z",
          },
        },
        team_memberships: [
          {
            user_id: "alice@bitovi.com",
            spend: 12,
            metadata: {
              bitovi_budget_policy: {
                temp_additive: 50,
              },
            },
          },
        ],
      }),
    };
    const resolved = resolveKeyCycleBudget(
      makeKey({ max_budget: 0, team_max_budget: 0 }),
      teams.map((t) => ({ ...t, max_budget: null })),
      contexts,
    );
    expect(resolved).toMatchObject({
      budget: 150,
      budget_source: "member",
      budget_boost_label: "+$50 temp",
      spend: 12,
      budget_duration: "30d",
    });
  });
});

describe("toKeyCycleBudgetRow", () => {
  it("maps key fields and percent for the current cycle", () => {
    const row = toKeyCycleBudgetRow(makeKey({ spend: 80, max_budget: 100 }), teams);
    expect(row.key_alias).toBe("alice-key");
    expect(row.user_email).toBe("alice@bitovi.com");
    expect(row.spend).toBe(80);
    expect(row.budget).toBe(100);
    expect(row.percent_used).toBe(80);
    expect(row.budget_duration).toBe("30d");
  });
});
