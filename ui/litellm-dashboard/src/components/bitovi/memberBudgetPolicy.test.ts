import { describe, expect, it } from "vitest";

import { computeEffectiveMemberBudget } from "./memberBudgetPolicy";

describe("computeEffectiveMemberBudget", () => {
  it("uses team default alone", () => {
    const result = computeEffectiveMemberBudget(100, {});
    expect(result.effectiveMax).toBe(100);
    expect(result.usingTeamDefaultBase).toBe(true);
  });

  it("applies recurring and temp additives", () => {
    const result = computeEffectiveMemberBudget(100, {
      recurring_additive: 100,
      temp_additive: 50,
    });
    expect(result.effectiveMax).toBe(250);
    expect(result.tempActive).toBe(true);
  });

  it("clears expired temp", () => {
    const result = computeEffectiveMemberBudget(
      100,
      {
        recurring_additive: 100,
        temp_additive: 50,
        temp_expires_at: "2020-01-01T00:00:00Z",
      },
      new Date("2026-07-22T00:00:00Z"),
    );
    expect(result.effectiveMax).toBe(200);
    expect(result.tempActive).toBe(false);
  });

  it("uses permanent base instead of team default", () => {
    const result = computeEffectiveMemberBudget(150, {
      permanent_max_budget: 80,
      recurring_additive: 100,
    });
    expect(result.base).toBe(80);
    expect(result.effectiveMax).toBe(180);
    expect(result.usingTeamDefaultBase).toBe(false);
  });
});
