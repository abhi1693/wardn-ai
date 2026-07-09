import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Gauge,
  ListTree,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

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
import {
  backendCookieHeader,
  backendPath,
  type WorkspaceContext,
  workspaceObservabilityApiPath,
} from "@/lib/workspace-context";

type MCPToolUsageSummary = {
  total: number;
  succeeded: number;
  failed: number;
  running: number;
  attributed: number;
  unattributed: number;
  averageDurationMs: number | null;
};

type MCPToolUsageRead = {
  id: string;
  organizationId: string | null;
  workspaceId: string | null;
  runtimeSessionId: string | null;
  installationId: string;
  userId: string | null;
  userEmail: string;
  userDisplayName: string;
  agentId: string | null;
  agentName: string;
  agentRunId: string | null;
  serverName: string;
  serverVersion: string;
  toolName: string;
  status: string;
  startedAt: string;
  finishedAt: string | null;
  durationMs: number | null;
  inputSizeBytes: number;
  outputSizeBytes: number;
  isError: boolean;
  error: string;
};

type MCPToolUsageListResponse = {
  summary: MCPToolUsageSummary;
  toolCalls: MCPToolUsageRead[];
};

type WorkspaceObservabilityViewProps = {
  workspaceContext: WorkspaceContext;
};

function emptyUsage(): MCPToolUsageListResponse {
  return {
    summary: {
      total: 0,
      succeeded: 0,
      failed: 0,
      running: 0,
      attributed: 0,
      unattributed: 0,
      averageDurationMs: null,
    },
    toolCalls: [],
  };
}

async function getMcpToolUsage(context: WorkspaceContext) {
  const path = workspaceObservabilityApiPath(context, "/mcp-tool-usage?limit=100");
  if (!path) {
    return emptyUsage();
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return emptyUsage();
    }
    return (await response.json()) as MCPToolUsageListResponse;
  } catch {
    return emptyUsage();
  }
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatBytes(value: number) {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value?: string | null) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDuration(value?: number | null) {
  if (value === null || value === undefined) {
    return "";
  }
  if (value < 1000) {
    return `${value} ms`;
  }
  return `${(value / 1000).toFixed(2)} s`;
}

function statusVariant(status: string, isError: boolean) {
  if (status === "succeeded" && !isError) {
    return "success" as const;
  }
  if (status === "running") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function actorLabel(call: MCPToolUsageRead) {
  if (call.userDisplayName) {
    return call.userDisplayName;
  }
  if (call.userEmail) {
    return call.userEmail;
  }
  return "Unattributed";
}

function agentLabel(call: MCPToolUsageRead) {
  return call.agentName || "Direct MCP";
}

export async function WorkspaceObservabilityView({
  workspaceContext,
}: WorkspaceObservabilityViewProps) {
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;
  if (!organization || !workspace) {
    redirect("/");
  }

  const usage = await getMcpToolUsage(workspaceContext);
  const { summary, toolCalls } = usage;
  const successRate =
    summary.total > 0 ? Math.round((summary.succeeded / summary.total) * 100) : 0;

  return (
    <AppShell
      active="workspace-observability"
      actions={
        <Badge variant={summary.failed > 0 ? "secondary" : "outline"}>
          {formatNumber(summary.total)} tool calls
        </Badge>
      }
      eyebrow="Workspace"
      title="Observability"
      workspaceContext={workspaceContext}
    >
      <section className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Tool calls</div>
                <div className="mt-2 text-2xl font-semibold">{formatNumber(summary.total)}</div>
              </div>
              <Activity className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Success rate</div>
                <div className="mt-2 text-2xl font-semibold">{successRate}%</div>
              </div>
              <CheckCircle2 className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Attributed</div>
                <div className="mt-2 text-2xl font-semibold">
                  {formatNumber(summary.attributed)}
                </div>
              </div>
              <ListTree className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm text-muted-foreground">Average duration</div>
                <div className="mt-2 text-2xl font-semibold">
                  {formatDuration(summary.averageDurationMs) || "n/a"}
                </div>
              </div>
              <Gauge className="size-5 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle>MCP Tool Usage</CardTitle>
              <Badge variant={summary.failed > 0 ? "secondary" : "outline"}>
                {formatNumber(summary.failed)} failed
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            {toolCalls.length > 0 ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>When</TableHead>
                      <TableHead>Person</TableHead>
                      <TableHead>Agent</TableHead>
                      <TableHead>Tool</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Duration</TableHead>
                      <TableHead className="text-right">I/O</TableHead>
                      <TableHead className="text-right">Run</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {toolCalls.map((call) => {
                      const runHref = call.agentRunId
                        ? `/org/${encodeURIComponent(
                            organization.id
                          )}/workspace/${encodeURIComponent(
                            workspace.id
                          )}/agent-runs/${encodeURIComponent(call.agentRunId)}`
                        : "";

                      return (
                        <TableRow key={call.id}>
                          <TableCell className="min-w-40 align-top">
                            <div className="text-sm">{formatDate(call.startedAt)}</div>
                          </TableCell>
                          <TableCell className="min-w-44 align-top">
                            <div className="font-medium">{actorLabel(call)}</div>
                            {call.userEmail && call.userEmail !== call.userDisplayName ? (
                              <div className="mt-1 text-xs text-muted-foreground">
                                {call.userEmail}
                              </div>
                            ) : null}
                          </TableCell>
                          <TableCell className="min-w-40 align-top">
                            <div>{agentLabel(call)}</div>
                          </TableCell>
                          <TableCell className="min-w-56 align-top">
                            <div className="font-medium">{call.toolName}</div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {call.serverName}
                            </div>
                          </TableCell>
                          <TableCell className="align-top">
                            <Badge variant={statusVariant(call.status, call.isError)}>
                              {call.isError ? "error" : call.status}
                            </Badge>
                            {call.error ? (
                              <div className="mt-1 max-w-56 truncate text-xs text-muted-foreground">
                                {call.error}
                              </div>
                            ) : null}
                          </TableCell>
                          <TableCell className="text-right align-top">
                            {formatDuration(call.durationMs) || "-"}
                          </TableCell>
                          <TableCell className="text-right align-top">
                            <div>{formatBytes(call.inputSizeBytes)}</div>
                            <div className="text-xs text-muted-foreground">
                              {formatBytes(call.outputSizeBytes)}
                            </div>
                          </TableCell>
                          <TableCell className="text-right align-top">
                            {runHref ? (
                              <Button asChild size="sm" variant="outline">
                                <Link href={runHref}>Trace</Link>
                              </Button>
                            ) : (
                              <span className="text-sm text-muted-foreground">-</span>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <div className="flex min-h-56 flex-col items-center justify-center rounded-md border border-dashed text-center">
                <CircleDot className="mb-3 size-6 text-muted-foreground" />
                <div className="text-sm font-medium">No tool calls recorded</div>
                <div className="mt-1 max-w-md text-sm text-muted-foreground">
                  MCP tool usage will appear here after agents or gateway clients invoke workspace
                  tools.
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>LLM Usage</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border border-dashed p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 size-4 text-muted-foreground" />
                  <div>
                    <div className="text-sm font-medium">Waiting for instrumentation</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      Token and cost rows will populate after model calls write usage records.
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Attribution</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Workspace</span>
                <span className="font-medium">{workspace.name}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Attributed calls</span>
                <span className="font-mono">{formatNumber(summary.attributed)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Unattributed calls</span>
                <span className="font-mono">{formatNumber(summary.unattributed)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Running</span>
                <span className="font-mono">{formatNumber(summary.running)}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>
    </AppShell>
  );
}
