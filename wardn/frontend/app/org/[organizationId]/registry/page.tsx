import { RegistryPageView } from "@/app/registry/registry-page-view";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationRegistryPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationRegistryPage({
  params,
}: OrganizationRegistryPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });

  return <RegistryPageView workspaceContext={workspaceContext} />;
}
