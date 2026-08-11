import { AlertTriangle } from "lucide-react";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { Badge } from "@/components/atoms/badge";
import type { WorkspaceObservabilityDashboardResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
  type WorkspaceContext,
  workspaceObservabilityApiPath,
} from "@/lib/workspace-context";
import { WorkspaceObservabilityDashboardClient } from "@/app/observability/workspace-observability-dashboard-client";

type WorkspaceObservabilityViewProps = {
  workspaceContext: WorkspaceContext;
};

function emptyDashboard(): WorkspaceObservabilityDashboardResponse {
  const today = new Date().toISOString().slice(0, 10);
  return {
    activity: [],
    attention: [],
    recentRuns: [],
    summary: {
      activeRuntimeSessions: 0,
      agentRuns: 0,
      attributedLlmCalls: 0,
      attributedToolCalls: 0,
      averageToolDurationMs: null,
      costUsd: "0",
      failedAgentRuns: 0,
      failedRequests: 0,
      failedToolCalls: 0,
      healthScore: 100,
      p95ToolDurationMs: null,
      requestSuccessRate: 100,
      requests: 0,
      runningAgentRuns: 0,
      runningToolCalls: 0,
      runtimeSessionsNeedingAttention: 0,
      toolCalls: 0,
      toolSuccessRate: 100,
      totalTokens: 0,
      unattributedLlmCalls: 0,
      unattributedToolCalls: 0,
    },
    topAgents: [],
    topModels: [],
    topTools: [],
    topUsers: [],
    window: {
      breakdownLimit: 8,
      endDate: today,
      startDate: today,
      timezone: "UTC",
    },
  };
}

async function getDashboard(context: WorkspaceContext) {
  const path = workspaceObservabilityApiPath(context, "/dashboard?breakdownLimit=8");
  if (!path) {
    return emptyDashboard();
  }
  return backendJson<WorkspaceObservabilityDashboardResponse>(path);
}

export async function WorkspaceObservabilityView({
  workspaceContext,
}: WorkspaceObservabilityViewProps) {
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;
  if (!organization || !workspace) {
    redirect("/");
  }

  const dashboard = await getDashboard(workspaceContext);

  return (
    <AppShell
      active="workspace-observability"
      actions={
        <Badge variant={dashboard.summary.failedAgentRuns > 0 ? "secondary" : "outline"}>
          <AlertTriangle className="size-3" />
          {dashboard.summary.failedAgentRuns} failed runs
        </Badge>
      }
      eyebrow="Workspace"
      title="Observability"
      workspaceContext={workspaceContext}
    >
      <WorkspaceObservabilityDashboardClient
        dashboard={dashboard}
        organizationId={organization.id}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
