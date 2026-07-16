"use client";

import { BadgeDollarSign, Bot, Cpu, Database, type LucideIcon } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  UsageSummaryBreakdownRow,
  UsageSummaryResponse as GeneratedUsageSummaryResponse,
  UsageTrendPoint,
} from "@/lib/api/generated/model";

export type UsageSummaryResponse = GeneratedUsageSummaryResponse;

type UsageSummaryViewProps = {
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

function TrendChart({ daily }: { daily: UsageTrendPoint[] }) {
  const data = daily.map((point) => ({
    ...point,
    dateLabel: formatDate(point.date),
    costUsd: Number(point.costUsd || 0),
  }));

  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <CardTitle>Daily trend</CardTitle>
        <CardDescription>Tokens, model requests, cost, and MCP activity by day.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
            No daily usage recorded.
          </div>
        ) : (
          <div className="h-72">
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
        {data.length === 0 ? (
          <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
            No usage recorded.
          </div>
        ) : (
          <div className="h-72">
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
                <Bar dataKey={metric} fill="#2563eb" name={metricLabel} radius={[0, 4, 4, 0]} />
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
    .map((row) => ({
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
        {data.length === 0 ? (
          <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
            No tool calls recorded.
          </div>
        ) : (
          <div className="h-72">
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
                  nameKey="name"
                  outerRadius={92}
                  paddingAngle={2}
                >
                  {data.map((entry, index) => (
                    <Cell
                      fill={chartColors[index % chartColors.length]}
                      key={entry.name}
                    />
                  ))}
                </Pie>
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <div className="px-4 py-8 text-sm text-muted-foreground">No usage recorded.</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead className="text-right">Tool calls</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="max-w-[320px] truncate font-medium">
                    {row.label}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInteger(row.requests)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInteger(row.totalTokens)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCurrency(row.costUsd)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInteger(row.toolCalls)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function UsageSummaryView({ usage, mode }: UsageSummaryViewProps) {
  const summary = usage.summary;
  const succeededDetail = `${formatInteger(summary.succeeded)} succeeded, ${formatInteger(
    summary.failed
  )} failed`;

  return (
    <div className="space-y-6">
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
          detail={`${formatInteger(summary.toolCalls)} MCP calls attributed`}
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

      <div className="grid gap-4 xl:grid-cols-2">
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
    </div>
  );
}
