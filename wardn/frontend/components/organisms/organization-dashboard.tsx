"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Boxes,
  CircleDollarSign,
  Clock3,
  Gauge,
  KeyRound,
  Network,
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
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "@/components/atoms/charts";

import { StatusDot } from "@/components/atoms/status-dot";
import { DashboardMetricCard } from "@/components/molecules/dashboard-metric-card";
import { DashboardPanel } from "@/components/molecules/dashboard-panel";
import { DashboardSection } from "@/components/molecules/dashboard-section";
import { HealthRow } from "@/components/molecules/health-row";
import { SignalBar } from "@/components/molecules/signal-bar";
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
import type {
  OrganizationDashboardResponse,
  OrganizationDashboardToolRow,
  OrganizationDashboardWorkspaceRow,
  OrganizationRead,
  UsageSummaryBreakdownRow,
} from "@/lib/api/generated/model";
import { formatUserDateBucket, formatUserShortDate } from "@/lib/date-time";

type OrganizationDashboardProps = {
  dashboard: OrganizationDashboardResponse;
  organization: OrganizationRead;
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
const chartColors = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#0891b2", "#7c3aed"];

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
    maximumFractionDigits: Number(value ?? 0) >= 1 ? 2 : 4,
    minimumFractionDigits: 2,
    style: "currency",
  }).format(numberValue(value));
}

function formatPercent(value: number | null | undefined) {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "n/a";
}

function formatDuration(value: number | null | undefined) {
  if (typeof value !== "number") {
    return "n/a";
  }
  if (value < 1000) {
    return `${formatCount(value)} ms`;
  }
  return `${(value / 1000).toFixed(1)} s`;
}

function formatDate(value: string | null | undefined) {
  return formatUserShortDate(value, "No activity");
}

