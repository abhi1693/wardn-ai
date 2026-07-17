import { Settings } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type { AgentConversationResponse } from "@/lib/api/generated/model";
import { ApiError, readApiResponseBody } from "@/lib/api/errors";
import { backendFetch } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

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
  const response = await backendFetch(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/quick-start`,
    { method: "POST" }
  );
  const body = await readApiResponseBody(response);
  if (!response.ok) {
    if (response.status === 408 || response.status === 429 || response.status >= 500) {
      throw new ApiError(
        response.status,
        body,
        `Wardn API request failed (${response.status}).`
      );
    }
    const payload = body as { detail?: unknown } | undefined;
    return {
      conversationId: null,
      error:
        typeof payload?.detail === "string"
          ? payload.detail
          : "Workspace chat could not be started.",
    };
  }
  const payload = body as AgentConversationResponse;
  return { conversationId: payload.conversation.id, error: null };
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

  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
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
      contentClassName="h-screen min-h-0 max-w-none px-0 pb-0 pt-16 max-lg:h-auto max-lg:pt-0 max-md:px-0 max-md:pb-0"
      contentInnerClassName="h-full space-y-0"
      eyebrow="Workspace"
      sectionClassName="max-lg:min-h-0"
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
