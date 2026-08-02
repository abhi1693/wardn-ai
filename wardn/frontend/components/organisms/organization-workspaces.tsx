"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Boxes,
  CircleDollarSign,
  MessageSquare,
  PlugZap,
  Search,
  ServerCog,
  Sparkles,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { StatusDot } from "@/components/atoms/status-dot";
import { DashboardMetricCard } from "@/components/molecules/dashboard-metric-card";
import { DashboardPanel } from "@/components/molecules/dashboard-panel";
import { HealthRow } from "@/components/molecules/health-row";
import { SignalBar } from "@/components/molecules/signal-bar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  OrganizationDashboardResponse,
  OrganizationDashboardWorkspaceRow,
  OrganizationRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { setSelectionCookie } from "@/lib/selection-cookies";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";
import { cn } from "@/lib/utils";

type OrganizationWorkspacesProps = {
  dashboard: OrganizationDashboardResponse;
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

type WorkspaceOverviewRow = OrganizationDashboardWorkspaceRow & {
  activityScore: number;
  attentionCount: number;
  createdAt: string;
  currentUserRole: string;
  description: string;
  guardrailDefaultDeny: boolean;
  hasActivity: boolean;
  hasMcp: boolean;
  healthScore: number;
  metricsMissing: boolean;
  requestSuccessRate: number;
  toolSuccessRate: number;
  updatedAt: string;
};

type WorkspaceFilter = "active" | "all" | "attention" | "connected";
type WorkspaceSort = "activity" | "attention" | "cost" | "name" | "recent";

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
const chartColors = {
  active: "#16a34a",
  attention: "#dc2626",
  cost: "#2563eb",
  requests: "#0891b2",
  toolCalls: "#f59e0b",
};

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

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "No activity";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

function shortLabel(value: string, maxLength = 20) {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}...` : value;
}

function percent(part: number, total: number) {
  if (total <= 0) {
    return 0;
  }
  return (part / total) * 100;
}

function successRate(failed: number, total: number) {
  if (total <= 0) {
    return 100;
  }
  return Math.max(0, Math.min(100, percent(total - failed, total)));
}

function attentionCount(row: OrganizationDashboardWorkspaceRow) {
  let count = 0;
  if (row.status !== "active") {
    count += 1;
  }
  if (row.failedRequests > 0) {
    count += 1;
  }
  if (row.failedToolCalls > 0) {
    count += 1;
  }
  if (row.serversNeedingAttention > 0) {
    count += 1;
  }
  if (row.runtimeSessionsNeedingAttention > 0) {
    count += 1;
  }
  if (row.serverUpdates > 0) {
    count += 1;
  }
  return count;
}

function workspaceHealth(row: OrganizationDashboardWorkspaceRow) {
  let score = 100;
  if (row.status !== "active") {
    score -= 30;
  }
  score -= Math.min(30, percent(row.failedRequests, row.requests) * 0.45);
  score -= Math.min(25, percent(row.failedToolCalls, row.toolCalls) * 0.45);
  score -= Math.min(20, row.serversNeedingAttention * 8);
  score -= Math.min(15, row.runtimeSessionsNeedingAttention * 7);
  score -= Math.min(8, row.serverUpdates * 2);
  if (row.installations === 0) {
    score -= 8;
  }
  if (row.agents === 0) {
    score -= 4;
  }
  return Math.max(0, Math.min(100, Math.round(score)));
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

function workspaceStatusTone(row: WorkspaceOverviewRow) {
  if (row.status !== "active" || row.serversNeedingAttention > 0) {
    return "danger" as const;
  }
  if (
    row.failedRequests > 0 ||
    row.failedToolCalls > 0 ||
    row.runtimeSessionsNeedingAttention > 0 ||
    row.serverUpdates > 0
  ) {
    return "warning" as const;
  }
  return "success" as const;
}

function badgeVariant(tone: "danger" | "success" | "warning") {
  if (tone === "danger") {
    return "destructive" as const;
  }
  if (tone === "success") {
    return "success" as const;
  }
  return "secondary" as const;
}

function workspacePath(organizationId: string, workspaceId: string, suffix = "/chat") {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}${suffix}`;
}

