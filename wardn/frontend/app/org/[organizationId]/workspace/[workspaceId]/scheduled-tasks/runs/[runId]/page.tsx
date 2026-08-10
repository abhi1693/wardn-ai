import { ArrowLeft, Bot, CalendarClock, MessageSquare, Pencil } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/templates/app-shell";
import { CancelScheduledTaskRunButton } from "@/app/org/[organizationId]/workspace/[workspaceId]/scheduled-tasks/runs/[runId]/cancel-scheduled-task-run-button";
import { DateTimeText } from "@/components/atoms/date-time-text";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import type {
  WorkspaceScheduledTaskRead,
  WorkspaceScheduledTaskRunRead,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type ScheduledTaskRunPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; runId: string }>;
};

function workspaceHref(organizationId: string, workspaceId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(workspaceId)}`;
}

function scheduledTasksHref(organizationId: string, workspaceId: string) {
  return `${workspaceHref(organizationId, workspaceId)}/scheduled-tasks`;
}

function scheduledTaskEditHref(organizationId: string, workspaceId: string, taskId: string) {
  return `${scheduledTasksHref(organizationId, workspaceId)}/${encodeURIComponent(taskId)}/edit`;
}

function agentRunHref(organizationId: string, workspaceId: string, agentRunId: string) {
  return `${workspaceHref(organizationId, workspaceId)}/agent-runs/${encodeURIComponent(
    agentRunId
  )}`;
}

function chatHref(organizationId: string, workspaceId: string, conversationId: string) {
  return `${workspaceHref(organizationId, workspaceId)}/chat/${encodeURIComponent(
    conversationId
  )}`;
}

async function getScheduledTaskRun(
  organizationId: string,
  workspaceId: string,
  runId: string
): Promise<WorkspaceScheduledTaskRunRead> {
  return backendJson<WorkspaceScheduledTaskRunRead>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(
      workspaceId
    )}/scheduled-tasks/runs/${encodeURIComponent(runId)}`
  );
}

