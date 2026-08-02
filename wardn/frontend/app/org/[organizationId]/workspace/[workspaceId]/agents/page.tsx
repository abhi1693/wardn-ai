import { redirect } from "next/navigation";

type WorkspaceAgentsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceAgentsPage({ params }: WorkspaceAgentsPageProps) {
  const { organizationId, workspaceId } = await params;
  redirect(`/org/${organizationId}/workspace/${workspaceId}/chat`);
}
