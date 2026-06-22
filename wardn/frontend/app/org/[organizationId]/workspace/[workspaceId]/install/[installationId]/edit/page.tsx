import { EditInstallView } from "@/app/install/edit-install-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type EditInstallPageProps = {
  params: Promise<{
    installationId: string;
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function EditInstallPage({ params }: EditInstallPageProps) {
  const { installationId, organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return (
    <EditInstallView
      installationId={installationId}
      workspaceContext={workspaceContext}
    />
  );
}