async function getScheduledTask(
  organizationId: string,
  workspaceId: string,
  taskId: string
): Promise<WorkspaceScheduledTaskRead> {
  return backendJson<WorkspaceScheduledTaskRead>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/scheduled-tasks/${encodeURIComponent(
      taskId
    )}`
  );
}

function statusVariant(status: string) {
  if (
    status === "succeeded" ||
    status === "partially_delivered" ||
    status === "sent" ||
    status === "delivered"
  ) {
    return "success" as const;
  }
  if (status === "failed" || status === "delivery_failed") {
    return "destructive" as const;
  }
  if (status === "running" || status === "queued" || status === "waiting_confirmation") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

const runDateTimeOptions: Intl.DateTimeFormatOptions = {
  dateStyle: "medium",
  timeStyle: "medium",
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function summaryCount(summary: Record<string, unknown>, key: string) {
  const value = summary[key];
  return typeof value === "number" ? value : Number(value ?? 0);
}

function outputLabel(run: WorkspaceScheduledTaskRunRead) {
  const summary = record(run.deliverySummary);
  const sent = summaryCount(summary, "sent");
  const failed = summaryCount(summary, "failed");
  return failed > 0 ? `${sent} sent, ${failed} failed` : `${sent} sent`;
}

function InfoItem({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-sm">{value}</div>
    </div>
  );
}

export default async function ScheduledTaskRunPage({ params }: ScheduledTaskRunPageProps) {
  const { organizationId, workspaceId, runId } = await params;
  const [workspaceContext, run] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getScheduledTaskRun(organizationId, workspaceId, runId),
  ]);

  if (!run) {
    notFound();
  }

  const task = await getScheduledTask(organizationId, workspaceId, run.taskId);
  const agentHref = run.agentRunId
    ? agentRunHref(organizationId, workspaceId, run.agentRunId)
    : "";
  const runChatHref = run.conversationId
    ? chatHref(organizationId, workspaceId, run.conversationId)
    : "";

  return (
    <AppShell
      active="workspace-scheduled-tasks"
      actions={
        <div className="flex flex-wrap gap-2">
          <CancelScheduledTaskRunButton
            canCancel={Boolean(run.canCancel)}
            organizationId={organizationId}
            runId={run.id}
            taskId={run.taskId}
            workspaceId={workspaceId}
          />
          <Button asChild size="sm" variant="outline">
            <Link href={scheduledTasksHref(organizationId, workspaceId)}>
              <ArrowLeft className="size-4" />
              Scheduled tasks
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={scheduledTaskEditHref(organizationId, workspaceId, task.id)}>
              <Pencil className="size-4" />
              Edit task
            </Link>
          </Button>
          {runChatHref ? (
            <Button asChild size="sm" variant="outline">
              <Link href={runChatHref}>
                <MessageSquare className="size-4" />
                Chat
              </Link>
            </Button>
          ) : null}
          {agentHref ? (
            <Button asChild size="sm" variant="outline">
              <Link href={agentHref}>
                <Bot className="size-4" />
                Agent run
              </Link>
            </Button>
          ) : null}
        </div>
      }
      eyebrow="Scheduled Task"
      title="Run Details"
      workspaceContext={workspaceContext}
    >
      <div className="space-y-4">
        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3">
            <div>
              <CardTitle>{task.name}</CardTitle>
              <div className="mt-1 font-mono text-xs text-muted-foreground">{run.id}</div>
            </div>
            <Badge variant={statusVariant(run.status)}>{statusLabel(run.status)}</Badge>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-4">
            <InfoItem
              label="Scheduled"
              value={
                <DateTimeText options={runDateTimeOptions} value={run.scheduledFor} />
              }
            />
            <InfoItem
              label="Started"
              value={<DateTimeText options={runDateTimeOptions} value={run.startedAt} />}
            />
            <InfoItem
              label="Finished"
              value={<DateTimeText options={runDateTimeOptions} value={run.finishedAt} />}
            />
            <InfoItem label="Output" value={outputLabel(run)} />
            <InfoItem label="Attempt" value={`${run.attemptCount} / ${run.maxAttempts}`} />
            <InfoItem label="Trigger" value={statusLabel(run.triggerSource)} />
            <InfoItem
              label="Assistant run"
              value={run.agentRunId ? <Link href={agentHref}>{run.agentRunId}</Link> : "Pending"}
            />
            <InfoItem
              label="Conversation"
              value={
                run.conversationId ? <Link href={runChatHref}>{run.conversationId}</Link> : "None"
              }
            />
          </CardContent>
        </Card>

        {run.error ? (
          <Card className="border-red-200 bg-red-50">
            <CardContent className="py-3 text-sm text-red-700">{run.error}</CardContent>
          </Card>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Deliveries</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(run.deliveries ?? []).length > 0 ? (
                (run.deliveries ?? []).map((delivery) => (
                  <div
                    className="rounded-md border border-border p-3 text-sm"
                    key={delivery.id}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium">
                          {delivery.displayName || delivery.routeType}
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {delivery.provider || delivery.routeType}
                        </div>
                      </div>
                      <Badge variant={statusVariant(delivery.status)}>
                        {statusLabel(delivery.status)}
                      </Badge>
                    </div>
                    {delivery.error ? (
                      <div className="mt-2 text-xs text-red-700">{delivery.error}</div>
                    ) : null}
                  </div>
                ))
              ) : (
                <div className="flex min-h-24 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
                  No delivery attempts yet.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Notifications</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(run.notifications ?? []).length > 0 ? (
                (run.notifications ?? []).map((notification) => (
                  <div
                    className="rounded-md border border-border p-3 text-sm"
                    key={notification.id}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium">
                          {notification.title || notification.eventType}
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {notification.displayName || notification.routeType}
                        </div>
                      </div>
                      <Badge variant={statusVariant(notification.status)}>
                        {statusLabel(notification.status)}
                      </Badge>
                    </div>
                    {notification.message ? (
                      <div className="mt-2 text-xs text-muted-foreground">
                        {notification.message}
                      </div>
                    ) : null}
                    {notification.error ? (
                      <div className="mt-2 text-xs text-red-700">{notification.error}</div>
                    ) : null}
                  </div>
                ))
              ) : (
                <div className="flex min-h-24 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
                  No notifications routed yet.
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarClock className="size-4 text-muted-foreground" />
              Timeline
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-4">
            <InfoItem
              label="Available"
              value={<DateTimeText options={runDateTimeOptions} value={run.availableAt} />}
            />
            <InfoItem
              label="Created"
              value={<DateTimeText options={runDateTimeOptions} value={run.createdAt} />}
            />
            <InfoItem
              label="Updated"
              value={<DateTimeText options={runDateTimeOptions} value={run.updatedAt} />}
            />
            <InfoItem label="Task run ID" value={<span className="font-mono">{run.id}</span>} />
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
