import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { WorkspaceDashboardClient } from "@/app/workspace/workspace-dashboard-client";
import type {
  AgentListResponse,
  MCPGatewayToolApprovalListResponse,
  MCPRuntimeSummaryResponse,
  MCPServerInstallationListResponse,
  MCPToolUsageListResponse,
  UsageSummaryResponse,
  WorkspaceObservabilityDashboardResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
  type WorkspaceContext,
  workspaceBasePath,
  workspaceInstallPath,
  workspaceMcpRegistryPath,
  workspaceMcpRuntimePath,
  workspaceObservabilityApiPath,
  workspaceObservabilityPath,
  workspaceRuntimePath,
} from "@/lib/workspace-context";

type WorkspaceDashboardViewProps = {
  workspaceContext: WorkspaceContext;
};

function workspaceAgentsPath(context: WorkspaceContext) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return "";
  }
  return `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/workspaces/${encodeURIComponent(context.selectedWorkspace.id)}/agents?limit=100`;
}

function workspaceUsagePath(context: WorkspaceContext) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return "";
  }
  return `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/workspaces/${encodeURIComponent(
    context.selectedWorkspace.id
  )}/usage/summary?breakdownLimit=8`;
}

async function getInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers?limit=100");
  if (!path) {
    return [];
  }
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

async function getUsageSummary(context: WorkspaceContext) {
  const path = workspaceUsagePath(context);
  if (!path) {
    return null;
  }
  return backendJson<UsageSummaryResponse>(path);
}

async function getRuntimeSummary(context: WorkspaceContext) {
  const path = workspaceMcpRuntimePath(context, "/summary");
  if (!path) {
    return null;
  }
  return backendJson<MCPRuntimeSummaryResponse>(path);
}

async function getAgents(context: WorkspaceContext) {
  const path = workspaceAgentsPath(context);
  if (!path) {
    return [];
  }
  const data = await backendJson<AgentListResponse>(path);
  return data.agents;
}

async function getToolUsage(context: WorkspaceContext) {
  const path = workspaceObservabilityApiPath(context, "/mcp-tool-usage?limit=100");
  if (!path) {
    return null;
  }
  return backendJson<MCPToolUsageListResponse>(path);
}

async function getObservabilityDashboard(context: WorkspaceContext) {
  const path = workspaceObservabilityApiPath(context, "/dashboard?breakdownLimit=8");
  if (!path) {
    return null;
  }
  return backendJson<WorkspaceObservabilityDashboardResponse>(path);
}

async function getGatewayApprovals(context: WorkspaceContext) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return [];
  }
  const path = `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/workspaces/${encodeURIComponent(
    context.selectedWorkspace.id
  )}/mcp/gateway/tool-approvals?status=pending&limit=25`;
  const data = await backendJson<MCPGatewayToolApprovalListResponse>(path);
  return data.approvals;
}

export async function WorkspaceDashboardView({ workspaceContext }: WorkspaceDashboardViewProps) {
  const workspace = workspaceContext.selectedWorkspace;
  if (!workspace) {
    notFound();
  }

  const [installations, usage, runtime, agents, toolUsage, observability, gatewayApprovals] =
    await Promise.all([
    getInstallations(workspaceContext),
    getUsageSummary(workspaceContext),
    getRuntimeSummary(workspaceContext),
    getAgents(workspaceContext),
    getToolUsage(workspaceContext),
    getObservabilityDashboard(workspaceContext),
    getGatewayApprovals(workspaceContext),
  ]);

  if (!usage || !runtime || !toolUsage || !observability) {
    notFound();
  }

  const basePath = workspaceBasePath(workspaceContext);
  const paths = {
    agentRuns: basePath ? `${basePath}/agent-runs` : "/",
    agents: basePath ? `${basePath}/agents` : "/",
    chat: basePath ? `${basePath}/chat` : "/",
    install: workspaceInstallPath(workspaceContext) || "/",
    observability: workspaceObservabilityPath(workspaceContext) || "/",
    runtime: workspaceRuntimePath(workspaceContext) || "/",
    scheduledTasks: basePath ? `${basePath}/scheduled-tasks` : "/",
    workspace: basePath || "/",
  };

  return (
    <AppShell
      active="workspace-dashboard"
      eyebrow="Workspace"
      title={workspace.name}
      workspaceContext={workspaceContext}
    >
      <WorkspaceDashboardClient
        agents={agents}
        gatewayApprovals={gatewayApprovals}
        installations={installations}
        observability={observability}
        paths={paths}
        runtime={runtime}
        toolUsage={toolUsage}
        usage={usage}
        workspace={workspace}
      />
    </AppShell>
  );
}
