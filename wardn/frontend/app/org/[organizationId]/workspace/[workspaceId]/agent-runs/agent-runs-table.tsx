"use client";

import { ArrowRight, Copy, MessageSquare } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { DateTimeText } from "@/components/atoms/date-time-text";
import { DataTableColumnHeader } from "@/components/molecules/data-table-column-header";
import {
  DataTable,
  type DataTableColumnDef,
} from "@/components/organisms/data-table";
import type { AgentRunRead } from "@/lib/api/generated/model";

import { AgentRunActions } from "./agent-run-actions";

type AgentRunsTableProps = {
  organizationId: string;
  runs: AgentRunRead[];
  workspaceId: string;
};

function statusVariant(status: string) {
  if (status === "succeeded" || status === "completed") {
    return "success" as const;
  }
  if (status === "failed" || status === "blocked") {
    return "destructive" as const;
  }
  if (status === "running" || status === "submitted") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function metricValue(value?: number | null) {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
}

function triggerLabel(triggerType: string) {
  const labels: Record<string, string> = {
    chat: "Chat",
    scheduled: "Scheduled",
    telegram: "Telegram",
    whatsapp: "WhatsApp",
    whatsapp_local: "WhatsApp",
  };
  return labels[triggerType] ?? triggerType;
}

function runHref(organizationId: string, workspaceId: string, runId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/agent-runs/${encodeURIComponent(runId)}`;
}

function chatHref(organizationId: string, workspaceId: string, conversationId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/chat/${encodeURIComponent(conversationId)}`;
}

export function AgentRunsTable({ organizationId, runs, workspaceId }: AgentRunsTableProps) {
  const columns: DataTableColumnDef<AgentRunRead>[] = [
    {
      accessorFn: (run) => `${run.id} ${run.triggerType}`,
      id: "run",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Started" />,
      sortFn: (left, right) =>
        Date.parse(left.original.startedAt ?? "") - Date.parse(right.original.startedAt ?? ""),
      cell: ({ row }) => (
        <div className="space-y-1">
          <DateTimeText
            className="font-medium"
            fallback="Not started"
            value={row.original.startedAt}
          />
          <div className="max-w-56 truncate font-mono text-xs text-muted-foreground">
            {row.original.id}
          </div>
        </div>
      ),
    },
    {
      accessorKey: "status",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      cell: ({ row }) => (
        <Badge variant={statusVariant(row.original.status)}>{row.original.status}</Badge>
      ),
    },
    {
      accessorKey: "triggerType",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Trigger" />,
      cell: ({ row }) => triggerLabel(row.original.triggerType),
    },
    {
      accessorKey: "toolCalls",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tools" />,
      cell: ({ row }) => metricValue(row.original.toolCalls),
    },
    {
      accessorKey: "totalTokens",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tokens" />,
      cell: ({ row }) => metricValue(row.original.totalTokens),
    },
    {
      id: "actions",
      enableHiding: false,
      enableSorting: false,
      header: () => <div className="text-right">Actions</div>,
      cell: ({ row }) => {
        const run = row.original;
        return (
          <div className="flex justify-end gap-2">
            <AgentRunActions
              canCancel={run.canCancel}
              canRerun={run.canRerun}
              organizationId={organizationId}
              runId={run.id}
              variant="icon"
              workspaceId={workspaceId}
            />
            {run.conversationId ? (
              <Button asChild size="icon" title="Open chat" variant="outline">
                <Link
                  aria-label={`Open chat for ${run.id}`}
                  href={chatHref(organizationId, workspaceId, run.conversationId)}
                >
                  <MessageSquare className="size-4" />
                </Link>
              </Button>
            ) : null}
            <Button asChild size="icon" title="Open run" variant="outline">
              <Link
                aria-label={`Open ${run.id}`}
                href={runHref(organizationId, workspaceId, run.id)}
              >
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        );
      },
    },
  ];

  async function copyRunIds(selectedRuns: AgentRunRead[]) {
    await navigator.clipboard.writeText(selectedRuns.map((run) => run.id).join("\n"));
    toast.success(`${selectedRuns.length} run ID${selectedRuns.length === 1 ? "" : "s"} copied.`);
  }

  return (
    <DataTable
      bulkActions={(selectedRuns) => (
        <Button onClick={() => void copyRunIds(selectedRuns)} size="sm" type="button" variant="outline">
          <Copy className="size-4" />
          Copy IDs
        </Button>
      )}
      columns={columns}
      data={runs}
      emptyState={
        <div className="mx-auto max-w-md">
          <div className="text-base font-semibold text-foreground">No runs recorded</div>
          <div className="mt-1 text-sm leading-6 text-muted-foreground">
            Start a chat to create the first trace. Runs will show model output, tool calls,
            policy decisions, and runtime errors here.
          </div>
          <Button asChild className="mt-4" size="sm">
            <Link
              href={`/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
                workspaceId
              )}/chat`}
            >
              Open chat
            </Link>
          </Button>
        </div>
      }
      filters={[
        {
          columnId: "status",
          label: "Status",
          options: [
            { label: "Running", value: "running" },
            { label: "Succeeded", value: "succeeded" },
            { label: "Blocked", value: "blocked" },
            { label: "Failed", value: "failed" },
          ],
        },
      ]}
      getRowId={(run) => run.id}
      pageSize={20}
      search={{ columnId: "run", placeholder: "Search run ID or trigger" }}
      selectable
      urlSyncKey="runs"
    />
  );
}
