import { Settings } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Button } from "@/components/atoms/button";
import { AppShell } from "@/components/templates/app-shell";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { WorkspaceChatLauncher } from "./workspace-chat-launcher";

type WorkspaceChatPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceChatPage({ params }: WorkspaceChatPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;

  if (!organization || !workspaceContext.selectedWorkspace) {
    notFound();
  }

  const workspaceSettingsPath = `/organizations/${encodeURIComponent(
    organization.id
  )}/workspaces/${encodeURIComponent(workspaceId)}/settings`;

  return (
    <AppShell
      active="workspace-chat"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={workspaceSettingsPath}>
            <Settings className="size-4" />
            Settings
          </Link>
        </Button>
      }
      contentClassName="h-screen min-h-0 max-w-none px-0 pb-0 pt-14"
      contentInnerClassName="h-full space-y-0"
      eyebrow="Workspace"
      title="Chat"
      workspaceContext={workspaceContext}
    >
      <WorkspaceChatLauncher organizationId={organizationId} workspaceId={workspaceId} />
    </AppShell>
  );
}
