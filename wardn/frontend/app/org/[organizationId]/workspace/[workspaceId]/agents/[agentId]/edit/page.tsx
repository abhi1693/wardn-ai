import { redirect } from "next/navigation";

type EditWorkspaceAgentPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function EditWorkspaceAgentPage({ params }: EditWorkspaceAgentPageProps) {
  const { organizationId, workspaceId } = await params;
  redirect(`/org/${organizationId}/workspace/${workspaceId}/chat`);
}
