"use client";

import {
  AlertTriangle,
  BadgeDollarSign,
  Bot,
  CheckCircle2,
  Clock3,
  Cpu,
  Database,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "@/components/atoms/charts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import { Button } from "@/components/atoms/button";
import { DashboardSection } from "@/components/molecules/dashboard-section";
import { DataTableColumnHeader } from "@/components/molecules/data-table-column-header";
import { DataTable, type DataTableColumnDef } from "@/components/organisms/data-table";
import type {
  UsageSummaryBreakdownRow,
  UsageSummaryResponse as GeneratedUsageSummaryResponse,
  UsageTrendPoint,
} from "@/lib/api/generated/model";

export type UsageSummaryResponse = GeneratedUsageSummaryResponse;

type UsageSummaryViewProps = {
  attentionActionLabel?: string;
  attentionHref?: string;
  usage: UsageSummaryResponse;
  mode: "organization" | "me";
};

function formatInteger(value: number) {
  return new Intl.NumberFormat("en").format(value);
}

function formatCurrency(value: string | number) {
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  }).format(Number(value || 0));
}

function shortLabel(value: string, maxLength = 22) {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}...` : value;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T00:00:00`));
}

const chartColors = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"];

type ChartTooltipProps = {
  active?: boolean;
  payload?: Array<{ color?: string; dataKey?: string; name?: string; value?: number | string }>;
  label?: string;
};

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
          const formatted = key.toLowerCase().includes("cost")
            ? formatCurrency(value)
            : formatInteger(value);
          return (
            <div className="flex items-center gap-2" key={key}>
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

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="mt-2 truncate text-2xl font-semibold leading-8">{value}</div>
          <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
        </div>
        <Icon className="mt-1 size-5 shrink-0 text-muted-foreground" />
      </CardContent>
    </Card>
  );
}

