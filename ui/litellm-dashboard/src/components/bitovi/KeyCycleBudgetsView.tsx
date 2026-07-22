import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Progress, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import { formatNumberWithCommas } from "@/utils/dataUtils";
import { keyListCall } from "@/components/networking";
import type { KeyResponse, Team } from "@/components/key_team_helpers/key_list";

export type KeyCycleBudgetRow = {
  token_id: string;
  key_alias: string;
  user_id: string;
  user_email: string;
  team_id: string | null;
  team_alias: string;
  spend: number;
  budget: number | null;
  budget_source: "key" | "team" | "none";
  budget_duration: string | null;
  budget_reset_at: string | null;
  percent_used: number | null;
};

export function resolveKeyCycleBudget(
  key: KeyResponse,
  teams: Team[],
): { budget: number | null; budget_source: "key" | "team" | "none" } {
  const keyBudget = key.max_budget;
  if (typeof keyBudget === "number" && Number.isFinite(keyBudget) && keyBudget > 0) {
    return { budget: keyBudget, budget_source: "key" };
  }
  const team = teams.find((t) => t.team_id === key.team_id);
  const teamBudget = team?.max_budget ?? key.team_max_budget;
  if (typeof teamBudget === "number" && Number.isFinite(teamBudget) && teamBudget > 0) {
    return { budget: teamBudget, budget_source: "team" };
  }
  return { budget: null, budget_source: "none" };
}

export function percentOfCycleBudget(spend: number, budget: number | null): number | null {
  if (budget == null || !(budget > 0) || !Number.isFinite(spend)) {
    return null;
  }
  return Math.min(999, Math.max(0, (spend / budget) * 100));
}

export function toKeyCycleBudgetRow(key: KeyResponse, teams: Team[]): KeyCycleBudgetRow {
  const { budget, budget_source } = resolveKeyCycleBudget(key, teams);
  const spend = typeof key.spend === "number" && Number.isFinite(key.spend) ? key.spend : 0;
  return {
    token_id: key.token_id || key.token || key.key_name,
    key_alias: key.key_alias || key.key_name || "(unnamed)",
    user_id: key.user_id || "",
    user_email: key.user_email || "",
    team_id: key.team_id,
    team_alias: key.team_alias || "",
    spend,
    budget,
    budget_source,
    budget_duration: key.budget_duration || null,
    budget_reset_at: key.budget_reset_at || null,
    percent_used: percentOfCycleBudget(spend, budget),
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
      setRows(keys.map((key) => toKeyCycleBudgetRow(key, teams)));
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
        width: 140,
        render: (budget: number | null, row) => {
          if (budget == null) return "Unlimited";
          const suffix = row.budget_source === "team" ? " (team)" : "";
          return `$${formatNumberWithCommas(budget)}${suffix}`;
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
        Spend vs each key&apos;s current budget cycle (<code>max_budget</code> / <code>budget_duration</code>).
        Proxy admins only. This is the key-level counter — not the team-member pool shown under My Budgets.
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
