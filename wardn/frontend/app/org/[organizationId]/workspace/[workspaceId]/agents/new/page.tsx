import { redirect } from "next/navigation";

type NewWorkspaceAgentPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function NewWorkspaceAgentPage({ params }: NewWorkspaceAgentPageProps) {
  const { organizationId, workspaceId } = await params;
  redirect(`/org/${organizationId}/workspace/${workspaceId}/chat`);
}