function shortLabel(value: string, maxLength = 22) {
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

function severityTone(severity: string) {
  if (severity === "danger") {
    return "danger" as const;
  }
  if (severity === "warning") {
    return "warning" as const;
  }
  return "info" as const;
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

function chartDate(value: string) {
  return formatUserDateBucket(value);
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

function CostTrendChart({ dashboard }: { dashboard: OrganizationDashboardResponse }) {
  const data = dashboard.daily.map((point) => ({
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
      title="Activity trend"
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
              : "No usage recorded in this window."
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
              <Legend />
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
                fillOpacity={0.12}
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
  const data = rows.slice(0, 8).map((row) => ({
    costUsd: numberValue(row.costUsd),
    name: shortLabel(row.label, 28),
    requests: row.requests,
    totalTokens: row.totalTokens,
  }));

  return (
    <DashboardPanel description="Highest cost model routes in the selected window." title="Model spend">
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
                width={126}
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

function WorkspaceDemandChart({ rows }: { rows: OrganizationDashboardWorkspaceRow[] }) {
  const data = rows.slice(0, 8).map((row) => ({
    costUsd: numberValue(row.costUsd),
    name: shortLabel(row.name, 24),
    requests: row.requests,
    toolCalls: row.toolCalls,
  }));

  return (
    <DashboardPanel description="Workspaces ranked by requests and MCP activity." title="Workspace demand">
      {data.length < 2 ? (
        <EmptyChart
          label={
            data[0]
              ? `${data[0].name}: ${formatCount(data[0].requests)} requests, ${formatCount(
                  data[0].toolCalls
                )} tool calls, ${formatCurrency(data[0].costUsd)}.`
              : "No workspace activity recorded."
          }
        />
      ) : (
        <div className="h-72">
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
                tickMargin={10}
              />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Bar dataKey="requests" fill="#0891b2" name="Requests" radius={[4, 4, 0, 0]} />
              <Bar dataKey="toolCalls" fill="#f59e0b" name="Tool calls" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </DashboardPanel>
  );
}

function RuntimeMixChart({ dashboard }: { dashboard: OrganizationDashboardResponse }) {
  const data = dashboard.runtimeMix.map((row, index) => ({
    ...row,
    fill: chartColors[index % chartColors.length],
    name: row.label,
    value: row.total,
  }));

  return (
    <DashboardPanel description="Installed MCP server runtime distribution." title="Runtime mix">
      {data.length < 2 ? (
        <EmptyChart
          label={
            data[0]
              ? `${data[0].name}: ${formatCount(data[0].total)} installed, ${formatCount(
                  data[0].enabled
                )} enabled, ${formatCount(data[0].attention)} need review.`
              : "No MCP runtimes installed."
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
          <div className="h-56">
            <ResponsiveContainer height="100%" width="100%">
              <PieChart>
                <Tooltip content={<ChartTooltip />} />
                <Pie
                  cx="50%"
                  cy="50%"
                  data={data}
                  dataKey="value"
                  innerRadius={58}
                  nameKey="name"
                  outerRadius={88}
                  paddingAngle={2}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-3 self-center">
            {dashboard.runtimeMix.map((row, index) => (
              <div className="space-y-2" key={row.runtime}>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className="size-2 rounded-full"
                      style={{ backgroundColor: chartColors[index % chartColors.length] }}
                    />
                    <span className="truncate font-medium">{row.label}</span>
                  </div>
                  <span className="font-mono text-muted-foreground">{formatCount(row.total)}</span>
                </div>
                <SignalBar
                  segments={[
                    { label: `${row.enabled} enabled`, tone: "success", value: row.enabled },
                    { label: `${row.attention} review`, tone: "warning", value: row.attention },
                    {
                      label: "Other",
                      tone: "neutral",
                      value: Math.max(row.total - row.enabled - row.attention, 0),
                    },
                  ]}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </DashboardPanel>
  );
}

function WorkspaceTable({
  organizationId,
  rows,
}: {
  organizationId: string;
  rows: OrganizationDashboardWorkspaceRow[];
}) {
  return (
    <DashboardPanel
      action={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${encodeURIComponent(organizationId)}/workspaces`}>
            <Boxes className="size-4" />
            All
          </Link>
        </Button>
      }
      description="Spend, demand, and MCP readiness by workspace."
      title="Workspace hotspots"
    >
      <div className="-mx-4 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Workspace</TableHead>
              <TableHead className="text-right">Requests</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead className="text-right">Tools</TableHead>
              <TableHead className="text-right">Review</TableHead>
              <TableHead className="text-right">Open</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell className="h-24 text-center text-muted-foreground" colSpan={6}>
                  No workspace activity recorded.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const attention =
                  row.serversNeedingAttention + row.runtimeSessionsNeedingAttention;
                return (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="min-w-44">
                        <div className="flex items-center gap-2 font-medium">
                          <StatusDot tone={row.status === "active" ? "success" : "warning"} />
                          {row.name}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {row.slug} · {formatDate(row.latestActivityAt)}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCount(row.requests)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCurrency(row.costUsd)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCount(row.toolCount)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge variant={attention > 0 ? "destructive" : "outline"}>
                        {formatCount(attention)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button aria-label={`Open ${row.name}`} asChild size="icon" variant="ghost">
                        <Link
                          href={`/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
                            row.id
                          )}/chat`}
                        >
                          <ArrowRight className="size-4" />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </DashboardPanel>
  );
}

function ToolTable({ rows }: { rows: OrganizationDashboardToolRow[] }) {
  return (
    <DashboardPanel description="Most active MCP tools with reliability and latency." title="Tool reliability">
      <div className="-mx-4 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tool</TableHead>
              <TableHead>Workspace</TableHead>
              <TableHead className="text-right">Calls</TableHead>
              <TableHead className="text-right">Error rate</TableHead>
              <TableHead className="text-right">p95</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell className="h-24 text-center text-muted-foreground" colSpan={5}>
                  No MCP tool calls recorded.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <div className="min-w-52">
                      <div className="font-medium">{row.toolName}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{row.serverName}</div>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{row.workspaceName}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatCount(row.calls)}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant={row.errorRate > 0 ? "destructive" : "outline"}>
                      {formatPercent(row.errorRate)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatDuration(row.p95DurationMs)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </DashboardPanel>
  );
}

export function OrganizationDashboard({ dashboard, organization }: OrganizationDashboardProps) {
  const summary = dashboard.summary;
  const scoreTone = healthTone(summary.healthScore);
  const budgetDetail =
    summary.monthlyBudgetUsd && summary.budgetUtilizationPercent !== null
      ? `${formatPercent(summary.budgetUtilizationPercent)} of ${formatCurrency(
          summary.monthlyBudgetUsd
        )}`
      : "No monthly budget configured";
  const attentionCount = dashboard.attention.length;
  const pendingActionCount =
    summary.pendingInvitations +
    summary.pendingToolApprovals +
    summary.failedScheduledTasks +
    summary.runtimeSessionsNeedingAttention +
    summary.installationsNeedingCredentials +
    summary.stalledAgentRuns;

  return (
    <div className="space-y-4">
      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="p-5 md:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{organization.currentUserRole}</Badge>
              <Badge variant={badgeVariant(scoreTone)}>{summary.healthScore}/100 health</Badge>
              <span className="text-sm text-muted-foreground">
                {dashboard.window.startDate} to {dashboard.window.endDate}
              </span>
            </div>
            <div className="mt-5 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div className="min-w-0">
                <h2 className="text-2xl font-semibold leading-8 text-foreground md:text-3xl md:leading-10">
                  {organization.name}
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  {formatCount(summary.activeWorkspaces)} active workspaces,{" "}
                  {formatCount(summary.enabledServers)} enabled MCP servers,{" "}
                  {formatCount(summary.activeAgents)} active agents
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button asChild size="sm" variant="outline">
                  <Link href={`/org/${encodeURIComponent(organization.id)}/usage`}>
                    <BarChart3 className="size-4" />
                    Usage
                  </Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link href={`/org/${encodeURIComponent(organization.id)}/catalog`}>
                    <BookOpen className="size-4" />
                    Catalog
                  </Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link href={`/organizations/${encodeURIComponent(organization.id)}/settings`}>
                    <ShieldCheck className="size-4" />
                    Settings
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
                  {attentionCount === 0 ? "No active attention items" : `${attentionCount} signals`}
                </div>
              </div>
              <Gauge className="size-5 text-muted-foreground" />
            </div>
            <div className="mt-5">
              <SignalBar
                className="h-3"
                segments={[
                  { label: "Health", tone: scoreTone, value: summary.healthScore },
                  { label: "Risk", tone: "neutral", value: 100 - summary.healthScore },
                ]}
              />
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="px-2 py-2">
                  <div className="text-lg font-semibold">{formatPercent(summary.requestSuccessRate)}</div>
                  <div className="mt-1 text-muted-foreground">Requests</div>
                </div>
                <div className="border-x border-border px-2 py-2">
                  <div className="text-lg font-semibold">{formatPercent(summary.toolSuccessRate)}</div>
                  <div className="mt-1 text-muted-foreground">Tools</div>
                </div>
                <div className="px-2 py-2">
                  <div className="text-lg font-semibold">{formatCount(pendingActionCount)}</div>
                  <div className="mt-1 text-muted-foreground">Actions</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <DashboardSection
        defaultOpen={attentionCount > 0}
        description="Pending approvals, failures, credentials, budget, and runtime risks."
        id="organization-attention"
        persistenceKey="wardn.dashboard.organization.attention"
        summary={attentionCount === 0 ? "Clear" : `${formatCount(attentionCount)} to review`}
        title="Needs attention"
      >
        <div className="overflow-hidden rounded-md border border-border">
          {dashboard.attention.length === 0 ? (
            <HealthRow
              badge="Clear"
              detail="No pending approvals, failed tasks, credential gaps, or runtime risks detected"
              icon={ShieldCheck}
              label="No active items"
              tone="success"
            />
          ) : (
            dashboard.attention.map((item) => {
              const tone = severityTone(item.severity);
              return (
                <HealthRow
                  badge={item.severity}
                  detail={item.detail}
                  href={item.href || undefined}
                  icon={tone === "danger" ? AlertTriangle : Activity}
                  key={item.key}
                  label={item.label}
                  tone={tone}
                />
              );
            })
          )}
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen
        description="Cost, request, tool, and MCP coverage at a glance."
        id="organization-overview"
        persistenceKey="wardn.dashboard.organization.overview"
        summary="4 key metrics"
        title="Overview"
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <DashboardMetricCard
            detail={`${formatCurrency(summary.costUsd)} actual · ${budgetDetail}`}
            href={`/org/${encodeURIComponent(organization.id)}/usage`}
            icon={CircleDollarSign}
            label="Monthly run-rate"
            tone={summary.budgetUtilizationPercent && summary.budgetUtilizationPercent >= 80 ? "warning" : "success"}
            value={formatCurrency(summary.projectedMonthlyCostUsd)}
          />
          <DashboardMetricCard
            badge={formatPercent(summary.requestSuccessRate)}
            detail={`${formatCount(summary.failedRequests)} failed · ${formatCompact(
              summary.totalTokens
            )} tokens`}
            icon={Activity}
            label="Model requests"
            tone={summary.failedRequests > 0 ? "warning" : "info"}
            value={formatCompact(summary.requests)}
          />
          <DashboardMetricCard
            badge={formatPercent(summary.toolSuccessRate)}
            detail={`${formatDuration(summary.averageToolDurationMs)} avg · ${formatCount(
              summary.tools
            )} tools`}
            icon={Wrench}
            label="MCP tool calls"
            tone={summary.toolSuccessRate >= 98 ? "success" : "warning"}
            value={formatCompact(summary.toolCalls)}
          />
          <DashboardMetricCard
            detail={`${formatCount(summary.enabledServers)}/${formatCount(
              summary.installedServers
            )} enabled · ${formatCount(summary.serverUpdates)} updates`}
            href={`/org/${encodeURIComponent(organization.id)}/catalog`}
            icon={ServerCog}
            label="MCP coverage"
            tone={summary.serversNeedingAttention > 0 ? "danger" : "success"}
            value={formatCompact(summary.installedServers)}
          />
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={
          dashboard.daily.length > 1 ||
          dashboard.topModels.length > 1 ||
          dashboard.workspaces.length > 1 ||
          dashboard.runtimeMix.length > 1
        }
        description="Activity, spend, demand, and runtime distribution."
        id="organization-trends"
        persistenceKey="wardn.dashboard.organization.trends"
        summary="4 visual summaries"
        title="Trends"
      >
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-3">
            <CostTrendChart dashboard={dashboard} />
            <ModelSpendChart rows={dashboard.topModels} />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <WorkspaceDemandChart rows={dashboard.workspaces} />
            <RuntimeMixChart dashboard={dashboard} />
          </div>
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={false}
        description="Workspace and tool tables plus readiness controls."
        id="organization-details"
        persistenceKey="wardn.dashboard.organization.details"
        summary={`${formatCount(dashboard.workspaces.length + dashboard.topTools.length)} rows`}
        title="Detailed breakdowns"
      >
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-5">
            <WorkspaceTable organizationId={organization.id} rows={dashboard.workspaces} />
            <ToolTable rows={dashboard.topTools} />
          </div>
          <div className="min-w-0 space-y-5">
          <DashboardPanel description="Catalog sync and model credential coverage." title="Readiness">
            <div className="-m-4">
              <HealthRow
                badge={`${formatCount(summary.activeProviderCredentials)}/${formatCount(
                  summary.providerCredentials
                )}`}
                detail={
                  dashboard.providers.length === 0
                    ? "No provider credentials configured"
                    : dashboard.providers
                        .map((provider) => `${provider.provider}: ${provider.active}/${provider.total}`)
                        .join(", ")
                }
                icon={KeyRound}
                label="Model providers"
                tone={summary.activeProviderCredentials > 0 ? "success" : "danger"}
              />
              <HealthRow
                badge={`${formatCount(dashboard.catalog.synced)}/${formatCount(
                  dashboard.catalog.enabled
                )}`}
                detail={`${formatCount(dashboard.catalog.errors)} errors · ${formatCount(
                  dashboard.catalog.stale
                )} stale`}
                icon={BookOpen}
                label="Catalog sync"
                tone={dashboard.catalog.errors > 0 ? "warning" : "success"}
              />
              <HealthRow
                badge={`${formatCount(summary.activeRuntimeSessions)}/${formatCount(
                  summary.runtimeSessions
                )}`}
                detail={`${formatCount(
                  summary.runtimeSessionsNeedingAttention
                )} sessions need review`}
                icon={Network}
                label="Runtime sessions"
                tone={summary.runtimeSessionsNeedingAttention > 0 ? "warning" : "success"}
              />
              <HealthRow
                badge={`${formatCount(summary.activeAgents)}/${formatCount(summary.agents)}`}
                detail={`${formatCount(summary.tools)} active tool schemas available`}
                icon={Sparkles}
                label="Agent coverage"
                tone={summary.activeAgents > 0 ? "success" : "warning"}
              />
              <HealthRow
                badge={formatCount(summary.usageBudgets)}
                detail={`${formatCount(summary.resourceLimits)} resource limits configured`}
                icon={Clock3}
                label="Controls"
                tone={summary.usageBudgets > 0 || summary.resourceLimits > 0 ? "info" : "neutral"}
              />
            </div>
          </DashboardPanel>
          </div>
        </div>
      </DashboardSection>
    </div>
  );
}
