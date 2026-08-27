"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Bot,
  Boxes,
  CircleDollarSign,
  Gauge,
  MessageSquare,
  PlugZap,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "@/components/atoms/charts";

import { DashboardMetricCard } from "@/components/molecules/dashboard-metric-card";
import { DashboardPanel } from "@/components/molecules/dashboard-panel";
import { DashboardSection } from "@/components/molecules/dashboard-section";
import { HealthRow } from "@/components/molecules/health-row";
import { SignalBar } from "@/components/molecules/signal-bar";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import type {
  AgentRead,
  MCPGatewayToolApprovalRead,
  MCPRuntimeSummaryResponse,
  MCPServerInstallationRead,
  MCPToolUsageListResponse,
  UsageSummaryBreakdownRow,
  UsageSummaryResponse,
  WorkspaceObservabilityAgentRunRow,
  WorkspaceObservabilityDashboardResponse,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { formatUserDateBucket, formatUserShortDateTime } from "@/lib/date-time";

type WorkspaceDashboardPaths = {
  agentRuns: string;
  agents: string;
  chat: string;
  install: string;
  observability: string;
  runtime: string;
  scheduledTasks: string;
  workspace: string;
};

type WorkspaceDashboardClientProps = {
  agents: AgentRead[];
  gatewayApprovals: MCPGatewayToolApprovalRead[];
  installations: MCPServerInstallationRead[];
  observability: WorkspaceObservabilityDashboardResponse;
  paths: WorkspaceDashboardPaths;
  runtime: MCPRuntimeSummaryResponse;
  toolUsage: MCPToolUsageListResponse;
  usage: UsageSummaryResponse;
  workspace: WorkspaceRead;
};

type ChartTooltipProps = {
  active?: boolean;
  label?: string;
  payload?: Array<{
    color?: string;
    dataKey?: string;
    name?: string;
    value?: number | string;
  }>;
};

type AttentionItem = {
  detail: string;
  href?: string;
  key: string;
  label: string;
  severity: "danger" | "info" | "success" | "warning";
};

type DashboardTone = "danger" | "info" | "neutral" | "success" | "warning";

const chartColors = ["#2563eb", "#0891b2", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed"];
const compactNumberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  notation: "compact",
});
const numberFormatter = new Intl.NumberFormat("en-US");

function numberValue(value: number | string | null | undefined) {
  return Number(value ?? 0);
}

function formatCount(value: number | null | undefined) {
  return typeof value === "number" ? numberFormatter.format(value) : "0";
}

function formatCompact(value: number | null | undefined) {
  return typeof value === "number" ? compactNumberFormatter.format(value) : "0";
}

function formatCurrency(value: number | string | null | undefined) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: numberValue(value) >= 1 ? 2 : 4,
    minimumFractionDigits: 2,
    style: "currency",
  }).format(numberValue(value));
}

function formatDuration(value: number | null | undefined) {
  if (typeof value !== "number") {
    return "n/a";
  }
  if (value < 1000) {
    return `${formatCount(Math.round(value))} ms`;
  }
  return `${(value / 1000).toFixed(1)} s`;
}

function formatPercent(value: number | null | undefined) {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "n/a";
}

function formatRatioPercent(value: number | null | undefined) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "n/a";
}

function chartDate(value: string) {
  return formatUserDateBucket(value);
}

