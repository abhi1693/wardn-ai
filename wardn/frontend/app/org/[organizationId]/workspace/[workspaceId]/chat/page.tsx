import {
  AlertTriangle,
  CheckCircle2,
  KeyRound,
  Settings,
  ShieldOff,
} from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getGuardrailPolicyRecords } from "@/app/org/[organizationId]/workspace/[workspaceId]/guardrails/data";
import { Button } from "@/components/ui/button";
import type {
  AgentConversationResponse,
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import { ApiError, readApiResponseBody } from "@/lib/api/errors";
import { backendFetch, backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";
import { getLlmCredentials } from "../../../llm-credentials/data";

type WorkspaceChatPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

type QuickStartResult =
  | { conversationId: string; error: null }
  | { conversationId: null; error: string };

type SetupCard = {
  count: number | string;
  description: string;
  href: string;
  icon: typeof CheckCircle2;
  label: string;
};

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

async function getWorkspaceInstallations(organizationId: string, workspaceId: string) {
  const payload = await backendJson<MCPServerInstallationListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/mcp/registry/installed-servers`
  );
  return payload.installations;
}

function connectionNeedsAttention(installation: MCPServerInstallationRead) {
  return installation.status !== "enabled" || Boolean(installation.installError);
}

function buildSetupCards({
  credentialsCount,
  installations,
  organizationId,
  policyBlockCount,
  workspaceId,
}: {
  credentialsCount: number;
  installations: MCPServerInstallationRead[];
  organizationId: string;
  policyBlockCount: number;
  workspaceId: string;
}): SetupCard[] {
  const workspaceBasePath = `/org/${encodeURIComponent(
    organizationId
  )}/workspace/${encodeURIComponent(workspaceId)}`;
  const connectedCount = installations.filter((installation) => !connectionNeedsAttention(installation))
    .length;
  const unhealthyCount = installations.filter(connectionNeedsAttention).length;

  return [
    {
      count: credentialsCount > 0 ? "OK" : 1,
      description:
        credentialsCount > 0
          ? "An LLM credential is available."
          : "Add one model credential before chat can start.",
      href: `/org/${encodeURIComponent(organizationId)}/llm-credentials/new`,
      icon: KeyRound,
      label: "Needs credential",
    },
    {
      count: connectedCount,
      description: "Connections ready for workspace chat.",
      href: `${workspaceBasePath}/install`,
      icon: CheckCircle2,
      label: "Connected",
    },
    {
      count: policyBlockCount,
      description: "Active deny rules that can stop tool calls.",
      href: `${workspaceBasePath}/guardrails`,
      icon: ShieldOff,
      label: "Blocked by policy",
    },
    {
      count: unhealthyCount,
      description: "Connections reporting setup or runtime issues.",
      href: `${workspaceBasePath}/install`,
      icon: AlertTriangle,
      label: "Unhealthy",
    },
  ];
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

  const [workspaceContext, credentials, installations, policies] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getLlmCredentials(organizationId),
    getWorkspaceInstallations(organizationId, workspaceId),
    getGuardrailPolicyRecords(organizationId, workspaceId),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }
  const setupCards = buildSetupCards({
    credentialsCount: credentials.length,
    installations,
    organizationId: organization.id,
    policyBlockCount: policies.filter(
      (record) => record.policy.isActive && record.policy.mode === "deny"
    ).length,
    workspaceId,
  });
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
      contentClassName="h-screen min-h-0 max-w-none px-0 pb-0 pt-16 max-lg:h-auto max-lg:pt-0 max-md:px-0 max-md:pb-0"
      contentInnerClassName="h-full space-y-0"
      eyebrow="Workspace"
      sectionClassName="max-lg:min-h-0"
      title="Chat"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto flex min-h-[calc(100vh-220px)] max-w-4xl flex-col justify-center">
        <div className="text-center">
          <div className="mb-3 text-lg font-semibold">Chat is not ready</div>
          <p className="mx-auto max-w-xl text-sm leading-6 text-[var(--on-surface-variant)]">
          {quickStart.error}
          </p>
        </div>

        <section className="mt-6 grid gap-3 md:grid-cols-4">
          {setupCards.map((card) => {
            const Icon = card.icon;
            return (
              <Link
                className="rounded-md border border-border bg-card p-4 text-left shadow-[var(--shadow-card)] transition-colors hover:border-ring/40 hover:bg-muted/30"
                href={card.href}
                key={card.label}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">{card.label}</div>
                  <Icon className="size-4 text-muted-foreground" />
                </div>
                <div className="mt-3 text-2xl font-semibold">{card.count}</div>
                <div className="mt-1 text-xs leading-4 text-muted-foreground">
                  {card.description}
                </div>
              </Link>
            );
          })}
        </section>

        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Button asChild size="sm">
            <Link href={`/org/${organization.id}/llm-credentials/new`}>Add credential</Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/workspace/${workspaceId}/install`}>
              Connections
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/workspace/${workspaceId}/guardrails`}>
              Access rules
            </Link>
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
