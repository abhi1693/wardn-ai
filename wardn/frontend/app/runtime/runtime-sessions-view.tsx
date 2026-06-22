import { redirect } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Badge } from "@/components/ui/badge";
import type {
  MCPRuntimeSessionListResponse,
  MCPRuntimeSummaryResponse,
} from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  type WorkspaceContext,
  workspaceMcpRuntimePath,
} from "@/lib/workspace-context";

import { RuntimeSessionsClient } from "./runtime-sessions-client";

async function getRuntimeSessions(context: WorkspaceContext) {
  const path = workspaceMcpRuntimePath(context, "/sessions");
  if (!path) {
    return [];
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as MCPRuntimeSessionListResponse;
    return data.sessions;
  } catch {
    return [];
  }
}

async function getRuntimeSummary(context: WorkspaceContext) {
  const path = workspaceMcpRuntimePath(context, "/summary");
  if (!path) {
    return null;
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as MCPRuntimeSummaryResponse;
  } catch {
    return null;
  }
}

type RuntimeSessionsViewProps = {
  workspaceContext: WorkspaceContext;
};

export async function RuntimeSessionsView({ workspaceContext }: RuntimeSessionsViewProps) {
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;
  if (!organization || !workspace) {
    redirect("/");
  }

  const [sessions, summary] = await Promise.all([
    getRuntimeSessions(workspaceContext),
    getRuntimeSummary(workspaceContext),
  ]);
  const activeCount = sessions.filter((session) =>
    ["pending", "starting", "running", "idle"].includes(session.status)
  ).length;

  return (
    <AppShell
      active="runtime"
      actions={
        <Badge variant={activeCount > 0 ? "success" : "outline"}>
          {activeCount} active
        </Badge>
      }
      eyebrow="MCP Runtime"
      title="Runtime Sessions"
      workspaceContext={workspaceContext}
    >
      <RuntimeSessionsClient
        initialSessions={sessions}
        initialSummary={summary}
        organizationId={organization.id}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
