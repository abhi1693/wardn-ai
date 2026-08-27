"use client";

import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Gauge,
  ListTree,
  Network,
  Search,
  ShieldAlert,
  Timer,
} from "lucide-react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "@/components/atoms/charts";

import { DateTimeText } from "@/components/atoms/date-time-text";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { DashboardMetricCard } from "@/components/molecules/dashboard-metric-card";
import { DashboardPanel } from "@/components/molecules/dashboard-panel";
import { DashboardSection } from "@/components/molecules/dashboard-section";
import { HealthRow } from "@/components/molecules/health-row";
import { SignalBar } from "@/components/molecules/signal-bar";
import type {
  UsageSummaryBreakdownRow,
  WorkspaceObservabilityAgentRunRow,
  WorkspaceObservabilityDashboardResponse,
  WorkspaceObservabilityTopToolRow,
} from "@/lib/api/generated/model";
import { formatUserDateBucket } from "@/lib/date-time";

type WorkspaceObservabilityDashboardClientProps = {
  dashboard: WorkspaceObservabilityDashboardResponse;
  organizationId: string;
  workspaceId: string;
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

function chartDate(value: string) {
  return formatUserDateBucket(value);
}

function shortLabel(value: string, maxLength = 24) {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}...` : value;
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

function statusBadgeVariant(status: string) {
  if (status === "failed" || status === "error") {
    return "destructive" as const;
  }
  if (status === "succeeded" || status === "completed") {
    return "success" as const;
  }
  if (status === "running") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function attentionTone(severity: string) {
  if (severity === "danger") {
    return "danger" as const;
  }
  if (severity === "warning") {
    return "warning" as const;
  }
  if (severity === "success") {
    return "success" as const;
  }
  return "info" as const;
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
            key.toLowerCase().includes("cost")
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

function runHref(organizationId: string, workspaceId: string, runId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/agent-runs/${encodeURIComponent(runId)}`;
}

function attentionHref(basePath: string, href?: string) {
  if (!href) {
    return undefined;
  }
  return href.startsWith("/") ? href : `${basePath}/${href}`;
}

