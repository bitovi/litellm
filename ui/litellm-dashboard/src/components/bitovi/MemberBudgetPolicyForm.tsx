import NumericalInput from "@/components/shared/numerical_input";
import { deriveErrorMessage, getGlobalLitellmHeaderName, getProxyBaseUrl } from "@/components/networking";
import { Button, Form, Space, Typography } from "antd";
import React, { useEffect, useState } from "react";

export interface BitoviBudgetBreakdown {
  team_default?: number | null;
  base?: number | null;
  recurring_additive?: number;
  temp_additive?: number;
  effective_max?: number | null;
  using_team_default_base?: boolean;
  temp_active?: boolean;
}

interface MemberBudgetPolicyResponse {
  team_id: string;
  user_id: string;
  team_default?: number | null;
  policy: {
    permanent_max_budget?: number;
    recurring_additive?: number;
    temp_additive?: number;
    temp_expires_at?: string;
  };
  breakdown: BitoviBudgetBreakdown;
  effective_max?: number | null;
}

interface MemberBudgetPolicyFormProps {
  accessToken: string;
  teamId: string;
  userId: string;
  onSaved?: () => void;
}

async function fetchPolicy(
  accessToken: string,
  teamId: string,
  userId: string,
): Promise<MemberBudgetPolicyResponse> {
  const proxyBaseUrl = getProxyBaseUrl();
  const url = proxyBaseUrl
    ? `${proxyBaseUrl}/bitovi/team/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}/budget-policy`
    : `/bitovi/team/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}/budget-policy`;
  const response = await fetch(url, {
    method: "GET",
    headers: {
      [getGlobalLitellmHeaderName()]: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(deriveErrorMessage(errorData));
  }
  return (await response.json()) as MemberBudgetPolicyResponse;
}

async function putPolicy(
  accessToken: string,
  teamId: string,
  userId: string,
  body: Record<string, unknown>,
): Promise<MemberBudgetPolicyResponse> {
  const proxyBaseUrl = getProxyBaseUrl();
  const url = proxyBaseUrl
    ? `${proxyBaseUrl}/bitovi/team/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}/budget-policy`
    : `/bitovi/team/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}/budget-policy`;
  const response = await fetch(url, {
    method: "PUT",
    headers: {
      [getGlobalLitellmHeaderName()]: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(deriveErrorMessage(errorData));
  }
  return (await response.json()) as MemberBudgetPolicyResponse;
}

export default function MemberBudgetPolicyForm({
  accessToken,
  teamId,
  userId,
  onSaved,
}: MemberBudgetPolicyFormProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [breakdown, setBreakdown] = useState<BitoviBudgetBreakdown | null>(null);
  const [teamDefault, setTeamDefault] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchPolicy(accessToken, teamId, userId);
        if (cancelled) return;
        setBreakdown(data.breakdown);
        setTeamDefault(data.team_default ?? null);
        form.setFieldsValue({
          permanent_max_budget: data.policy.permanent_max_budget ?? null,
          recurring_additive: data.policy.recurring_additive ?? null,
          temp_additive: data.policy.temp_additive ?? null,
        });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load budget policy");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken, teamId, userId, form]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const values = await form.validateFields();
      const body: Record<string, unknown> = {};
      if (values.permanent_max_budget === null || values.permanent_max_budget === undefined || values.permanent_max_budget === "") {
        body.clear_permanent = true;
      } else {
        body.permanent_max_budget = Number(values.permanent_max_budget);
      }
      if (values.recurring_additive === null || values.recurring_additive === undefined || values.recurring_additive === "") {
        body.clear_recurring = true;
      } else {
        body.recurring_additive = Number(values.recurring_additive);
      }
      if (values.temp_additive === null || values.temp_additive === undefined || values.temp_additive === "") {
        body.clear_temp = true;
      } else {
        body.temp_additive = Number(values.temp_additive);
      }
      const data = await putPolicy(accessToken, teamId, userId, body);
      setBreakdown(data.breakdown);
      setTeamDefault(data.team_default ?? null);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save budget policy");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <Typography.Text type="secondary">Loading member budget policy…</Typography.Text>;
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Config team members inherit the team default
        {teamDefault != null ? ` ($${teamDefault})` : ""}. Use additives to boost a user without
        changing the YAML default.
      </Typography.Text>
      {breakdown?.effective_max != null && (
        <Typography.Text>
          Effective cap this cycle: <strong>${breakdown.effective_max}</strong>
          {breakdown.recurring_additive ? ` (recurring +$${breakdown.recurring_additive})` : ""}
          {breakdown.temp_active && breakdown.temp_additive
            ? ` (temp +$${breakdown.temp_additive})`
            : ""}
        </Typography.Text>
      )}
      <Form form={form} layout="vertical">
        <Form.Item
          name="permanent_max_budget"
          label="Permanent base override (USD)"
          tooltip="Replaces the team default as this user's base. Leave empty to inherit the team default."
        >
          <NumericalInput step={0.01} min={0} placeholder="Inherit team default" />
        </Form.Item>
        <Form.Item
          name="recurring_additive"
          label="Recurring additive each cycle (USD)"
          tooltip="Added on top of base every cycle. Spend resets; this amount stays."
        >
          <NumericalInput step={0.01} min={0} placeholder="0" />
        </Form.Item>
        <Form.Item
          name="temp_additive"
          label="Temp additive until cycle reset (USD)"
          tooltip="One-shot boost for the rest of this cycle. Clears at budget_reset_at."
        >
          <NumericalInput step={0.01} min={0} placeholder="0" />
        </Form.Item>
      </Form>
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
      <Button type="primary" loading={saving} onClick={handleSave}>
        Save budget policy
      </Button>
    </Space>
  );
}
