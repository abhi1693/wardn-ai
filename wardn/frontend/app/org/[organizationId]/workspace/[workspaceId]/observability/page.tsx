import { getWorkspaceContext } from "@/lib/workspace-context";

import { WorkspaceObservabilityView } from "@/app/observability/workspace-observability-view";

type WorkspaceObservabilityPageProps = {
  params: Promise<{
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function WorkspaceObservabilityPage({
  params,
}: WorkspaceObservabilityPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return <WorkspaceObservabilityView workspaceContext={workspaceContext} />;
}
