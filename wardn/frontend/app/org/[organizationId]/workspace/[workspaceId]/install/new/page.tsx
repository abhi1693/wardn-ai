import { NewInstallView } from "@/app/install/new-install-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewInstallPageProps = {
  params: Promise<{
    organizationId: string;
    workspaceId: string;
  }>;
  searchParams: Promise<{
    serverName?: string;
    version?: string;
  }>;
};

export default async function NewInstallPage({ params, searchParams }: NewInstallPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });

  return (
    <NewInstallView
      searchParams={await searchParams}
      workspaceContext={workspaceContext}
    />
  );
}
