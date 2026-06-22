import { RuntimeSessionsView } from "@/app/runtime/runtime-sessions-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type RuntimeSessionsPageProps = {
  params: Promise<{
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function RuntimeSessionsPage({ params }: RuntimeSessionsPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return <RuntimeSessionsView workspaceContext={workspaceContext} />;
}
