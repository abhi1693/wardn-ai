import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { ScheduledTaskFormLoader } from "@/app/org/[organizationId]/workspace/[workspaceId]/scheduled-tasks/_components/scheduled-task-form-loader";
import type {
  ChatProviderConnectionListResponse,
  WorkspaceScheduledTaskRead,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type EditScheduledTaskPageProps = {
  params: Promise<{ organizationId: string; taskId: string; workspaceId: string }>;
};

async function getProviderConnections(organizationId: string, workspaceId: string) {
  const payload = await backendJson<ChatProviderConnectionListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/chat-providers`
  );
  return payload.connections;
}

async function getScheduledTask(
  organizationId: string,
  workspaceId: string,
  taskId: string
) {
  return backendJson<WorkspaceScheduledTaskRead>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(
      workspaceId
    )}/scheduled-tasks/${encodeURIComponent(taskId)}`
  );
}

export default async function EditScheduledTaskPage({ params }: EditScheduledTaskPageProps) {
  const { organizationId, taskId, workspaceId } = await params;
  const [workspaceContext, connections, task] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getProviderConnections(organizationId, workspaceId),
    getScheduledTask(organizationId, workspaceId, taskId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace || task.workspaceId !== workspace.id) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-scheduled-tasks"
      contentClassName="mx-0 max-w-none px-6"
      contentInnerClassName="space-y-0"
      eyebrow="Workspace"
      title="Edit Scheduled Task"
      workspaceContext={workspaceContext}
    >
      <ScheduledTaskFormLoader
        connections={connections}
        organizationId={organization.id}
        task={task}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
