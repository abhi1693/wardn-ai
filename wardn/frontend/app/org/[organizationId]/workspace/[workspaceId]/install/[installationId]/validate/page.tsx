import { ValidateInstallView } from "@/app/install/validate-install-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type ValidateInstallPageProps = {
  params: Promise<{
    installationId: string;
    organizationId: string;
    workspaceId: string;
  }>;
};

export default async function ValidateInstallPage({ params }: ValidateInstallPageProps) {
  const { installationId, organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return (
    <ValidateInstallView
      installationId={installationId}
      workspaceContext={workspaceContext}
    />
  );
}
