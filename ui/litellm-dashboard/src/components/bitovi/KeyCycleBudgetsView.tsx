import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Progress, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import { formatNumberWithCommas } from "@/utils/dataUtils";
import { keyListCall, teamInfoCall } from "@/components/networking";
import type { KeyResponse, Team } from "@/components/key_team_helpers/key_list";
import {
  computeEffectiveMemberBudget,
  parseMemberBudgetPolicy,
} from "@/components/bitovi/memberBudgetPolicy";

export type KeyCycleBudgetSource = "key" | "team" | "member" | "none";

export type KeyCycleBudgetRow = {
  token_id: string;
  key_alias: string;
  user_id: string;
  user_email: string;
  team_id: string | null;
  team_alias: string;
  spend: number;
  budget: number | null;
  budget_source: KeyCycleBudgetSource;
  budget_boost_label: string | null;
  budget_duration: string | null;
  budget_reset_at: string | null;
  percent_used: number | null;
};

export type TeamMemberBudgetContext = {
  teamDefault: number | null;
  budgetDuration: string | null;
  budgetResetAt: string | null;
  membershipsByUserId: Record<
    string,
    {
      metadata?: Record<string, unknown> | null;
      spend?: number | null;
    }
  >;
};

function boostLabelFromEffective(effective: {
  usingTeamDefaultBase: boolean;
  base: number | null;
  recurringAdditive: number;
  tempAdditive: number;
  tempActive: boolean;
}): string | null {
  const parts: string[] = [];
  if (!effective.usingTeamDefaultBase && effective.base != null) {
    parts.push(`perm $${formatNumberWithCommas(effective.base)}`);
  }
  if (effective.recurringAdditive > 0) {
    parts.push(`+$${formatNumberWithCommas(effective.recurringAdditive)} recurring`);
  }
  if (effective.tempActive && effective.tempAdditive > 0) {
    parts.push(`+$${formatNumberWithCommas(effective.tempAdditive)} temp`);
  }
  return parts.length > 0 ? parts.join(", ") : null;
}

export function buildTeamMemberBudgetContext(teamInfoResponse: {
  team_info?: {
    team_member_budget_table?: {
      max_budget?: number | null;
      budget_duration?: string | null;
      budget_reset_at?: string | null;
    } | null;
  };
  team_memberships?: Array<{
    user_id?: string;
    metadata?: Record<string, unknown> | null;
    spend?: number | null;
    litellm_budget_table?: {
      max_budget?: number | null;
      budget_duration?: string | null;
      budget_reset_at?: string | null;
    } | null;
  }>;
}): TeamMemberBudgetContext {
  const table = teamInfoResponse.team_info?.team_member_budget_table;
  const membershipsByUserId: TeamMemberBudgetContext["membershipsByUserId"] = {};
  for (const membership of teamInfoResponse.team_memberships ?? []) {
    if (!membership.user_id) continue;
    membershipsByUserId[membership.user_id] = {
      metadata: membership.metadata ?? null,
      spend: membership.spend ?? null,
    };
  }
  return {
    teamDefault: typeof table?.max_budget === "number" ? table.max_budget : null,
    budgetDuration: table?.budget_duration ?? null,
    budgetResetAt: table?.budget_reset_at ?? null,
    membershipsByUserId,
  };
}

