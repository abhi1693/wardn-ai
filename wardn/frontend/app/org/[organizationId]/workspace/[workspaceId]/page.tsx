import { redirect } from "next/navigation";

type WorkspaceLandingPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceLandingPage({ params }: WorkspaceLandingPageProps) {
  const { organizationId, workspaceId } = await params;

  redirect(
    `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
      workspaceId
    )}/chat`
  );
}
