import React from "react";
import { Card, Descriptions, Typography } from "antd";
import { formatNumberWithCommas } from "@/utils/dataUtils";

export type HeadroomCompressionMeta = {
  tokens_before?: number;
  tokens_after?: number;
  tokens_saved?: number;
  compression_ratio?: number;
};

function readHeadroomCompression(metadata: Record<string, unknown> | undefined): HeadroomCompressionMeta | null {
  if (!metadata) return null;
  const direct = metadata.headroom_compression;
  if (direct && typeof direct === "object") {
    return direct as HeadroomCompressionMeta;
  }
  const spend = metadata.spend_logs_metadata;
  if (spend && typeof spend === "object") {
    const nested = (spend as Record<string, unknown>).headroom_compression;
    if (nested && typeof nested === "object") {
      return nested as HeadroomCompressionMeta;
    }
  }
  return null;
}

export function HeadroomCompressionPanel({ metadata }: { metadata?: Record<string, unknown> }) {
  const stats = readHeadroomCompression(metadata);
  if (!stats || stats.tokens_before == null || stats.tokens_after == null) {
    return null;
  }
  const saved = stats.tokens_saved ?? Math.max(0, Number(stats.tokens_before) - Number(stats.tokens_after));
  const ratio =
    stats.compression_ratio != null
      ? `${(Number(stats.compression_ratio) * 100).toFixed(1)}% of original`
      : null;

  return (
    <Card size="small" className="mb-4" title="Headroom compression">
      <Typography.Paragraph type="secondary" className="mb-3">
        Tokens before vs after prompt compression (Bitovi). Independent of redacted guardrail_response.
      </Typography.Paragraph>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="Before">{formatNumberWithCommas(Number(stats.tokens_before))}</Descriptions.Item>
        <Descriptions.Item label="After">{formatNumberWithCommas(Number(stats.tokens_after))}</Descriptions.Item>
        <Descriptions.Item label="Saved">{formatNumberWithCommas(saved)}</Descriptions.Item>
        {ratio ? <Descriptions.Item label="Remaining">{ratio}</Descriptions.Item> : null}
      </Descriptions>
    </Card>
  );
}