export function resolveKeyCycleBudget(
  key: KeyResponse,
  teams: Team[],
  memberContexts: Record<string, TeamMemberBudgetContext> = {},
): {
  budget: number | null;
  budget_source: KeyCycleBudgetSource;
  budget_boost_label: string | null;
  budget_duration: string | null;
  budget_reset_at: string | null;
  spend: number;
} {
  const keyBudget = key.max_budget;
  if (typeof keyBudget === "number" && Number.isFinite(keyBudget) && keyBudget > 0) {
    const spend = typeof key.spend === "number" && Number.isFinite(key.spend) ? key.spend : 0;
    return {
      budget: keyBudget,
      budget_source: "key",
      budget_boost_label: null,
      budget_duration: key.budget_duration || null,
      budget_reset_at: key.budget_reset_at || null,
      spend,
    };
  }

  const teamId = key.team_id;
  if (typeof teamId === "string" && teamId) {
    const context = memberContexts[teamId];
    if (context) {
      const membership = key.user_id ? context.membershipsByUserId[key.user_id] : undefined;
      const policy = parseMemberBudgetPolicy(membership?.metadata ?? null);
      const effective = computeEffectiveMemberBudget(context.teamDefault, policy);
      if (effective.effectiveMax != null) {
        const memberSpend =
          typeof membership?.spend === "number" && Number.isFinite(membership.spend)
            ? membership.spend
            : typeof key.team_member_spend === "number" && Number.isFinite(key.team_member_spend)
              ? key.team_member_spend
              : typeof key.spend === "number" && Number.isFinite(key.spend)
                ? key.spend
                : 0;
        return {
          budget: effective.effectiveMax,
          budget_source: "member",
          budget_boost_label: boostLabelFromEffective(effective),
          budget_duration: context.budgetDuration,
          budget_reset_at: context.budgetResetAt,
          spend: memberSpend,
        };
      }
    }
  }

  const team = teams.find((t) => t.team_id === key.team_id);
  const teamBudget = team?.max_budget ?? key.team_max_budget;
  if (typeof teamBudget === "number" && Number.isFinite(teamBudget) && teamBudget > 0) {
    const spend = typeof key.spend === "number" && Number.isFinite(key.spend) ? key.spend : 0;
    return {
      budget: teamBudget,
      budget_source: "team",
      budget_boost_label: null,
      budget_duration: key.budget_duration || team?.budget_duration || null,
      budget_reset_at: key.budget_reset_at || null,
      spend,
    };
  }

  const spend = typeof key.spend === "number" && Number.isFinite(key.spend) ? key.spend : 0;
  return {
    budget: null,
    budget_source: "none",
    budget_boost_label: null,
    budget_duration: key.budget_duration || null,
    budget_reset_at: key.budget_reset_at || null,
    spend,
  };
}

export function percentOfCycleBudget(spend: number, budget: number | null): number | null {
  if (budget == null || !(budget > 0) || !Number.isFinite(spend)) {
    return null;
  }
  return Math.min(999, Math.max(0, (spend / budget) * 100));
}

export function toKeyCycleBudgetRow(
  key: KeyResponse,
  teams: Team[],
  memberContexts: Record<string, TeamMemberBudgetContext> = {},
): KeyCycleBudgetRow {
  const resolved = resolveKeyCycleBudget(key, teams, memberContexts);
  return {
    token_id: key.token_id || key.token || key.key_name,
    key_alias: key.key_alias || key.key_name || "(unnamed)",
    user_id: key.user_id || "",
    user_email: key.user_email || "",
    team_id: key.team_id,
    team_alias: key.team_alias || "",
    spend: resolved.spend,
    budget: resolved.budget,
    budget_source: resolved.budget_source,
    budget_boost_label: resolved.budget_boost_label,
    budget_duration: resolved.budget_duration,
    budget_reset_at: resolved.budget_reset_at,
    percent_used: percentOfCycleBudget(resolved.spend, resolved.budget),
  };
}

export type KeyCycleBudgetsViewProps = {
  accessToken: string | null;
  teams: Team[];
};

const PAGE_SIZE = 50;