function workspaceSettingsPath(organizationId: string, workspaceId: string) {
  return `/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
    workspaceId
  )}/settings`;
}

function emptyDashboardRow(workspace: WorkspaceRead): OrganizationDashboardWorkspaceRow {
  return {
    activeAgents: 0,
    activeRuntimeSessions: 0,
    agents: 0,
    costUsd: "0",
    enabledInstallations: 0,
    failedRequests: 0,
    failedToolCalls: 0,
    id: workspace.id,
    installations: 0,
    latestActivityAt: null,
    name: workspace.name,
    requests: 0,
    runtimeSessions: 0,
    runtimeSessionsNeedingAttention: 0,
    serverUpdates: 0,
    serversNeedingAttention: 0,
    slug: workspace.slug,
    status: workspace.status,
    toolCalls: 0,
    toolCount: 0,
    totalTokens: 0,
  };
}

function mergeWorkspaceRows(
  workspaces: WorkspaceRead[],
  dashboardRows: OrganizationDashboardWorkspaceRow[]
) {
  const dashboardRowById = new Map(dashboardRows.map((row) => [row.id, row]));
  return workspaces.map((workspace) => {
    const metrics = dashboardRowById.get(workspace.id) ?? emptyDashboardRow(workspace);
    const row: WorkspaceOverviewRow = {
      ...metrics,
      createdAt: workspace.createdAt,
      currentUserRole: workspace.currentUserRole,
      description: workspace.description,
      guardrailDefaultDeny: workspace.guardrailDefaultDeny,
      metricsMissing: !dashboardRowById.has(workspace.id),
      updatedAt: workspace.updatedAt,
      activityScore: metrics.requests + metrics.toolCalls + metrics.totalTokens / 1000,
      attentionCount: attentionCount(metrics),
      hasActivity: metrics.requests > 0 || metrics.toolCalls > 0,
      hasMcp: metrics.installations > 0 || metrics.toolCount > 0,
      healthScore: workspaceHealth(metrics),
      requestSuccessRate: successRate(metrics.failedRequests, metrics.requests),
      toolSuccessRate: successRate(metrics.failedToolCalls, metrics.toolCalls),
    };
    return row;
  });
}

function sortWorkspaceRows(rows: WorkspaceOverviewRow[], sort: WorkspaceSort) {
  return [...rows].sort((a, b) => {
    if (sort === "attention") {
      return (
        b.attentionCount - a.attentionCount ||
        a.healthScore - b.healthScore ||
        b.activityScore - a.activityScore ||
        a.name.localeCompare(b.name)
      );
    }
    if (sort === "cost") {
      return (
        numberValue(b.costUsd) - numberValue(a.costUsd) ||
        b.requests - a.requests ||
        a.name.localeCompare(b.name)
      );
    }
    if (sort === "name") {
      return a.name.localeCompare(b.name);
    }
    if (sort === "recent") {
      return (
        new Date(b.latestActivityAt ?? b.updatedAt).getTime() -
          new Date(a.latestActivityAt ?? a.updatedAt).getTime() ||
        a.name.localeCompare(b.name)
      );
    }
    return (
      b.activityScore - a.activityScore ||
      numberValue(b.costUsd) - numberValue(a.costUsd) ||
      a.name.localeCompare(b.name)
    );
  });
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
              : key.toLowerCase().includes("score") || key.toLowerCase().includes("rate")
                ? formatPercent(value)
                : formatCount(value);
          return (
            <div className="flex items-center gap-2" key={`${key}-${item.name}`}>
              <span
                className="size-2 rounded-full"
                style={{ backgroundColor: item.color ?? chartColors.requests }}
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
    <div className="flex h-72 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
      {label}
    </div>
  );
}

