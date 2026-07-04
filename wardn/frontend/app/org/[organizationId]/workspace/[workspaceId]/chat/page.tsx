import { Settings } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import type { AgentConversationResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceChatPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

type QuickStartResult =
  | { conversationId: string; error: null }
  | { conversationId: null; error: string };

async function quickStartWorkspaceAgent(
  organizationId: string,
  workspaceId: string
): Promise<QuickStartResult> {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/workspaces/${encodeURIComponent(workspaceId)}/agents/quick-start`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
        method: "POST",
      }
    );
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      return {
        conversationId: null,
        error:
          typeof payload?.detail === "string"
            ? payload.detail
            : "Workspace chat could not be started.",
      };
    }
    const payload = (await response.json()) as AgentConversationResponse;
    return { conversationId: payload.conversation.id, error: null };
  } catch {
    return { conversationId: null, error: "Workspace chat could not be started." };
  }
}

export default async function WorkspaceChatPage({ params }: WorkspaceChatPageProps) {
  const { organizationId, workspaceId } = await params;
  const quickStart = await quickStartWorkspaceAgent(organizationId, workspaceId);

  if (quickStart.conversationId) {
    redirect(
      `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
        workspaceId
      )}/chat/${encodeURIComponent(quickStart.conversationId)}`
    );
  }

  const [workspaceContext, organization] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
  ]);

  if (!organization) {
    return null;
  }

  return (
    <AppShell
      active="workspace-chat"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/workspace/${workspaceId}/agents`}>
            <Settings className="size-4" />
            Manage agents
          </Link>
        </Button>
      }
      eyebrow="Workspace"
      title="Chat"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto flex min-h-[calc(100vh-220px)] max-w-xl flex-col items-center justify-center text-center">
        <div className="mb-3 text-lg font-semibold">Chat is not ready</div>
        <p className="text-sm leading-6 text-[var(--on-surface-variant)]">
          {quickStart.error}
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Button asChild size="sm">
            <Link href={`/org/${organization.id}/llm-credentials/new`}>Add credential</Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/workspace/${workspaceId}/agents`}>
              Manage agents
            </Link>
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