function shortLabel(value: string, maxLength = 24) {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}...` : value;
}

function pluralize(value: number, singular: string, plural = `${singular}s`) {
  return value === 1 ? singular : plural;
}

function commaList(values: string[], fallback: string, limit = 3) {
  const visible = values.filter(Boolean).slice(0, limit);
  if (visible.length === 0) {
    return fallback;
  }
  const remaining = values.length - visible.length;
  return remaining > 0 ? `${visible.join(", ")} +${remaining}` : visible.join(", ");
}

function runStatusTone(status: string): DashboardTone {
  if (status === "failed") {
    return "danger";
  }
  if (status === "running" || status === "waiting_confirmation" || status === "submitted") {
    return "warning";
  }
  if (status === "succeeded") {
    return "success";
  }
  return "info";
}

function runStatusLabel(status: string) {
  return status.replaceAll("_", " ") || "unknown";
}

function runHref(agentRunsPath: string, runId: string) {
  return `${agentRunsPath}/${encodeURIComponent(runId)}`;
}

function installationHref(installPath: string, installationId: string) {
  return `${installPath}/${encodeURIComponent(installationId)}`;
}

function attentionHref(workspacePath: string, href?: string) {
  if (!href) {
    return undefined;
  }
  return href.startsWith("/") ? href : `${workspacePath}/${href}`;
}

function formatTimestamp(value: string | null | undefined) {
  return formatUserShortDateTime(value, "No timestamp");
}

function runtimeLabel(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === "remote") {
    return "Remote";
  }
  if (normalized === "oci") {
    return "OCI";
  }
  if (normalized === "npm") {
    return "NPM";
  }
  if (normalized === "uvx") {
    return "UVX";
  }
  return value || "Unknown";
}

function installationNeedsAttention(installation: MCPServerInstallationRead) {
  return installation.status !== "enabled" || Boolean(installation.installError);
}

function requestSuccessRate(usage: UsageSummaryResponse) {
  const completed = usage.summary.succeeded + usage.summary.failed;
  if (completed === 0) {
    return 100;
  }
  return (usage.summary.succeeded / completed) * 100;
}

function toolSuccessRate(runtime: MCPRuntimeSummaryResponse) {
  const completed = runtime.toolCalls.succeeded + runtime.toolCalls.failed;
  if (completed === 0) {
    return 100;
  }
  return (runtime.toolCalls.succeeded / completed) * 100;
}

function workspaceHealthScore({
  agents,
  installations,
  runtime,
  usage,
}: {
  agents: AgentRead[];
  installations: MCPServerInstallationRead[];
  runtime: MCPRuntimeSummaryResponse;
  usage: UsageSummaryResponse;
}) {
  const attentionCount = installations.filter(installationNeedsAttention).length;
  const requestRisk = Math.min(22, 100 - requestSuccessRate(usage));
  const toolRisk = Math.min(18, runtime.toolCalls.recentFailureRate * 100);
  const runtimeRisk = Math.min(
    18,
    (runtime.failedSessions + runtime.staleActiveSessions + runtime.recentServerErrors.length) * 6
  );
  const connectionRisk = Math.min(22, attentionCount * 7);
  const coverageRisk = agents.length > 0 && agents.every((agent) => !agent.isActive) ? 10 : 0;
  const score = 100 - requestRisk - toolRisk - runtimeRisk - connectionRisk - coverageRisk;
  return Math.max(0, Math.round(score));
}

function healthTone(score: number) {
  if (score >= 85) {
    return "success" as const;
  }
  if (score >= 65) {
    return "warning" as const;
  }
  return "danger" as const;
}

function badgeVariant(tone: "danger" | "info" | "success" | "warning") {
  if (tone === "danger") {
    return "destructive" as const;
  }
  if (tone === "success") {
    return "success" as const;
  }
  return "secondary" as const;
}

function ChartTooltip({ active, payload, label }: ChartTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-[var(--shadow-card)]">
      {label ? <div className="mb-1 font-medium text-foreground">{label}</div> : null}
      <div className="space-y-1">
        {payload.map((item) => {
          const key = String(item.dataKey ?? item.name ?? "");
          const value = Number(item.value ?? 0);
          const formatted =
            key.toLowerCase().includes("cost") || key.toLowerCase().includes("spend")
              ? formatCurrency(value)
              : key.toLowerCase().includes("rate")
                ? formatPercent(value)
                : formatCount(value);
          return (
            <div className="flex items-center gap-2" key={`${key}-${item.name}`}>
              <span
                className="size-2 rounded-full"
                style={{ backgroundColor: item.color ?? "#2563eb" }}
              />
              <span className="text-muted-foreground">{item.name ?? key}</span>
              <span className="font-medium text-foreground">{formatted}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex min-h-28 items-center justify-center rounded-md border border-dashed border-border px-4 text-center text-sm text-muted-foreground">
      {label}
    </div>
  );
}

function ActivityTrendChart({ usage }: { usage: UsageSummaryResponse }) {
  const data = usage.daily.map((point) => ({
    costUsd: numberValue(point.costUsd),
    dateLabel: chartDate(point.date),
    requests: point.requests,
    toolCalls: point.toolCalls,
    totalTokens: point.totalTokens,
  }));

  return (
    <DashboardPanel
      className="xl:col-span-2"
      description={`${usage.window.startDate} to ${usage.window.endDate}`}
      title="Workspace activity"
    >
      {data.length < 2 ? (
        <EmptyChart
          label={
            data[0]
              ? `${data[0].dateLabel}: ${formatCount(data[0].requests)} requests, ${formatCount(
                  data[0].toolCalls
                )} tool calls, ${formatCompact(data[0].totalTokens)} tokens, ${formatCurrency(
                  data[0].costUsd
                )}. Add another day to show a trend.`
              : "No workspace usage recorded in this window."
          }
        />
      ) : (
        <div className="h-72">
          <ResponsiveContainer height="100%" width="100%">
            <AreaChart data={data} margin={{ left: 0, right: 12, top: 10 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="dateLabel"
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickLine={false}
                tickMargin={10}
              />
              <YAxis
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickFormatter={(value) => formatCompact(Number(value))}
                tickLine={false}
                tickMargin={10}
                yAxisId="volume"
              />
              <YAxis hide orientation="right" yAxisId="cost" />
              <Tooltip content={<ChartTooltip />} />
              <Area
                dataKey="requests"
                fill="#2563eb"
                fillOpacity={0.14}
                name="Requests"
                stroke="#2563eb"
                strokeWidth={2}
                type="monotone"
                yAxisId="volume"
              />
              <Area
                dataKey="toolCalls"
                fill="#16a34a"
                fillOpacity={0.1}
                name="Tool calls"
                stroke="#16a34a"
                strokeWidth={2}
                type="monotone"
                yAxisId="volume"
              />
              <Line
                dataKey="costUsd"
                dot={false}
                name="Cost"
                stroke="#dc2626"
                strokeWidth={2}
                type="monotone"
                yAxisId="cost"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </DashboardPanel>
  );
}

function ModelSpendChart({ rows }: { rows: UsageSummaryBreakdownRow[] }) {
  const data = rows.slice(0, 6).map((row) => ({
    costUsd: numberValue(row.costUsd),
    name: shortLabel(row.label, 28),
    requests: row.requests,
    totalTokens: row.totalTokens,
  }));

  return (
    <DashboardPanel description="Highest cost model routes in this workspace." title="Model spend">
      {data.length < 2 ? (
        <EmptyChart
          label={
            data[0]
              ? `${data[0].name}: ${formatCurrency(data[0].costUsd)}, ${formatCount(
                  data[0].requests
                )} requests, ${formatCompact(data[0].totalTokens)} tokens.`
              : "No model spend recorded."
          }
        />
      ) : (
        <div className="h-72">
          <ResponsiveContainer height="100%" width="100%">
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 18 }}>
              <CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickFormatter={(value) => formatCurrency(Number(value))}
                tickLine={false}
                type="number"
              />
              <YAxis
                dataKey="name"
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickLine={false}
                type="category"
                width={128}
              />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="costUsd" fill="#2563eb" name="Cost" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </DashboardPanel>
  );
}

function AgentDemandChart({
  agents,
  rows,
}: {
  agents: AgentRead[];
  rows: UsageSummaryBreakdownRow[];
}) {
  const usageRows =
    rows.length > 0
      ? rows.slice(0, 6).map((row) => ({
          name: shortLabel(row.label, 24),
          requests: row.requests,
          toolCalls: row.toolCalls,
        }))
      : agents.slice(0, 6).map((agent) => ({
          name: shortLabel(agent.name, 24),
          requests: 0,
          toolCalls: agent.toolCount,
        }));

  return (
    <DashboardPanel
      description="Workspace assistant demand and tool coverage."
      title="Assistant workload"
    >
      {usageRows.length < 2 ? (
        <EmptyChart
          label={
            usageRows[0]
              ? `${usageRows[0].name}: ${formatCount(
                  usageRows[0].requests
                )} requests and ${formatCount(usageRows[0].toolCalls)} tools.`
              : "No workspace assistant activity yet."
          }
        />
      ) : (
        <div className="h-72">
          <ResponsiveContainer height="100%" width="100%">
            <BarChart data={usageRows} margin={{ left: 0, right: 12, top: 10 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="name"
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickLine={false}
                tickMargin={10}
              />
              <YAxis
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickFormatter={(value) => formatCompact(Number(value))}
                tickLine={false}
              />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="requests" fill="#0891b2" name="Requests" radius={[4, 4, 0, 0]} />
              <Bar dataKey="toolCalls" fill="#f59e0b" name="Tools" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </DashboardPanel>
  );
}

function ConnectionMixPanel({
  installPath,
  installations,
}: {
  installPath: string;
  installations: MCPServerInstallationRead[];
}) {
  const runtimeRows = Object.entries(
    installations.reduce<Record<string, { attention: number; enabled: number; total: number }>>(
      (result, installation) => {
        const label = runtimeLabel(installation.installType);
        result[label] ??= { attention: 0, enabled: 0, total: 0 };
        result[label].total += 1;
        if (installation.status === "enabled") {
          result[label].enabled += 1;
        }
        if (installationNeedsAttention(installation)) {
          result[label].attention += 1;
        }
        return result;
      },
      {}
    )
  )
    .map(([label, row]) => ({ label, ...row }))
    .sort((first, second) => second.total - first.total);

  const enabled = installations.filter((installation) => installation.status === "enabled").length;
  const attention = installations.filter(installationNeedsAttention).length;
  const updates = installations.filter((installation) => installation.updateAvailable).length;

  return (
    <DashboardPanel
      action={
        installPath ? (
          <Button asChild size="sm" variant="outline">
            <Link href={installPath}>
              <PlugZap className="size-4" />
              Open
            </Link>
          </Button>
        ) : null
      }
      description="MCP connection mix and version posture."
      title="Connections"
    >
      {runtimeRows.length < 2 ? (
        <EmptyChart
          label={
            runtimeRows[0]
              ? `${runtimeRows[0].label}: ${formatCount(runtimeRows[0].total)} installed, ${formatCount(
                  runtimeRows[0].enabled
                )} enabled, ${formatCount(runtimeRows[0].attention)} need review, ${formatCount(
                  updates
                )} updates.`
              : "No MCP servers installed."
          }
        />
      ) : (
        <div className="grid gap-5 md:grid-cols-[180px_minmax(0,1fr)]">
          <div className="h-48">
            <ResponsiveContainer height="100%" width="100%">
              <PieChart>
                <Tooltip content={<ChartTooltip />} />
                <Pie
                  cx="50%"
                  cy="50%"
                  data={runtimeRows.map((row, index) => ({
                    fill: chartColors[index % chartColors.length],
                    name: row.label,
                    value: row.total,
                  }))}
                  dataKey="value"
                  innerRadius={48}
                  nameKey="name"
                  outerRadius={76}
                  paddingAngle={2}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="min-w-0 space-y-4 self-center">
            <div>
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-medium">Enabled connections</span>
                <span className="font-mono text-muted-foreground">
                  {formatCount(enabled)}/{formatCount(installations.length)}
                </span>
              </div>
              <SignalBar
                className="mt-2"
                segments={[
                  { label: `${enabled} enabled`, tone: "success", value: enabled },
                  { label: `${attention} review`, tone: "warning", value: attention },
                  {
                    label: "Other",
                    tone: "neutral",
                    value: Math.max(installations.length - enabled - attention, 0),
                  },
                ]}
              />
            </div>
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <div className="rounded-md border border-border bg-muted/30 px-2 py-2">
                <div className="text-base font-semibold">{formatCount(runtimeRows.length)}</div>
                <div className="mt-1 text-muted-foreground">Types</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-2">
                <div className="text-base font-semibold">{formatCount(updates)}</div>
                <div className="mt-1 text-muted-foreground">Updates</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-2">
                <div className="text-base font-semibold">{formatCount(attention)}</div>
                <div className="mt-1 text-muted-foreground">Review</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardPanel>
  );
}

function RuntimePanel({
  runtime,
  runtimePath,
  toolUsage,
}: {
  runtime: MCPRuntimeSummaryResponse;
  runtimePath: string;
  toolUsage: MCPToolUsageListResponse;
}) {
  const active = runtime.activeSessions;
  const idle = runtime.idleSessions;
  const stopped = runtime.stoppedSessions + runtime.expiredSessions;
  const failed = runtime.failedSessions + runtime.staleActiveSessions;
  const recentCalls = runtime.toolCalls.recentTotal;

  return (
    <DashboardPanel
      action={
        runtimePath ? (
          <Button asChild size="sm" variant="outline">
            <Link href={runtimePath}>
              <ServerCog className="size-4" />
              Runtime
            </Link>
          </Button>
        ) : null
      }
      description="Session state and recent MCP tool execution."
      title="Runtime posture"
    >
      <div className="space-y-5">
        <SignalBar
          className="h-3"
          segments={[
            { label: `${active} active`, tone: "success", value: active },
            { label: `${idle} idle`, tone: "info", value: idle },
            { label: `${failed} review`, tone: "danger", value: failed },
            { label: `${stopped} stopped`, tone: "neutral", value: stopped },
          ]}
        />
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-md border border-border bg-muted/25 p-3">
            <div className="text-xs text-muted-foreground">Active sessions</div>
            <div className="mt-2 text-2xl font-semibold">{formatCount(active)}</div>
          </div>
          <div className="rounded-md border border-border bg-muted/25 p-3">
            <div className="text-xs text-muted-foreground">Recent failure rate</div>
            <div className="mt-2 text-2xl font-semibold">
              {formatRatioPercent(runtime.toolCalls.recentFailureRate)}
            </div>
          </div>
          <div className="rounded-md border border-border bg-muted/25 p-3">
            <div className="text-xs text-muted-foreground">Recent calls</div>
            <div className="mt-2 text-2xl font-semibold">{formatCount(recentCalls)}</div>
          </div>
          <div className="rounded-md border border-border bg-muted/25 p-3">
            <div className="text-xs text-muted-foreground">Avg duration</div>
            <div className="mt-2 text-2xl font-semibold">
              {formatDuration(toolUsage.summary.averageDurationMs)}
            </div>
          </div>
        </div>
      </div>
    </DashboardPanel>
  );
}

function AttentionPanel({ items }: { items: AttentionItem[] }) {
  return (
    <DashboardPanel description="Prioritized workspace actions." title="What to do next">
      <div className="-m-4">
        {items.length === 0 ? (
          <HealthRow
            badge="Clear"
            detail="No approvals, failed runs, broken tools, or runtime issues detected"
            icon={ShieldCheck}
            label="No active items"
            tone="success"
          />
        ) : (
          items.slice(0, 6).map((item) => (
            <HealthRow
              badge={item.severity}
              detail={item.detail}
              href={item.href}
              icon={item.severity === "danger" ? AlertTriangle : Activity}
              key={item.key}
              label={item.label}
              tone={item.severity}
            />
          ))
        )}
      </div>
    </DashboardPanel>
  );
}

function buildAttentionItems({
  agentRunsPath,
  agents,
  gatewayApprovals,
  installPath,
  installations,
  observability,
  observabilityPath,
  paths,
  runtime,
  runtimePath,
  usage,
  workspace,
}: {
  agentRunsPath: string;
  agents: AgentRead[];
  gatewayApprovals: MCPGatewayToolApprovalRead[];
  installPath: string;
  installations: MCPServerInstallationRead[];
  observability: WorkspaceObservabilityDashboardResponse;
  observabilityPath: string;
  paths: WorkspaceDashboardPaths;
  runtime: MCPRuntimeSummaryResponse;
  runtimePath: string;
  usage: UsageSummaryResponse;
  workspace: WorkspaceRead;
}) {
  const items: AttentionItem[] = [];
  const installationAttention = installations.filter(installationNeedsAttention).length;
  const updateCount = installations.filter((installation) => installation.updateAvailable).length;
  const waitingRuns = observability.recentRuns.filter(
    (run) => run.status === "waiting_confirmation"
  );
  const pendingApprovals = gatewayApprovals.length + waitingRuns.length;

  if (pendingApprovals > 0) {
    const approvalHref =
      gatewayApprovals[0]?.installationId
        ? installationHref(installPath, gatewayApprovals[0].installationId)
        : waitingRuns[0]
          ? runHref(agentRunsPath, waitingRuns[0].id)
          : installPath;
    items.push({
      detail: `${formatCount(pendingApprovals)} pending ${pluralize(
        pendingApprovals,
        "approval"
      )} blocking tool execution`,
      href: approvalHref,
      key: "pending-approvals",
      label: "Review approvals",
      severity: "danger",
    });
  }

  for (const item of observability.attention.filter((item) => item.severity !== "success")) {
    items.push({
      detail: item.detail,
      href: attentionHref(paths.workspace, item.href) ?? observabilityPath,
      key: `observability-${item.key}`,
      label: item.label,
      severity:
        item.severity === "danger" ? "danger" : item.severity === "warning" ? "warning" : "info",
    });
  }

  if (usage.summary.failed > 0 && !items.some((item) => item.key === "observability-llm-failures")) {
    items.push({
      detail: `${formatCount(usage.summary.failed)} failed ${pluralize(
        usage.summary.failed,
        "request"
      )} in the current window`,
      href: observabilityPath,
      key: "failed-requests",
      label: "Model reliability",
      severity: "warning",
    });
  }
  if (runtime.toolCalls.recentFailureRate >= 0.05) {
    items.push({
      detail: `${formatRatioPercent(runtime.toolCalls.recentFailureRate)} recent MCP tool failure rate`,
      href: runtimePath,
      key: "tool-failures",
      label: "Tool execution risk",
      severity: runtime.toolCalls.recentFailureRate >= 0.15 ? "danger" : "warning",
    });
  }
  if (installationAttention > 0) {
    items.push({
      detail: `${formatCount(installationAttention)} ${pluralize(
        installationAttention,
        "connection"
      )} disabled or reporting install errors`,
      href: installPath,
      key: "connection-attention",
      label: "Connection health",
      severity: "danger",
    });
  }
  if (runtime.failedSessions + runtime.staleActiveSessions > 0) {
    const count = runtime.failedSessions + runtime.staleActiveSessions;
    items.push({
      detail: `${formatCount(count)} ${pluralize(count, "session")} failed or stale`,
      href: runtimePath,
      key: "runtime-sessions",
      label: "Runtime sessions",
      severity: "warning",
    });
  }
  if (updateCount > 0) {
    items.push({
      detail: `${formatCount(updateCount)} ${pluralize(updateCount, "server")} with catalog updates`,
      href: installPath,
      key: "server-updates",
      label: "Available updates",
      severity: "info",
    });
  }
  if (agents.length === 0) {
    items.push({
      detail: "Start chat to create the workspace assistant",
      key: "agents",
      label: "Workspace assistant",
      severity: "info",
    });
  }
  if (workspace && !workspace.guardrailDefaultDeny) {
    items.push({
      detail: "Workspace access mode is default allow",
      key: "guardrails",
      label: "Access posture",
      severity: "info",
    });
  }

  return items;
}

function brokenSignalCount({
  installationAttention,
  observability,
  runtime,
}: {
  installationAttention: number;
  observability: WorkspaceObservabilityDashboardResponse;
  runtime: MCPRuntimeSummaryResponse;
}) {
  return (
    installationAttention +
    runtime.failedSessions +
    runtime.staleActiveSessions +
    observability.summary.failedAgentRuns +
    observability.summary.failedRequests +
    observability.summary.failedToolCalls +
    observability.summary.runtimeSessionsNeedingAttention
  );
}

function WorkspaceHomePanel({
  activeAgents,
  agentRunsPath,
  agents,
  attentionItems,
  assignedTools,
  gatewayApprovals,
  installationAttention,
  installations,
  installPath,
  observability,
  runtime,
  paths,
}: {
  activeAgents: number;
  agentRunsPath: string;
  agents: AgentRead[];
  attentionItems: AttentionItem[];
  assignedTools: number;
  gatewayApprovals: MCPGatewayToolApprovalRead[];
  installationAttention: number;
  installations: MCPServerInstallationRead[];
  installPath: string;
  observability: WorkspaceObservabilityDashboardResponse;
  runtime: MCPRuntimeSummaryResponse;
  paths: WorkspaceDashboardPaths;
}) {
  const enabledInstallations = installations.filter(
    (installation) => installation.status === "enabled"
  ).length;
  const activeAgentNames = commaList(
    agents.filter((agent) => agent.isActive).map((agent) => agent.name),
    "No active agents"
  );
  const waitingRuns = observability.recentRuns.filter(
    (run) => run.status === "waiting_confirmation"
  );
  const approvalCount = gatewayApprovals.length + waitingRuns.length;
  const firstApprovalHref =
    gatewayApprovals[0]?.installationId
      ? installationHref(installPath, gatewayApprovals[0].installationId)
      : waitingRuns[0]
        ? runHref(agentRunsPath, waitingRuns[0].id)
        : paths.agentRuns;
  const brokenCount = brokenSignalCount({ installationAttention, observability, runtime });
  const latestRun = observability.recentRuns[0];
  const nextAction =
    attentionItems.find((item) => item.severity === "danger" || item.severity === "warning") ??
    attentionItems.find((item) => item.severity !== "success");

  return (
    <DashboardPanel
      description="Agents, tools, broken state, approvals, recent activity, and next action."
      title="Workspace home"
    >
      <div className="overflow-hidden rounded-md border border-border">
        <HealthRow
          badge={`${formatCount(activeAgents)}/${formatCount(agents.length)}`}
          detail={activeAgentNames}
          href={paths.agents}
          icon={Bot}
          label="Active agents"
          tone={activeAgents > 0 ? "success" : "warning"}
        />
        <HealthRow
          badge={formatCount(assignedTools)}
          detail={`${formatCount(enabledInstallations)} enabled MCP ${pluralize(
            enabledInstallations,
            "connection"
          )}`}
          href={installPath}
          icon={Wrench}
          label="Installed tools"
          tone={assignedTools > 0 || enabledInstallations > 0 ? "success" : "warning"}
        />
        <HealthRow
          badge={formatCount(brokenCount)}
          detail={`${formatCount(observability.summary.failedAgentRuns)} failed runs · ${formatCount(
            observability.summary.failedToolCalls
          )} failed tool calls · ${formatCount(installationAttention)} broken connections`}
          href={brokenCount > 0 ? paths.observability : paths.runtime}
          icon={brokenCount > 0 ? AlertTriangle : ShieldCheck}
          label="Broken"
          tone={brokenCount > 0 ? "danger" : "success"}
        />
        <HealthRow
          badge={formatCount(approvalCount)}
          detail={
            approvalCount > 0
              ? `${formatCount(gatewayApprovals.length)} gateway · ${formatCount(
                  waitingRuns.length
                )} agent-run`
              : "No tool approvals waiting"
          }
          href={firstApprovalHref}
          icon={PlugZap}
          label="Needs approval"
          tone={approvalCount > 0 ? "danger" : "success"}
        />
        <HealthRow
          badge={latestRun ? runStatusLabel(latestRun.status) : "None"}
          detail={
            latestRun
              ? `${latestRun.agentName} · ${formatTimestamp(
                  latestRun.finishedAt ?? latestRun.startedAt
                )}`
              : "No agent runs in this window"
          }
          href={latestRun ? runHref(agentRunsPath, latestRun.id) : agentRunsPath}
          icon={Activity}
          label="Ran recently"
          tone={latestRun ? runStatusTone(latestRun.status) : "neutral"}
        />
        <HealthRow
          badge={nextAction ? nextAction.severity : "Clear"}
          detail={nextAction?.detail ?? "No immediate workspace action needed"}
          href={nextAction?.href ?? paths.chat}
          icon={nextAction?.severity === "danger" ? AlertTriangle : ArrowRight}
          label="Do next"
          tone={nextAction?.severity ?? "success"}
        />
      </div>
    </DashboardPanel>
  );
}

function RecentRunsPanel({
  agentRunsPath,
  runs,
}: {
  agentRunsPath: string;
  runs: WorkspaceObservabilityAgentRunRow[];
}) {
  return (
    <DashboardPanel
      action={
        <Button asChild size="sm" variant="outline">
          <Link href={agentRunsPath}>
            <Activity className="size-4" />
            Runs
          </Link>
        </Button>
      }
      description="Latest agent executions in this workspace."
      title="Recent runs"
    >
      <div className="-m-4">
        {runs.length === 0 ? (
          <HealthRow
            detail="No agent runs recorded in the current window"
            href={agentRunsPath}
            icon={Activity}
            label="No recent runs"
            tone="neutral"
          />
        ) : (
          runs.slice(0, 5).map((run) => (
            <HealthRow
              badge={runStatusLabel(run.status)}
              detail={`${run.agentName} · ${formatCount(run.requests)} model ${pluralize(
                run.requests,
                "request"
              )} · ${formatTimestamp(run.finishedAt ?? run.startedAt)}`}
              href={runHref(agentRunsPath, run.id)}
              icon={run.status === "failed" ? AlertTriangle : Activity}
              key={run.id}
              label={run.triggerType || "Agent run"}
              tone={runStatusTone(run.status)}
            />
          ))
        )}
      </div>
    </DashboardPanel>
  );
}

function topToolRows(toolUsage: MCPToolUsageListResponse) {
  const rows = new Map<
    string,
    {
      calls: number;
      failed: number;
      serverName: string;
      toolName: string;
    }
  >();
  for (const call of toolUsage.toolCalls) {
    const key = `${call.serverName}:${call.toolName}`;
    const row = rows.get(key) ?? {
      calls: 0,
      failed: 0,
      serverName: call.serverName,
      toolName: call.toolName,
    };
    row.calls += 1;
    row.failed += call.isError || call.status === "failed" ? 1 : 0;
    rows.set(key, row);
  }
  return [...rows.values()].sort((first, second) => second.calls - first.calls).slice(0, 4);
}

function TopToolsPanel({ toolUsage }: { toolUsage: MCPToolUsageListResponse }) {
  const rows = topToolRows(toolUsage);

  return (
    <DashboardPanel description="Most common recent MCP tool calls." title="Tool mix">
      <div className="-m-4">
        {rows.length === 0 ? (
          <HealthRow
            detail="No recent MCP tool calls recorded"
            icon={Wrench}
            label="No tool activity"
            tone="neutral"
          />
        ) : (
          rows.map((row) => {
            const errorRate = row.calls > 0 ? (row.failed / row.calls) * 100 : 0;
            return (
              <HealthRow
                badge={formatPercent(errorRate)}
                detail={`${row.serverName} · ${formatCount(row.calls)} ${pluralize(
                  row.calls,
                  "call"
                )}`}
                icon={Wrench}
                key={`${row.serverName}:${row.toolName}`}
                label={row.toolName}
                tone={errorRate > 0 ? "warning" : "success"}
              />
            );
          })
        )}
      </div>
    </DashboardPanel>
  );
}

export function WorkspaceDashboardClient({
  agents,
  gatewayApprovals,
  installations,
  observability,
  paths,
  runtime,
  toolUsage,
  usage,
  workspace,
}: WorkspaceDashboardClientProps) {
  const chatPath = paths.chat || "/";
  const agentsPath = paths.agents || "/";
  const agentRunsPath = paths.agentRuns || "/";
  const installPath = paths.install || "/";
  const observabilityPath = paths.observability || "/";
  const runtimePath = paths.runtime || "/";
  const enabledInstallations = installations.filter(
    (installation) => installation.status === "enabled"
  ).length;
  const installationAttention = installations.filter(installationNeedsAttention).length;
  const updateCount = installations.filter((installation) => installation.updateAvailable).length;
  const activeAgents = agents.filter((agent) => agent.isActive).length;
  const assignedTools = agents.reduce((sum, agent) => sum + agent.toolCount, 0);
  const requestRate = requestSuccessRate(usage);
  const toolRate = toolSuccessRate(runtime);
  const healthScore = workspaceHealthScore({ agents, installations, runtime, usage });
  const scoreTone = healthTone(healthScore);
  const attentionItems = buildAttentionItems({
    agentRunsPath,
    agents,
    gatewayApprovals,
    installPath,
    installations,
    observability,
    observabilityPath,
    paths,
    runtime,
    runtimePath,
    usage,
    workspace,
  });

  return (
    <div className="space-y-4">
      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="p-5 md:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{workspace.currentUserRole}</Badge>
              <Badge variant={badgeVariant(scoreTone)}>Posture {healthScore}/100</Badge>
              <span className="rounded-sm border border-border bg-muted/35 px-2 py-0.5 text-xs text-muted-foreground">
                {usage.window.startDate} to {usage.window.endDate}
              </span>
            </div>
            <div className="mt-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <h2 className="text-2xl font-semibold leading-8 text-foreground md:text-3xl md:leading-10">
                  {workspace.name}
                </h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                  {activeAgents > 0
                    ? "Workspace assistant ready"
                    : "Workspace assistant not started"}
                  , {formatCount(enabledInstallations)} enabled connections,{" "}
                  {formatCount(usage.summary.requests)} model requests, and{" "}
                  {formatCount(runtime.toolCalls.total)} MCP tool calls.
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2 sm:flex-nowrap lg:justify-end">
                <Button asChild size="sm">
                  <Link href={chatPath}>
                    <MessageSquare className="size-4" />
                    Chat
                  </Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link href={installPath}>
                    <PlugZap className="size-4" />
                    Connections
                  </Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link href={observabilityPath}>
                    <BarChart3 className="size-4" />
                    Observability
                  </Link>
                </Button>
              </div>
            </div>
          </div>
          <div className="border-t border-border bg-muted/25 p-5 xl:border-l xl:border-t-0">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">Operating posture</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {attentionItems.length === 0
                    ? "No active attention items"
                    : `${attentionItems.length} signals`}
                </div>
              </div>
              <Gauge className="size-5 text-muted-foreground" />
            </div>
            <div className="mt-5">
              <SignalBar
                className="h-3"
                segments={[
                  { label: "Posture", tone: scoreTone, value: healthScore },
                  { label: "Risk", tone: "neutral", value: 100 - healthScore },
                ]}
              />
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="px-2 py-2">
                  <div className="text-lg font-semibold">{formatPercent(requestRate)}</div>
                  <div className="mt-1 text-muted-foreground">Requests</div>
                </div>
                <div className="border-x border-border px-2 py-2">
                  <div className="text-lg font-semibold">{formatPercent(toolRate)}</div>
                  <div className="mt-1 text-muted-foreground">Tools</div>
                </div>
                <div className="px-2 py-2">
                  <div className="text-lg font-semibold">{formatCount(attentionItems.length)}</div>
                  <div className="mt-1 text-muted-foreground">Actions</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <DashboardSection
        defaultOpen={attentionItems.length > 0}
        description="Broken state, approvals, and the next useful workspace action."
        id="workspace-attention"
        persistenceKey="wardn.dashboard.workspace.attention"
        summary={
          attentionItems.length === 0
            ? "Clear"
            : `${formatCount(attentionItems.length)} to review`
        }
        title="Needs attention"
      >
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <WorkspaceHomePanel
            activeAgents={activeAgents}
            agentRunsPath={agentRunsPath}
            agents={agents}
            assignedTools={assignedTools}
            attentionItems={attentionItems}
            gatewayApprovals={gatewayApprovals}
            installationAttention={installationAttention}
            installations={installations}
            installPath={installPath}
            observability={observability}
            paths={paths}
            runtime={runtime}
          />
          <AttentionPanel items={attentionItems} />
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen
        description="Reliability, spend, tool activity, and assistant coverage."
        id="workspace-overview"
        persistenceKey="wardn.dashboard.workspace.overview"
        summary="4 key metrics"
        title="Overview"
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <DashboardMetricCard
            badge={formatPercent(requestRate)}
            detail={`${formatCount(usage.summary.failed)} failed · ${formatCompact(
              usage.summary.totalTokens
            )} tokens`}
            href={observabilityPath}
            icon={Activity}
            label="Model requests"
            tone={usage.summary.failed > 0 ? "warning" : "info"}
            value={formatCompact(usage.summary.requests)}
          />
          <DashboardMetricCard
            detail={`${formatCompact(usage.summary.totalTokens)} tokens in window`}
            href={observabilityPath}
            icon={CircleDollarSign}
            label="Workspace spend"
            tone={numberValue(usage.summary.costUsd) > 0 ? "success" : "neutral"}
            value={formatCurrency(usage.summary.costUsd)}
          />
          <DashboardMetricCard
            badge={formatPercent(toolRate)}
            detail={`${formatRatioPercent(runtime.toolCalls.recentFailureRate)} recent failure · ${formatDuration(
              toolUsage.summary.averageDurationMs
            )} avg`}
            href={runtimePath}
            icon={Wrench}
            label="MCP tool calls"
            tone={runtime.toolCalls.recentFailureRate > 0 ? "warning" : "success"}
            value={formatCompact(runtime.toolCalls.total)}
          />
          <DashboardMetricCard
            badge={`${formatCount(activeAgents)}/${formatCount(agents.length)}`}
            detail={`${formatCount(
              assignedTools
            )} assigned workspace ${pluralize(assignedTools, "tool")}`}
            href={agentsPath}
            icon={Bot}
            label="Active agents"
            tone={activeAgents > 0 ? "success" : "warning"}
            value={formatCount(activeAgents)}
          />
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={
          usage.daily.length > 1 ||
          usage.byModel.length > 1 ||
          usage.byAgent.length > 1 ||
          installations.length > 1
        }
        description="Activity, runtime, model, assistant, and connection patterns."
        id="workspace-trends"
        persistenceKey="wardn.dashboard.workspace.trends"
        summary="5 visual summaries"
        title="Trends"
      >
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-3">
            <ActivityTrendChart usage={usage} />
            <RuntimePanel runtime={runtime} runtimePath={runtimePath} toolUsage={toolUsage} />
          </div>
          <div className="grid gap-5 xl:grid-cols-3">
            <ModelSpendChart rows={usage.byModel} />
            <AgentDemandChart agents={agents} rows={usage.byAgent} />
            <ConnectionMixPanel installPath={installPath} installations={installations} />
          </div>
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={false}
        description="Recent tool and run activity plus workspace destinations."
        id="workspace-details"
        persistenceKey="wardn.dashboard.workspace.details"
        summary={`${formatCount(toolUsage.toolCalls.length + observability.recentRuns.length)} events`}
        title="Recent activity and links"
      >
        <div className="space-y-5">
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <TopToolsPanel toolUsage={toolUsage} />
            <RecentRunsPanel agentRunsPath={agentRunsPath} runs={observability.recentRuns} />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
        <Link
          className="flex min-h-24 items-center justify-between gap-3 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] transition-colors hover:border-ring/35 hover:bg-muted/30"
          href={agentsPath}
        >
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Agents</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {formatCount(activeAgents)} active · {formatCount(assignedTools)} tools
            </div>
          </div>
          <Sparkles className="size-5 shrink-0 text-muted-foreground" />
        </Link>
        <Link
          className="flex min-h-24 items-center justify-between gap-3 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] transition-colors hover:border-ring/35 hover:bg-muted/30"
          href={installPath}
        >
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Connections</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {formatCount(enabledInstallations)} enabled · {formatCount(updateCount)} updates
            </div>
          </div>
          <Boxes className="size-5 shrink-0 text-muted-foreground" />
        </Link>
        <Link
          className="flex min-h-24 items-center justify-between gap-3 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] transition-colors hover:border-ring/35 hover:bg-muted/30"
          href={observabilityPath}
        >
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Observability</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {formatCount(toolUsage.summary.total)} recent tool events
            </div>
          </div>
          <ArrowRight className="size-5 shrink-0 text-muted-foreground" />
        </Link>
          </div>
        </div>
      </DashboardSection>
    </div>
  );
}