function WorkspaceActivityChart({ rows }: { rows: WorkspaceOverviewRow[] }) {
  const data = rows
    .filter((row) => row.hasActivity)
    .slice(0, 10)
    .map((row) => ({
      costUsd: numberValue(row.costUsd),
      name: shortLabel(row.name, 18),
      requests: row.requests,
      toolCalls: row.toolCalls,
    }));

  return (
    <DashboardPanel
      className="xl:col-span-2"
      description="Ranked by model requests and MCP tool calls in the current usage window."
      title="Workspace activity"
    >
      {data.length === 0 ? (
        <EmptyChart label="No workspace activity recorded in this window." />
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
              <Bar
                dataKey="requests"
                fill={chartColors.requests}
                name="Requests"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="toolCalls"
                fill={chartColors.toolCalls}
                name="Tool calls"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </DashboardPanel>
  );
}

function WorkspaceHealthChart({ rows }: { rows: WorkspaceOverviewRow[] }) {
  const data = rows
    .slice()
    .sort((a, b) => a.healthScore - b.healthScore || b.attentionCount - a.attentionCount)
    .slice(0, 8)
    .map((row) => ({
      attentionCount: row.attentionCount,
      fill:
        row.healthScore >= 85
          ? chartColors.active
          : row.healthScore >= 65
            ? chartColors.toolCalls
            : chartColors.attention,
      name: shortLabel(row.name, 22),
      score: row.healthScore,
    }));

  return (
    <DashboardPanel
      description="Lowest readiness scores across workspace control signals."
      title="Readiness score"
    >
      {data.length === 0 ? (
        <EmptyChart label="No workspaces to score." />
      ) : (
        <div className="h-72">
          <ResponsiveContainer height="100%" width="100%">
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 18 }}>
              <CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis
                domain={[0, 100]}
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickFormatter={(value) => `${value}%`}
                tickLine={false}
                type="number"
              />
              <YAxis
                dataKey="name"
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                tickLine={false}
                type="category"
                width={116}
              />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="score" name="Score" radius={[0, 4, 4, 0]}>
                {data.map((entry) => (
                  <Cell fill={entry.fill} key={entry.name} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </DashboardPanel>
  );
}

function WorkspaceReadinessPanel({
  activeCount,
  attentionCount,
  connectedCount,
  guardrailDefaultDenyCount,
  rows,
  totalCount,
}: {
  activeCount: number;
  attentionCount: number;
  connectedCount: number;
  guardrailDefaultDenyCount: number;
  rows: WorkspaceOverviewRow[];
  totalCount: number;
}) {
  const updates = rows.reduce((sum, row) => sum + row.serverUpdates, 0);
  const runtimeAttention = rows.reduce(
    (sum, row) => sum + row.runtimeSessionsNeedingAttention,
    0
  );
  const connectedPercent = percent(connectedCount, totalCount);
  const guardedPercent = percent(guardrailDefaultDenyCount, totalCount);

  return (
    <DashboardPanel
      description="Current control plane coverage across every workspace."
      title="Workspace posture"
    >
      <div className="space-y-4">
        <div className="space-y-3">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">Active coverage</span>
              <span className="font-mono text-muted-foreground">
                {formatCount(activeCount)} / {formatCount(totalCount)}
              </span>
            </div>
            <SignalBar
              segments={[
                { label: "Active", tone: "success", value: activeCount },
                {
                  label: "Inactive",
                  tone: "neutral",
                  value: Math.max(totalCount - activeCount, 0),
                },
              ]}
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">MCP connected</span>
              <span className="font-mono text-muted-foreground">
                {formatPercent(connectedPercent)}
              </span>
            </div>
            <SignalBar
              segments={[
                { label: "Connected", tone: "info", value: connectedCount },
                {
                  label: "No MCP servers",
                  tone: "neutral",
                  value: Math.max(totalCount - connectedCount, 0),
                },
              ]}
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">Default-deny guardrails</span>
              <span className="font-mono text-muted-foreground">
                {formatPercent(guardedPercent)}
              </span>
            </div>
            <SignalBar
              segments={[
                { label: "Default deny", tone: "success", value: guardrailDefaultDenyCount },
                {
                  label: "Default allow",
                  tone: "warning",
                  value: Math.max(totalCount - guardrailDefaultDenyCount, 0),
                },
              ]}
            />
          </div>
        </div>

        <div className="-mx-4 border-t border-border">
          <HealthRow
            badge={formatCount(attentionCount)}
            detail="Workspaces with failures, updates, disabled servers, or runtime issues"
            icon={AlertTriangle}
            label="Need attention"
            tone={attentionCount > 0 ? "warning" : "success"}
          />
          <HealthRow
            badge={formatCount(updates)}
            detail="Installed MCP server updates available"
            icon={Wrench}
            label="Server updates"
            tone={updates > 0 ? "warning" : "success"}
          />
          <HealthRow
            badge={formatCount(runtimeAttention)}
            detail="Runtime sessions that are not ready or need operator review"
            icon={ServerCog}
            label="Runtime issues"
            tone={runtimeAttention > 0 ? "danger" : "success"}
          />
        </div>
      </div>
    </DashboardPanel>
  );
}

function WorkspaceFeatureCards({
  organization,
  rows,
  openWorkspace,
}: {
  organization: OrganizationRead;
  rows: WorkspaceOverviewRow[];
  openWorkspace: (workspace: WorkspaceOverviewRow) => void;
}) {
  const featuredRows = rows.slice(0, 3);

  if (featuredRows.length === 0) {
    return null;
  }

  return (
    <section className="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-3">
      {featuredRows.map((workspace) => {
        const tone = workspaceStatusTone(workspace);
        return (
          <div
            className="min-w-0 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]"
            key={workspace.id}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <StatusDot tone={tone} />
                  <h3 className="truncate text-base font-semibold leading-6">
                    {workspace.name}
                  </h3>
                </div>
                <p className="mt-1 truncate text-sm leading-5 text-muted-foreground">
                  {workspace.description || workspace.slug}
                </p>
              </div>
              <Badge variant={badgeVariant(tone)}>{workspace.healthScore}%</Badge>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-3 border-y border-border py-3">
              <div>
                <div className="text-xs leading-4 text-muted-foreground">Requests</div>
                <div className="mt-1 truncate text-sm font-semibold">
                  {formatCompact(workspace.requests)}
                </div>
              </div>
              <div>
                <div className="text-xs leading-4 text-muted-foreground">Tools</div>
                <div className="mt-1 truncate text-sm font-semibold">
                  {formatCompact(workspace.toolCalls)}
                </div>
              </div>
              <div>
                <div className="text-xs leading-4 text-muted-foreground">Spend</div>
                <div className="mt-1 truncate text-sm font-semibold">
                  {formatCurrency(workspace.costUsd)}
                </div>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button onClick={() => openWorkspace(workspace)} size="sm" type="button">
                <MessageSquare className="size-4" />
                Chat
              </Button>
              <Button asChild size="sm" variant="outline">
                <Link href={workspacePath(organization.id, workspace.id, "/install")}>
                  <PlugZap className="size-4" />
                  Connections
                </Link>
              </Button>
              <Button asChild size="sm" variant="ghost">
                <Link href={workspacePath(organization.id, workspace.id, "/observability")}>
                  <Activity className="size-4" />
                  Observe
                </Link>
              </Button>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function WorkspaceTableView({
  filteredRows,
  filter,
  organization,
  search,
  setFilter,
  setSearch,
  setSort,
  sort,
  totalRows,
  openWorkspace,
}: {
  filteredRows: WorkspaceOverviewRow[];
  filter: WorkspaceFilter;
  organization: OrganizationRead;
  search: string;
  setFilter: (filter: WorkspaceFilter) => void;
  setSearch: (search: string) => void;
  setSort: (sort: WorkspaceSort) => void;
  sort: WorkspaceSort;
  totalRows: number;
  openWorkspace: (workspace: WorkspaceOverviewRow) => void;
}) {
  return (
    <DashboardPanel
      description={`${formatCount(filteredRows.length)} of ${formatCount(
        totalRows
      )} workspaces in view.`}
      title="Workspace operations"
    >
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="relative min-w-0 xl:w-[360px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search workspaces"
            value={search}
          />
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex rounded-md border border-border bg-card p-1">
            {[
              ["active", "Active"],
              ["attention", "Needs attention"],
              ["connected", "Connected"],
              ["all", "All"],
            ].map(([value, label]) => (
              <Button
                className="h-7 px-2 text-xs"
                key={value}
                onClick={() => setFilter(value as WorkspaceFilter)}
                size="sm"
                type="button"
                variant={filter === value ? "secondary" : "ghost"}
              >
                {label}
              </Button>
            ))}
          </div>
          <Select onValueChange={(value) => setSort(value as WorkspaceSort)} value={sort}>
            <SelectTrigger className="w-full sm:w-[190px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="activity">Highest activity</SelectItem>
              <SelectItem value="attention">Most attention</SelectItem>
              <SelectItem value="cost">Highest spend</SelectItem>
              <SelectItem value="recent">Most recent</SelectItem>
              <SelectItem value="name">Name</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {filteredRows.length === 0 ? (
        <div className="flex min-h-40 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
          No workspaces match the current view.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[250px]">Workspace</TableHead>
              <TableHead>Health</TableHead>
              <TableHead>Activity</TableHead>
              <TableHead>MCP surface</TableHead>
              <TableHead>Agents</TableHead>
              <TableHead>Last activity</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredRows.map((workspace) => {
              const tone = workspaceStatusTone(workspace);
              return (
                <TableRow key={workspace.id}>
                  <TableCell>
                    <div className="flex min-w-0 items-start gap-3">
                      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                        <Boxes className="size-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-medium">{workspace.name}</span>
                          <StatusDot tone={tone} />
                        </div>
                        <div className="mt-0.5 truncate text-xs leading-4 text-muted-foreground">
                          {workspace.description || workspace.slug}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <Badge variant="outline">{workspace.currentUserRole}</Badge>
                          <Badge variant={workspace.guardrailDefaultDeny ? "success" : "secondary"}>
                            {workspace.guardrailDefaultDeny ? "Default deny" : "Default allow"}
                          </Badge>
                          {workspace.metricsMissing ? (
                            <Badge variant="secondary">Quiet</Badge>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="w-32 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <Badge variant={badgeVariant(healthTone(workspace.healthScore))}>
                          {workspace.healthScore}%
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {workspace.attentionCount} flags
                        </span>
                      </div>
                      <SignalBar
                        segments={[
                          {
                            label: "Health",
                            tone: healthTone(workspace.healthScore),
                            value: workspace.healthScore,
                          },
                          {
                            label: "Gap",
                            tone: "neutral",
                            value: Math.max(100 - workspace.healthScore, 0),
                          },
                        ]}
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="font-medium">{formatCount(workspace.requests)} req</div>
                      <div className="text-xs text-muted-foreground">
                        {formatCount(workspace.toolCalls)} tools /{" "}
                        {formatCurrency(workspace.costUsd)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatPercent(workspace.requestSuccessRate)} request success
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="font-medium">
                        {formatCount(workspace.enabledInstallations)} /{" "}
                        {formatCount(workspace.installations)} servers
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatCount(workspace.toolCount)} tools /{" "}
                        {formatCount(workspace.activeRuntimeSessions)} runtime sessions
                      </div>
                      <div
                        className={cn(
                          "text-xs",
                          workspace.serversNeedingAttention > 0 ||
                            workspace.runtimeSessionsNeedingAttention > 0
                            ? "text-red-600"
                            : "text-muted-foreground"
                        )}
                      >
                        {formatCount(
                          workspace.serversNeedingAttention +
                            workspace.runtimeSessionsNeedingAttention
                        )}{" "}
                        runtime flags
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="font-medium">
                        {formatCount(workspace.activeAgents)} / {formatCount(workspace.agents)}
                      </div>
                      <div className="text-xs text-muted-foreground">active agents</div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="whitespace-nowrap text-sm">
                      {formatDateTime(workspace.latestActivityAt)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        aria-label={`Open ${workspace.name}`}
                        onClick={() => openWorkspace(workspace)}
                        size="sm"
                        type="button"
                      >
                        Open
                        <ArrowRight className="size-4" />
                      </Button>
                      <Button asChild size="sm" variant="outline">
                        <Link href={workspaceSettingsPath(organization.id, workspace.id)}>
                          Settings
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </DashboardPanel>
  );
}

export function OrganizationWorkspaces({
  dashboard,
  organization,
  workspaces,
}: OrganizationWorkspacesProps) {
  const router = useRouter();
  const [filter, setFilter] = useState<WorkspaceFilter>("active");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<WorkspaceSort>("activity");

  const rows = useMemo(
    () => mergeWorkspaceRows(workspaces, dashboard.workspaces),
    [dashboard.workspaces, workspaces]
  );
  const sortedRows = useMemo(() => sortWorkspaceRows(rows, sort), [rows, sort]);
  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sortedRows.filter((row) => {
      const matchesQuery =
        !query ||
        row.name.toLowerCase().includes(query) ||
        row.slug.toLowerCase().includes(query) ||
        row.description.toLowerCase().includes(query);
      const matchesFilter =
        filter === "all" ||
        (filter === "active" && row.status === "active") ||
        (filter === "attention" && row.attentionCount > 0) ||
        (filter === "connected" && row.hasMcp);
      return matchesQuery && matchesFilter;
    });
  }, [filter, search, sortedRows]);

  const activeCount = rows.filter((row) => row.status === "active").length;
  const attentionWorkspaceCount = rows.filter((row) => row.attentionCount > 0).length;
  const connectedCount = rows.filter((row) => row.hasMcp).length;
  const guardrailDefaultDenyCount = rows.filter((row) => row.guardrailDefaultDeny).length;
  const activeRuntimeSessions = rows.reduce(
    (sum, row) => sum + row.activeRuntimeSessions,
    0
  );
  const totalRequests = rows.reduce((sum, row) => sum + row.requests, 0);
  const failedRequests = rows.reduce((sum, row) => sum + row.failedRequests, 0);
  const totalCost = rows.reduce((sum, row) => sum + numberValue(row.costUsd), 0);
  const totalToolCalls = rows.reduce((sum, row) => sum + row.toolCalls, 0);

  function openWorkspace(workspace: WorkspaceOverviewRow) {
    setSelectionCookie(selectedOrganizationCookie, organization.id);
    setSelectionCookie(selectedWorkspaceCookie, workspace.id);
    router.push(workspacePath(organization.id, workspace.id));
    router.refresh();
  }

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        <DashboardMetricCard
          detail={`${formatCount(attentionWorkspaceCount)} need operator attention`}
          icon={Boxes}
          label="Active workspaces"
          tone={attentionWorkspaceCount > 0 ? "warning" : "success"}
          value={`${formatCount(activeCount)} / ${formatCount(rows.length)}`}
        />
        <DashboardMetricCard
          detail={`${formatCount(connectedCount)} workspaces with MCP servers`}
          icon={PlugZap}
          label="MCP coverage"
          tone={connectedCount > 0 ? "info" : "warning"}
          value={formatPercent(percent(connectedCount, rows.length))}
        />
        <DashboardMetricCard
          detail={`${formatPercent(successRate(failedRequests, totalRequests))} request success`}
          icon={Sparkles}
          label="Model requests"
          tone={failedRequests > 0 ? "warning" : "success"}
          value={formatCompact(totalRequests)}
        />
        <DashboardMetricCard
          detail={`${formatCount(activeRuntimeSessions)} active runtime sessions`}
          icon={ServerCog}
          label="MCP tool calls"
          tone={totalToolCalls > 0 ? "info" : "neutral"}
          value={formatCompact(totalToolCalls)}
        />
        <DashboardMetricCard
          detail={`${dashboard.window.startDate} to ${dashboard.window.endDate}`}
          icon={CircleDollarSign}
          label="Workspace spend"
          tone={totalCost > 0 ? "neutral" : "success"}
          value={formatCurrency(totalCost)}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <WorkspaceActivityChart rows={sortedRows} />
        <WorkspaceHealthChart rows={sortedRows} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <WorkspaceTableView
          filter={filter}
          filteredRows={filteredRows}
          openWorkspace={openWorkspace}
          organization={organization}
          search={search}
          setFilter={setFilter}
          setSearch={setSearch}
          setSort={setSort}
          sort={sort}
          totalRows={rows.length}
        />
        <WorkspaceReadinessPanel
          activeCount={activeCount}
          attentionCount={attentionWorkspaceCount}
          connectedCount={connectedCount}
          guardrailDefaultDenyCount={guardrailDefaultDenyCount}
          rows={rows}
          totalCount={rows.length}
        />
      </section>

      <WorkspaceFeatureCards
        openWorkspace={openWorkspace}
        organization={organization}
        rows={sortWorkspaceRows(rows, "attention")}
      />
    </div>
  );
}
