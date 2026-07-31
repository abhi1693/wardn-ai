import { ConnectionDetailView } from "@/app/install/connection-detail-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type ConnectionDetailPageProps = {
  params: Promise<{
    installationId: string;
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function ConnectionDetailPage({ params }: ConnectionDetailPageProps) {
  const { installationId, organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return (
    <ConnectionDetailView
      installationId={installationId}
      workspaceContext={workspaceContext}
    />
  );
}
