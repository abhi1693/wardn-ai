import { redirect } from "next/navigation";

type WorkspaceAgentPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceAgentPage({ params }: WorkspaceAgentPageProps) {
  const { organizationId, workspaceId } = await params;
  redirect(`/org/${organizationId}/workspace/${workspaceId}/chat`);
}
