/** Mirrors litellm_bitovi.proxy.config_teams.member_budget_policy */

export type BitoviMemberBudgetPolicy = {
  permanent_max_budget?: number | null;
  recurring_additive?: number | null;
  temp_additive?: number | null;
  temp_expires_at?: string | null;
};

export type EffectiveMemberBudget = {
  teamDefault: number | null;
  base: number | null;
  recurringAdditive: number;
  tempAdditive: number;
  effectiveMax: number | null;
  usingTeamDefaultBase: boolean;
  tempActive: boolean;
};

export function parseMemberBudgetPolicy(
  metadata: Record<string, unknown> | null | undefined,
): BitoviMemberBudgetPolicy {
  if (!metadata || typeof metadata !== "object") return {};
  const raw = metadata.bitovi_budget_policy;
  if (!raw || typeof raw !== "object") return {};
  return raw as BitoviMemberBudgetPolicy;
}

export function computeEffectiveMemberBudget(
  teamDefault: number | null | undefined,
  policy: BitoviMemberBudgetPolicy,
  now: Date = new Date(),
): EffectiveMemberBudget {
  const permanent =
    typeof policy.permanent_max_budget === "number" && Number.isFinite(policy.permanent_max_budget)
      ? policy.permanent_max_budget
      : null;
  const recurring =
    typeof policy.recurring_additive === "number" &&
    Number.isFinite(policy.recurring_additive) &&
    policy.recurring_additive > 0
      ? policy.recurring_additive
      : 0;
  let temp = 0;
  let tempActive = false;
  if (
    typeof policy.temp_additive === "number" &&
    Number.isFinite(policy.temp_additive) &&
    policy.temp_additive > 0
  ) {
    const expiresAt = policy.temp_expires_at ? new Date(policy.temp_expires_at) : null;
    if (!expiresAt || Number.isNaN(expiresAt.getTime()) || expiresAt > now) {
      temp = policy.temp_additive;
      tempActive = true;
    }
  }

  const usingTeamDefaultBase = permanent === null;
  const base = usingTeamDefaultBase
    ? typeof teamDefault === "number" && Number.isFinite(teamDefault)
      ? teamDefault
      : null
    : permanent;

  if (base === null) {
    return {
      teamDefault: typeof teamDefault === "number" ? teamDefault : null,
      base: null,
      recurringAdditive: recurring,
      tempAdditive: temp,
      effectiveMax: null,
      usingTeamDefaultBase,
      tempActive,
    };
  }

  return {
    teamDefault: typeof teamDefault === "number" ? teamDefault : null,
    base,
    recurringAdditive: recurring,
    tempAdditive: temp,
    effectiveMax: base + recurring + temp,
    usingTeamDefaultBase,
    tempActive,
  };
}