function CompactChartSummary({
  detail,
  title,
}: {
  detail: string;
  title: string;
}) {
  return (
    <div className="rounded-md border border-dashed border-border bg-muted/30 px-4 py-5">
      <div className="text-sm font-medium text-foreground">{title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{detail}</div>
    </div>
  );
}

function TrendChart({ daily }: { daily: UsageTrendPoint[] }) {
  const data = daily.map((point) => ({
    ...point,
    dateLabel: formatDate(point.date),
    costUsd: Number(point.costUsd || 0),
  }));

  return (
    <Card className="xl:col-span-3">
      <CardHeader>
        <CardTitle>Daily trend</CardTitle>
        <CardDescription>Tokens, model requests, cost, and MCP activity by day.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length < 2 ? (
          <CompactChartSummary
            detail={
              data[0]
                ? `${data[0].dateLabel}: ${formatInteger(data[0].totalTokens)} tokens, ${formatInteger(data[0].requests)} requests, ${formatInteger(data[0].toolCalls)} tool calls, ${formatCurrency(data[0].costUsd)}.`
                : "No daily usage was recorded in this period."
            }
            title={data.length === 0 ? "No trend data" : "One recorded day"}
          />
        ) : (
          <div className="h-64">
            <ResponsiveContainer height="100%" width="100%">
              <AreaChart data={data} margin={{ left: 0, right: 12, top: 10 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="dateLabel"
                  tickLine={false}
                  tickMargin={10}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                />
                <YAxis
                  tickFormatter={(value) => formatInteger(Number(value))}
                  tickLine={false}
                  tickMargin={10}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                  yAxisId="tokens"
                />
                <YAxis hide orientation="right" yAxisId="cost" />
                <Tooltip content={<ChartTooltip />} />
                <Legend />
                <Area
                  dataKey="totalTokens"
                  fill="#2563eb"
                  fillOpacity={0.16}
                  isAnimationActive={false}
                  name="Tokens"
                  stroke="#2563eb"
                  strokeWidth={2}
                  type="monotone"
                  yAxisId="tokens"
                />
                <Area
                  dataKey="requests"
                  fill="#16a34a"
                  fillOpacity={0.14}
                  isAnimationActive={false}
                  name="Requests"
                  stroke="#16a34a"
                  strokeWidth={2}
                  type="monotone"
                  yAxisId="tokens"
                />
                <Area
                  dataKey="toolCalls"
                  fill="#f59e0b"
                  fillOpacity={0.14}
                  isAnimationActive={false}
                  name="Tool calls"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  type="monotone"
                  yAxisId="tokens"
                />
                <Area
                  dataKey="costUsd"
                  fill="#dc2626"
                  fillOpacity={0.12}
                  isAnimationActive={false}
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
      </CardContent>
    </Card>
  );
}

function BreakdownBarChart({
  title,
  description,
  rows,
  metric,
}: {
  title: string;
  description: string;
  rows: UsageSummaryBreakdownRow[];
  metric: "costUsd" | "totalTokens";
}) {
  const data = rows.slice(0, 8).map((row) => ({
    name: shortLabel(row.label),
    costUsd: Number(row.costUsd || 0),
    totalTokens: row.totalTokens,
  }));
  const metricLabel = metric === "costUsd" ? "Cost" : "Tokens";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length < 2 ? (
          <CompactChartSummary
            detail={
              data[0]
                ? `${data[0].name}: ${
                    metric === "costUsd"
                      ? formatCurrency(data[0].costUsd)
                      : `${formatInteger(data[0].totalTokens)} tokens`
                  }.`
                : "No usage was recorded for this breakdown."
            }
            title={data.length === 0 ? "No breakdown data" : "One contributor"}
          />
        ) : (
          <div className="h-64">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={data} layout="vertical" margin={{ left: 10, right: 20 }}>
                <CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis
                  tickFormatter={(value) =>
                    metric === "costUsd"
                      ? formatCurrency(Number(value))
                      : formatInteger(Number(value))
                  }
                  tickLine={false}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                  type="number"
                />
                <YAxis
                  dataKey="name"
                  tickLine={false}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                  type="category"
                  width={116}
                />
                <Tooltip content={<ChartTooltip />} />
                <Bar
                  dataKey={metric}
                  fill="#2563eb"
                  isAnimationActive={false}
                  name={metricLabel}
                  radius={[0, 4, 4, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ToolCallPieChart({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: UsageSummaryBreakdownRow[];
}) {
  const data = rows
    .filter((row) => row.toolCalls > 0)
    .slice(0, 6)
    .map((row, index) => ({
      fill: chartColors[index % chartColors.length],
      name: shortLabel(row.label, 18),
      value: row.toolCalls,
    }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length < 2 ? (
          <CompactChartSummary
            detail={
              data[0]
                ? `${data[0].name}: ${formatInteger(data[0].value)} tool calls.`
                : "No tool calls were recorded for this breakdown."
            }
            title={data.length === 0 ? "No tool-call data" : "One contributing agent"}
          />
        ) : (
          <div className="h-64">
            <ResponsiveContainer height="100%" width="100%">
              <PieChart>
                <Tooltip content={<ChartTooltip />} />
                <Legend />
                <Pie
                  cx="50%"
                  cy="48%"
                  data={data}
                  dataKey="value"
                  innerRadius={58}
                  isAnimationActive={false}
                  nameKey="name"
                  outerRadius={92}
                  paddingAngle={2}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BreakdownTable({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: UsageSummaryBreakdownRow[];
}) {
  const columns: DataTableColumnDef<UsageSummaryBreakdownRow>[] = [
    {
      accessorKey: "label",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
      cell: ({ row }) => (
        <div className="max-w-[320px] truncate font-medium">{row.original.label}</div>
      ),
    },
    {
      accessorKey: "requests",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Requests" />,
      cell: ({ row }) => (
        <div className="text-right tabular-nums">{formatInteger(row.original.requests)}</div>
      ),
    },
    {
      accessorKey: "totalTokens",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tokens" />,
      cell: ({ row }) => (
        <div className="text-right tabular-nums">{formatInteger(row.original.totalTokens)}</div>
      ),
    },
    {
      accessorKey: "costUsd",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Cost" />,
      cell: ({ row }) => (
        <div className="text-right tabular-nums">{formatCurrency(row.original.costUsd)}</div>
      ),
    },
    {
      accessorKey: "toolCalls",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tool calls" />,
      cell: ({ row }) => (
        <div className="text-right tabular-nums">{formatInteger(row.original.toolCalls)}</div>
      ),
    },
  ];
  const urlSyncKey = `usage-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          data={rows}
          emptyState="No usage recorded."
          getRowId={(row) => row.id}
          pageSize={10}
          search={{ columnId: "label", placeholder: `Search ${title.toLowerCase()}` }}
          urlSyncKey={urlSyncKey}
        />
      </CardContent>
    </Card>
  );
}

export function UsageSummaryView({
  attentionActionLabel,
  attentionHref,
  usage,
  mode,
}: UsageSummaryViewProps) {
  const summary = usage.summary;
  const succeededDetail = `${formatInteger(summary.succeeded)} succeeded, ${formatInteger(
    summary.failed
  )} failed`;
  const hasFailures = summary.failed > 0;
  const hasRunningActivity = summary.running > 0;
  const attentionSummary = hasFailures
    ? `${formatInteger(summary.failed)} failed`
    : hasRunningActivity
      ? `${formatInteger(summary.running)} running`
      : "All clear";
  const meaningfulChartCount = [
    usage.daily.length > 1,
    usage.byModel.length > 1,
    usage.byWorkspace.length > 1,
    usage.byAgent.filter((row) => row.toolCalls > 0).length > 1,
  ].filter(Boolean).length;
  const compactSummaryCount = 4 - meaningfulChartCount;
  const breakdowns =
    mode === "organization"
      ? [usage.byUser, usage.byWorkspace, usage.byAgent, usage.byModel]
      : [usage.byWorkspace, usage.byAgent, usage.byModel];
  const breakdownRowCount = breakdowns.reduce((total, rows) => total + rows.length, 0);
  const preferencePrefix = `wardn.usage.sections.${mode}`;

  return (
    <div className="space-y-4">
      <DashboardSection
        defaultOpen={hasFailures || hasRunningActivity}
        description="Failures and activity that may require a closer look."
        id="usage-attention"
        persistenceKey={`${preferencePrefix}.attention`}
        summary={attentionSummary}
        title="Needs attention"
      >
        <div className="grid gap-3 lg:grid-cols-2">
          {hasFailures ? (
            <div className="flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4">
              <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
              <div className="min-w-0 flex-1">
                <div className="font-medium text-foreground">
                  {formatInteger(summary.failed)} failed model requests
                </div>
                <div className="mt-1 text-sm text-muted-foreground">
                  Review workspace observability for provider errors and request diagnostics.
                </div>
                {attentionHref ? (
                  <Button asChild className="mt-3" size="sm" variant="outline">
                    <Link href={attentionHref}>
                      {attentionActionLabel ?? "Review workspace activity"}
                    </Link>
                  </Button>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-3 rounded-md border border-border bg-muted/20 p-4">
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <div>
                <div className="font-medium text-foreground">No failed model requests</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  All recorded model requests completed without a reported failure.
                </div>
              </div>
            </div>
          )}
          <div className="flex items-start gap-3 rounded-md border border-border bg-muted/20 p-4">
            <Clock3 className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
            <div>
              <div className="font-medium text-foreground">
                {formatInteger(summary.running)} tool calls currently running
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                Running activity is shown first so stalled work is easier to notice.
              </div>
            </div>
          </div>
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen
        description="High-level request, token, cost, and tool-call totals."
        id="usage-overview"
        persistenceKey={`${preferencePrefix}.overview`}
        summary={`${formatInteger(summary.requests)} requests`}
        title="Usage overview"
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            detail={succeededDetail}
            icon={Cpu}
            label="Model requests"
            value={formatInteger(summary.requests)}
          />
          <StatCard
            detail={`${formatInteger(summary.inputTokens)} in, ${formatInteger(
              summary.outputTokens
            )} out`}
            icon={Database}
            label="Tokens"
            value={formatInteger(summary.totalTokens)}
          />
          <StatCard
            detail={`${formatInteger(summary.requests)} model requests attributed`}
            icon={BadgeDollarSign}
            label="Cost"
            value={formatCurrency(summary.costUsd)}
          />
          <StatCard
            detail={`${formatInteger(summary.running)} currently running`}
            icon={Bot}
            label="Tool calls"
            value={formatInteger(summary.toolCalls)}
          />
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={meaningfulChartCount > 0}
        description="Visual trends render only when at least two data points make comparison useful."
        id="usage-trends"
        persistenceKey={`${preferencePrefix}.trends`}
        summary={`${meaningfulChartCount} charts, ${compactSummaryCount} summaries`}
        title="Usage trends"
      >
        <div className="grid gap-4 xl:grid-cols-3">
          <TrendChart daily={usage.daily} />
          {mode === "organization" ? (
            <BreakdownBarChart
              description="Highest spend by model across the organization."
              metric="costUsd"
              rows={usage.byModel}
              title="Model cost"
            />
          ) : (
            <BreakdownBarChart
              description="Your highest token usage by model."
              metric="totalTokens"
              rows={usage.byModel}
              title="My model tokens"
            />
          )}
          <BreakdownBarChart
            description={
              mode === "organization"
                ? "Token usage grouped by workspace."
                : "Your token usage grouped by workspace."
            }
            metric="totalTokens"
            rows={usage.byWorkspace}
            title={mode === "organization" ? "Workspace tokens" : "My workspace tokens"}
          />
          <ToolCallPieChart
            description={
              mode === "organization"
                ? "MCP tool-call attribution by agent."
                : "Your MCP tool-call attribution by agent."
            }
            rows={usage.byAgent}
            title={mode === "organization" ? "Tool calls by agent" : "My tool calls"}
          />
        </div>
      </DashboardSection>

      <DashboardSection
        defaultOpen={false}
        description="Full searchable attribution tables, available when deeper analysis is needed."
        id="usage-breakdowns"
        persistenceKey={`${preferencePrefix}.breakdowns`}
        summary={`${breakdownRowCount} rows`}
        title="Detailed breakdowns"
      >
        {mode === "organization" ? (
          <div className="grid gap-4 xl:grid-cols-2">
            <BreakdownTable
              description="Attributed usage across organization members."
              rows={usage.byUser}
              title="By user"
            />
            <BreakdownTable
              description="Workspace-level token, cost, and tool-call totals."
              rows={usage.byWorkspace}
              title="By workspace"
            />
            <BreakdownTable
              description="Agent-level spend and tool activity."
              rows={usage.byAgent}
              title="By agent"
            />
            <BreakdownTable
              description="Provider and model cost distribution."
              rows={usage.byModel}
              title="By model"
            />
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            <BreakdownTable
              description="Your usage grouped by workspace."
              rows={usage.byWorkspace}
              title="My workspaces"
            />
            <BreakdownTable
              description="Your usage grouped by agent."
              rows={usage.byAgent}
              title="My agents"
            />
            <BreakdownTable
              description="Your model request distribution."
              rows={usage.byModel}
              title="My models"
            />
          </div>
        )}
      </DashboardSection>
    </div>
  );
}
