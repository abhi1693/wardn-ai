import { Clock, ListTree, Wrench } from "lucide-react";
import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import type { AgentRunListResponse, AgentRunRead } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { AgentRunsTable } from "./agent-runs-table";

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

function metricValue(value?: number | null) {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
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
          <AgentRunsTable
            organizationId={organization.id}
            runs={runs}
            workspaceId={workspace.id}
          />
        </CardContent>
      </Card>
    </AppShell>
  );
}
