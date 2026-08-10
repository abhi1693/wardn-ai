import { ArrowLeft, ListTree, MessageSquare } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { Button } from "@/components/atoms/button";
import type { AgentToolApprovalRead } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { ApprovalDecisionClient } from "./approval-decision-client";

type ApprovalPageProps = {
  params: Promise<{
    agentId: string;
    approvalId: string;
    organizationId: string;
    workspaceId: string;
  }>;
};

async function getApproval(
  organizationId: string,
  workspaceId: string,
  agentId: string,
  approvalId: string
): Promise<AgentToolApprovalRead> {
  return backendJson<AgentToolApprovalRead>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(
      agentId
    )}/tool-approvals/${encodeURIComponent(approvalId)}`
  );
}

export default async function ApprovalPage({ params }: ApprovalPageProps) {
  const { agentId, approvalId, organizationId, workspaceId } = await params;
  const [workspaceContext, approval] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getApproval(organizationId, workspaceId, agentId, approvalId),
  ]);

  if (!workspaceContext.selectedOrganization || !workspaceContext.selectedWorkspace) {
    notFound();
  }

  const workspaceBasePath = `/org/${encodeURIComponent(
    organizationId
  )}/workspace/${encodeURIComponent(workspaceId)}`;
  const chatHref = approval.conversationId
    ? `${workspaceBasePath}/chat/${encodeURIComponent(approval.conversationId)}`
    : "";
  const runHref = approval.agentRunId
    ? `${workspaceBasePath}/agent-runs/${encodeURIComponent(approval.agentRunId)}`
    : "";

  return (
    <AppShell
      active="workspace-runs"
      actions={
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href={`${workspaceBasePath}/agent-runs`}>
              <ArrowLeft className="size-4" />
              Runs
            </Link>
          </Button>
          {chatHref ? (
            <Button asChild size="sm" variant="outline">
              <Link href={chatHref}>
                <MessageSquare className="size-4" />
                Chat
              </Link>
            </Button>
          ) : null}
          {runHref ? (
            <Button asChild size="sm" variant="outline">
              <Link href={runHref}>
                <ListTree className="size-4" />
                Trace
              </Link>
            </Button>
          ) : null}
        </div>
      }
      eyebrow="Workspace Approval"
      title="Tool Approval"
      workspaceContext={workspaceContext}
    >
      <ApprovalDecisionClient
        agentId={agentId}
        approvalId={approvalId}
        initialApproval={approval}
        organizationId={organizationId}
        workspaceId={workspaceId}
      />
    </AppShell>
  );
}