function ActivityTrend({ dashboard }: { dashboard: WorkspaceObservabilityDashboardResponse }) {
  const data = dashboard.activity.map((point) => ({
    costUsd: numberValue(point.costUsd),
    dateLabel: chartDate(point.date),
    requests: point.requests,
    toolCalls: point.toolCalls,
    totalTokens: point.totalTokens,
  }));

  return (
    <DashboardPanel
      className="xl:col-span-2"
      description={`${dashboard.window.startDate} to ${dashboard.window.endDate}`}
      title="Agent activity"
    >
      {data.length < 2 ? (
        <EmptyChart
          label={
            data[0]
              ? `${data[0].dateLabel}: ${formatCount(data[0].requests)} model calls, ${formatCount(
                  data[0].toolCalls
                )} tool calls, ${formatCount(data[0].totalTokens)} tokens, ${formatCurrency(
                  data[0].costUsd
                )}. Add another day to show a trend.`
              : "No workspace activity recorded in this window."
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
                name="Model calls"
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

function AttentionPanel({
  basePath,
  dashboard,
}: {
  basePath: string;
  dashboard: WorkspaceObservabilityDashboardResponse;
}) {
  return (
    <DashboardPanel
      description="Failures, slow paths, and audit gaps ranked for triage."
      title="Needs attention"
    >
      <div className="overflow-hidden rounded-md border border-border">
        {dashboard.attention.map((item) => (
          <HealthRow
            detail={item.detail}
            href={attentionHref(basePath, item.href)}
            key={item.key}
            label={item.label}
            tone={attentionTone(item.severity)}
          />
        ))}
      </div>
    </DashboardPanel>
  );
}

function TopToolsPanel({ tools }: { tools: WorkspaceObservabilityTopToolRow[] }) {
  const data = tools.slice(0, 6).map((tool) => ({
    failed: tool.failed,
    name: shortLabel(tool.toolName, 22),
    p95: tool.p95DurationMs ?? 0,
    total: tool.calls,
  }));

  return (
    <DashboardPanel description="Failure volume and p95 latency by MCP tool." title="Tool hotspots">
      {tools.length === 0 ? (
        <EmptyChart label="No MCP tool calls recorded." />
      ) : (
        <div className="space-y-5">
          {data.length > 1 ? (
            <div className="h-64">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={data} margin={{ left: 0, right: 12, top: 10 }}>
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
                  <Bar dataKey="total" fill="#0891b2" name="Calls" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="failed" fill="#dc2626" name="Failed" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyChart
              label={`${data[0].name}: ${formatCount(data[0].total)} calls, ${formatCount(
                data[0].failed
              )} failed, p95 ${formatDuration(data[0].p95)}.`}
            />
          )}
          <div className="overflow-hidden rounded-md border border-border">
            {tools.slice(0, 5).map((tool) => (
              <HealthRow
                badge={`${formatPercent(tool.errorRate)} errors`}
                detail={`${tool.serverName} / p95 ${formatDuration(tool.p95DurationMs)}`}
                key={tool.id}
                label={tool.toolName}
                tone={tool.failed > 0 ? "warning" : "success"}
              />
            ))}
          </div>
        </div>
      )}
    </DashboardPanel>
  );
}

function BreakdownPanel({
  description,
  rows,
  title,
}: {
  description: string;
  rows: UsageSummaryBreakdownRow[];
  title: string;
}) {
  return (
    <DashboardPanel description={description} title={title}>
      {rows.length === 0 ? (
        <div className="flex min-h-48 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
          No usage recorded.
        </div>
      ) : (
        <div className="space-y-4">
          {rows.slice(0, 6).map((row) => (
            <div key={row.id}>
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="min-w-0 truncate font-medium">{row.label}</span>
                <span className="shrink-0 font-mono text-muted-foreground">
                  {formatCurrency(row.costUsd)}
                </span>
              </div>
              <SignalBar
                className="mt-2"
                segments={[
                  { label: `${row.requests} model calls`, tone: "info", value: row.requests },
                  { label: `${row.toolCalls} tool calls`, tone: "success", value: row.toolCalls },
                ]}
              />
              <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span>{formatCount(row.totalTokens)} tokens</span>
                <span>{formatCount(row.toolCalls)} tools</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </DashboardPanel>
  );
}

function RunsTable({
  organizationId,
  runs,
  workspaceId,
}: {
  organizationId: string;
  runs: WorkspaceObservabilityAgentRunRow[];
  workspaceId: string;
}) {
  return (
    <DashboardPanel
      className="xl:col-span-2"
      description="Recent agent turns with model, tool, identity, trace, and outcome signals."
      title="Agent turn timeline"
    >
      {runs.length === 0 ? (
        <div className="flex min-h-72 flex-col items-center justify-center rounded-md border border-dashed border-border text-center">
          <Search className="mb-3 size-6 text-muted-foreground" />
          <div className="text-sm font-medium">No agent turns in this window</div>
          <div className="mt-1 max-w-md text-sm text-muted-foreground">
            Runs will appear after workspace agents handle chat, scheduled, or provider-triggered
            work.
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Model</TableHead>
                <TableHead className="text-right">Tools</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead className="text-right">Trace</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="min-w-56 align-top">
                    <div className="font-medium">{run.agentName}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <DateTimeText fallback="" value={run.startedAt} />
                      <span>{run.triggerType}</span>
                    </div>
                    {run.error ? (
                      <div className="mt-1 max-w-72 truncate text-xs text-muted-foreground">
                        {run.error}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="min-w-44 align-top">
                    <div>{run.triggeredByDisplayName}</div>
                    {run.triggeredByEmail ? (
                      <div className="mt-1 text-xs text-muted-foreground">
                        {run.triggeredByEmail}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="align-top">
                    <Badge variant={statusBadgeVariant(run.status)}>{run.status}</Badge>
                  </TableCell>
                  <TableCell className="text-right align-top">
                    <div>{formatCount(run.requests)} calls</div>
                    <div className="text-xs text-muted-foreground">
                      {formatCount(run.totalTokens)} tokens
                    </div>
                  </TableCell>
                  <TableCell className="text-right align-top">
                    <div>{formatCount(run.toolCalls)} calls</div>
                    <div className="text-xs text-muted-foreground">
                      {formatCount(run.failedToolCalls)} failed
                    </div>
                  </TableCell>
                  <TableCell className="text-right align-top font-mono">
                    {formatCurrency(run.costUsd)}
                  </TableCell>
                  <TableCell className="text-right align-top">
                    <Button asChild size="sm" variant="outline">
                      <Link href={runHref(organizationId, workspaceId, run.id)}>
                        <ListTree className="size-4" />
                        Open
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </DashboardPanel>
  );
}

export function WorkspaceObservabilityDashboardClient({
  dashboard,
  organizationId,
  workspaceId,
}: WorkspaceObservabilityDashboardClientProps) {
  const summary = dashboard.summary;
  const basePath = `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}`;
  const attributionTotal =
    summary.attributedToolCalls +
    summary.unattributedToolCalls +
    summary.attributedLlmCalls +
    summary.unattributedLlmCalls;
  const attributedTotal = summary.attributedToolCalls + summary.attributedLlmCalls;
  const attentionCount = dashboard.attention.filter(
    (item) => item.severity !== "success"
  ).length;

  return (
    <div className="space-y-4">
      <DashboardSection
        defaultOpen={attentionCount > 0}
        description="Failures, slow paths, and audit gaps ranked for triage."
        id="observability-attention"
        persistenceKey="wardn.dashboard.observability.attention"
        summary={attentionCount === 0 ? "Clear" : `${formatCount(attentionCount)} to review`}
        title="Needs attention"
      >
        <AttentionPanel basePath={basePath} dashboard={dashboard} />
      </DashboardSection>

      <DashboardSection
        defaultOpen
        description="Health, activity, cost, and attribution at a glance."
        id="observability-overview"
        persistenceKey="wardn.dashboard.observability.overview"
        summary="5 key metrics"
        title="Overview"
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <DashboardMetricCard
            detail={`${summary.failedAgentRuns} failed, ${summary.runningAgentRuns} running`}
            icon={ShieldAlert}
            label="Health"
            tone={healthTone(summary.healthScore)}
            value={`${summary.healthScore}`}
          />
          <DashboardMetricCard
            detail={`${formatPercent(summary.requestSuccessRate)} model success`}
            icon={Bot}
            label="Agent turns"
            tone={summary.failedAgentRuns > 0 ? "warning" : "success"}
            value={formatCount(summary.agentRuns)}
          />
          <DashboardMetricCard
            detail={`${formatCount(summary.failedToolCalls)} failed, p95 ${formatDuration(
              summary.p95ToolDurationMs
            )}`}
            icon={Network}
            label="Tool calls"
            tone={summary.failedToolCalls > 0 ? "warning" : "info"}
            value={formatCount(summary.toolCalls)}
          />
          <DashboardMetricCard
            detail={`${formatCount(summary.totalTokens)} tokens`}
            icon={CircleDollarSign}
            label="Model cost"
            tone={numberValue(summary.costUsd) > 0 ? "info" : "neutral"}
            value={formatCurrency(summary.costUsd)}
          />
          <DashboardMetricCard
            detail={`${formatCount(attributedTotal)} of ${formatCount(attributionTotal)} events`}
            icon={CheckCircle2}
            label="Attribution"
            tone={summary.unattributedToolCalls + summary.unattributedLlmCalls > 0 ? "warning" : "success"}
            value={
              attributionTotal > 0
                ? formatPercent((attributedTotal / attributionTotal) * 100)
                : "100.0%"
            }
          />
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={dashboard.activity.length > 1}
        description="Agent request, tool, and cost movement across the selected window."
        id="observability-trends"
        persistenceKey="wardn.dashboard.observability.trends"
        summary={`${formatCount(dashboard.activity.length)} data points`}
        title="Trends"
      >
        <ActivityTrend dashboard={dashboard} />
      </DashboardSection>

      <DashboardSection
        defaultOpen={false}
        description="Runs, runtime posture, hotspots, attribution, and outcomes."
        id="observability-details"
        persistenceKey="wardn.dashboard.observability.details"
        summary={`${formatCount(
          dashboard.recentRuns.length + dashboard.topTools.length + dashboard.topModels.length
        )} records`}
        title="Detailed analysis"
      >
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-3">
            <RunsTable
              organizationId={organizationId}
              runs={dashboard.recentRuns}
              workspaceId={workspaceId}
            />
            <DashboardPanel description="Runtime and in-flight execution signals." title="Runtime posture">
              <div className="grid gap-3 text-sm">
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Activity className="size-4" />
                      Active sessions
                    </span>
                    <span className="font-mono">{formatCount(summary.activeRuntimeSessions)}</span>
                  </div>
                </div>
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <AlertTriangle className="size-4" />
                      Sessions needing review
                    </span>
                    <span className="font-mono">
                      {formatCount(summary.runtimeSessionsNeedingAttention)}
                    </span>
                  </div>
                </div>
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Timer className="size-4" />
                      Average tool latency
                    </span>
                    <span className="font-mono">{formatDuration(summary.averageToolDurationMs)}</span>
                  </div>
                </div>
                <div className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Clock3 className="size-4" />
                      Running tools
                    </span>
                    <span className="font-mono">{formatCount(summary.runningToolCalls)}</span>
                  </div>
                </div>
              </div>
            </DashboardPanel>
          </div>
          <div className="grid gap-5 xl:grid-cols-3">
            <TopToolsPanel tools={dashboard.topTools} />
            <BreakdownPanel
              description="Model routes by spend, token volume, and call count."
              rows={dashboard.topModels}
              title="Model spend"
            />
            <BreakdownPanel
              description="Users driving model and tool activity."
              rows={dashboard.topUsers}
              title="Actor attribution"
            />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <BreakdownPanel
              description="Agents generating requests and MCP calls."
              rows={dashboard.topAgents}
              title="Agent workload"
            />
            <DashboardPanel description="Outcome mix for this workspace window." title="Outcome mix">
          <div className="space-y-5">
            <div>
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-medium">Model calls</span>
                <span className="font-mono text-muted-foreground">
                  {formatPercent(summary.requestSuccessRate)}
                </span>
              </div>
              <SignalBar
                className="mt-2"
                segments={[
                  {
                    label: `${summary.requests - summary.failedRequests} succeeded`,
                    tone: "success",
                    value: Math.max(summary.requests - summary.failedRequests, 0),
                  },
                  {
                    label: `${summary.failedRequests} failed`,
                    tone: "danger",
                    value: summary.failedRequests,
                  },
                ]}
              />
            </div>
            <div>
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-medium">Tool calls</span>
                <span className="font-mono text-muted-foreground">
                  {formatPercent(summary.toolSuccessRate)}
                </span>
              </div>
              <SignalBar
                className="mt-2"
                segments={[
                  {
                    label: `${summary.toolCalls - summary.failedToolCalls} succeeded`,
                    tone: "success",
                    value: Math.max(summary.toolCalls - summary.failedToolCalls, 0),
                  },
                  {
                    label: `${summary.failedToolCalls} failed`,
                    tone: "danger",
                    value: summary.failedToolCalls,
                  },
                  {
                    label: `${summary.runningToolCalls} running`,
                    tone: "info",
                    value: summary.runningToolCalls,
                  },
                ]}
              />
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Gauge className="size-4" />
                  p95 latency
                </div>
                <div className="mt-2 text-lg font-semibold">
                  {formatDuration(summary.p95ToolDurationMs)}
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <ListTree className="size-4" />
                  Trace coverage
                </div>
                <div className="mt-2 text-lg font-semibold">
                  {formatCount(dashboard.recentRuns.filter((run) => run.traceId).length)}
                </div>
              </div>
            </div>
          </div>
            </DashboardPanel>
          </div>
        </div>
      </DashboardSection>
    </div>
  );
}
