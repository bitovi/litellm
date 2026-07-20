import React, { useEffect, useState } from "react";
import { Alert, Card, Col, Row, Spin, Statistic, Typography } from "antd";
import { getProxyBaseUrl } from "@/components/networking";
import { formatNumberWithCommas } from "@/utils/dataUtils";

type SavingsResponse = {
  start_date: string;
  end_date: string;
  requests_with_stats: number;
  requests_with_savings: number;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  compression_ratio: number;
};

export type HeadroomSavingsViewProps = {
  accessToken: string | null;
  /** YYYY-MM-DD */
  startDate: string;
  /** YYYY-MM-DD */
  endDate: string;
};

async function fetchHeadroomSavings(
  accessToken: string,
  startDate: string,
  endDate: string,
): Promise<SavingsResponse> {
  const base = getProxyBaseUrl() ? `${getProxyBaseUrl()}` : "";
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
  const res = await fetch(`${base}/bitovi/headroom/savings?${params.toString()}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

export function HeadroomSavingsView({ accessToken, startDate, endDate }: HeadroomSavingsViewProps) {
  const [data, setData] = useState<SavingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchHeadroomSavings(accessToken, startDate, endDate)
      .then((json) => {
        if (!cancelled) setData(json);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, startDate, endDate]);

  return (
    <div className="mt-4">
      <Typography.Title level={4}>Headroom savings</Typography.Title>
      <Typography.Paragraph type="secondary">
        Aggregate prompt tokens removed by the Headroom guardrail for {startDate} → {endDate} (UTC). Sourced from
        spend-log <code>metadata.headroom_compression</code> (not redacted guardrail payloads).
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon className="mb-4" message={error} /> : null}
      {loading ? (
        <div className="py-8 flex justify-center">
          <Spin />
        </div>
      ) : data ? (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card>
              <Statistic title="Tokens saved" value={formatNumberWithCommas(data.tokens_saved)} />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card>
              <Typography.Text type="secondary">Before → after</Typography.Text>
              <div className="text-2xl font-semibold mt-1">
                {formatNumberWithCommas(data.tokens_before)} → {formatNumberWithCommas(data.tokens_after)}
              </div>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card>
              <Typography.Text type="secondary">Requests with savings</Typography.Text>
              <div className="text-2xl font-semibold mt-1">
                {formatNumberWithCommas(data.requests_with_savings)} / {formatNumberWithCommas(data.requests_with_stats)}
              </div>
            </Card>
          </Col>
        </Row>
      ) : null}
    </div>
  );
}
