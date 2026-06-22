import { getWorkspaceContext } from "@/lib/workspace-context";

import { WorkspaceDashboardView } from "@/app/workspace/workspace-dashboard-view";

type WorkspaceDashboardPageProps = {
  params: Promise<{
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function WorkspaceDashboardPage({ params }: WorkspaceDashboardPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return <WorkspaceDashboardView workspaceContext={workspaceContext} />;
}
