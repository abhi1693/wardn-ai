import {
  ArrowRight,
  Clock,
  ListTree,
  MessageSquare,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AgentRunListResponse, AgentRunRead } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type AgentRunsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

async function getAgentRuns(
  organizationId: string,
  workspaceId: string
): Promise<AgentRunRead[]> {
  const payload = await backendJson<AgentRunListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agent-runs`
  );
  return payload.runs;
}

function formatDate(value?: string | null) {
  if (!value) {
    return "Not finished";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

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

export default async function AgentRunsPage({ params }: AgentRunsPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, runs] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getAgentRuns(organizationId, workspaceId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  const blockedRuns = runs.filter((run) => run.status === "blocked").length;
  const failedRuns = runs.filter((run) => run.status === "failed").length;
  const toolCalls = runs.reduce((total, run) => total + (run.toolCalls ?? 0), 0);

  return (
    <AppShell
      active="workspace-runs"
      eyebrow="Workspace"
      title="Runs"
      workspaceContext={workspaceContext}
    >
      <section className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Total runs</div>
                <div className="mt-1 text-xs text-muted-foreground">Agent activity recorded.</div>
              </div>
              <ListTree className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(runs.length)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Tool calls</div>
                <div className="mt-1 text-xs text-muted-foreground">Actions attempted.</div>
              </div>
              <Wrench className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(toolCalls)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Blocked</div>
                <div className="mt-1 text-xs text-muted-foreground">Stopped by access rules.</div>
              </div>
              <Clock className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(blockedRuns)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Failed</div>
                <div className="mt-1 text-xs text-muted-foreground">Runtime or provider errors.</div>
              </div>
              <Clock className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(failedRuns)}</div>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Tools</TableHead>
                <TableHead>Tokens</TableHead>
                <TableHead className="w-32 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.length > 0 ? (
                runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell>
                      <div className="space-y-1">
                        <div className="font-medium">{formatDate(run.startedAt)}</div>
                        <div className="max-w-56 truncate font-mono text-xs text-muted-foreground">
                          {run.id}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                    </TableCell>
                    <TableCell>{triggerLabel(run.triggerType)}</TableCell>
                    <TableCell>{metricValue(run.toolCalls)}</TableCell>
                    <TableCell>{metricValue(run.totalTokens)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        {run.conversationId ? (
                          <Button asChild size="icon" title="Open chat" variant="outline">
                            <Link
                              aria-label="Open chat"
                              href={chatHref(organization.id, workspace.id, run.conversationId)}
                            >
                              <MessageSquare className="size-4" />
                            </Link>
                          </Button>
                        ) : null}
                        <Button asChild size="icon" title="Open run" variant="outline">
                          <Link
                            aria-label="Open run"
                            href={runHref(organization.id, workspace.id, run.id)}
                          >
                            <ArrowRight className="size-4" />
                          </Link>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell className="h-40 text-center" colSpan={6}>
                    <div className="mx-auto max-w-md">
                      <div className="text-base font-semibold text-foreground">
                        No runs recorded
                      </div>
                      <div className="mt-1 text-sm leading-6 text-muted-foreground">
                        Start a chat to create the first trace. Runs will show model output, tool
                        calls, policy decisions, and runtime errors here.
                      </div>
                      <Button asChild className="mt-4" size="sm">
                        <Link
                          href={`/org/${encodeURIComponent(
                            organization.id
                          )}/workspace/${encodeURIComponent(workspace.id)}/chat`}
                        >
                          Open chat
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </AppShell>
  );
}
