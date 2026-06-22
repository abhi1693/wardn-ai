import { InstallListView } from "@/app/install/install-list-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type InstallServersPageProps = {
  params: Promise<{
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function InstallServersPage({ params }: InstallServersPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return <InstallListView workspaceContext={workspaceContext} />;
}
