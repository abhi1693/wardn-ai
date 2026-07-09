import { BadgeDollarSign, Bot, Cpu, Database, type LucideIcon } from "lucide-react";

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

export type UsageSummaryBreakdownRow = {
  id: string;
  label: string;
  requests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  costUsd: string | number;
  toolCalls: number;
};

export type UsageSummaryResponse = {
  summary: {
    requests: number;
    succeeded: number;
    failed: number;
    running: number;
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
    costUsd: string | number;
    toolCalls: number;
  };
  byUser: UsageSummaryBreakdownRow[];
  byWorkspace: UsageSummaryBreakdownRow[];
  byAgent: UsageSummaryBreakdownRow[];
  byModel: UsageSummaryBreakdownRow[];
};

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