export function KeyCycleBudgetsView({ accessToken, teams }: KeyCycleBudgetsViewProps) {
  const [rows, setRows] = useState<KeyCycleBudgetRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const data = await keyListCall(
        accessToken,
        null,
        null,
        null,
        null,
        null,
        page,
        PAGE_SIZE,
        "spend",
        "desc",
      );
      const keys: KeyResponse[] = data?.keys ?? data?.data ?? [];
      const teamIds = Array.from(
        new Set(keys.map((key) => key.team_id).filter((id): id is string => typeof id === "string" && !!id)),
      );
      const memberContexts: Record<string, TeamMemberBudgetContext> = {};
      await Promise.all(
        teamIds.map(async (teamId) => {
          try {
            const teamInfo = await teamInfoCall(accessToken, teamId);
            memberContexts[teamId] = buildTeamMemberBudgetContext(teamInfo ?? {});
          } catch {
            // Keep resolving other teams; key/team fallbacks still apply.
          }
        }),
      );
      setRows(keys.map((key) => toKeyCycleBudgetRow(key, teams, memberContexts)));
      setTotal(typeof data?.total_count === "number" ? data.total_count : keys.length);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [accessToken, page, teams]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<KeyCycleBudgetRow> = useMemo(
    () => [
      {
        title: "Key",
        dataIndex: "key_alias",
        key: "key_alias",
        ellipsis: true,
        render: (alias: string, row) => (
          <div className="min-w-0">
            <div className="font-medium text-gray-900 truncate">{alias}</div>
            <div className="text-xs text-gray-500 font-mono truncate">{row.token_id}</div>
          </div>
        ),
      },
      {
        title: "User",
        dataIndex: "user_id",
        key: "user_id",
        ellipsis: true,
        render: (_: string, row) => (
          <div className="min-w-0">
            <div className="truncate">{row.user_email || row.user_id || "—"}</div>
            {row.user_email && row.user_id ? (
              <div className="text-xs text-gray-500 truncate">{row.user_id}</div>
            ) : null}
          </div>
        ),
      },
      {
        title: "Team",
        dataIndex: "team_alias",
        key: "team_alias",
        ellipsis: true,
        render: (alias: string, row) => alias || row.team_id || "—",
      },
      {
        title: "Cycle spend",
        dataIndex: "spend",
        key: "spend",
        width: 120,
        sorter: (a, b) => a.spend - b.spend,
        render: (spend: number) => `$${formatNumberWithCommas(spend, 4)}`,
      },
      {
        title: "Cycle budget",
        dataIndex: "budget",
        key: "budget",
        width: 180,
        render: (budget: number | null, row) => {
          if (budget == null) return "Unlimited";
          const suffix =
            row.budget_source === "team"
              ? " (team)"
              : row.budget_source === "member"
                ? " (member)"
                : "";
          return (
            <div>
              <div>{`$${formatNumberWithCommas(budget)}${suffix}`}</div>
              {row.budget_boost_label ? (
                <Tag color="blue" className="mt-1">
                  {row.budget_boost_label}
                </Tag>
              ) : null}
            </div>
          );
        },
      },
      {
        title: "% of cycle",
        dataIndex: "percent_used",
        key: "percent_used",
        width: 180,
        sorter: (a, b) => (a.percent_used ?? -1) - (b.percent_used ?? -1),
        defaultSortOrder: "descend",
        render: (pct: number | null) => {
          if (pct == null) {
            return <Typography.Text type="secondary">n/a</Typography.Text>;
          }
          return (
            <div className="pr-2">
              <Progress
                percent={Math.min(100, Math.round(pct))}
                size="small"
                status={pct >= 100 ? "exception" : undefined}
                format={() => `${pct.toFixed(1)}%`}
              />
            </div>
          );
        },
      },
      {
        title: "Duration",
        dataIndex: "budget_duration",
        key: "budget_duration",
        width: 90,
        render: (d: string | null) => d || "—",
      },
      {
        title: "Resets",
        dataIndex: "budget_reset_at",
        key: "budget_reset_at",
        width: 160,
        render: (value: string | null) => (value ? new Date(value).toLocaleString() : "—"),
      },
    ],
    [],
  );

  return (
    <div className="mt-4">
      <Typography.Title level={4}>Key cycle budgets</Typography.Title>
      <Typography.Paragraph type="secondary">
        Prefers each key&apos;s own <code>max_budget</code> when set. Otherwise uses the same{" "}
        <strong>team member pool</strong> as the Members tab (including permanent / recurring / temp
        boosts). Proxy admins only.
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon className="mb-4" message={error} /> : null}
      <Table<KeyCycleBudgetRow>
        rowKey="token_id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (next) => setPage(next),
        }}
        scroll={{ x: 1100 }}
        size="middle"
      />
    </div>
  );
}
