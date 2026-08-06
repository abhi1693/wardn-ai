import { ArrowLeft, ExternalLink, MessageSquare } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type { AgentRunDetailResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { AgentRunActions } from "../agent-run-actions";
import { AgentRunDetailClient } from "./agent-run-detail-client";

type AgentRunPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; agentRunId: string }>;
};

async function getAgentRun(
  organizationId: string,
  workspaceId: string,
  agentRunId: string
): Promise<AgentRunDetailResponse> {
  return backendJson<AgentRunDetailResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agent-runs/${encodeURIComponent(agentRunId)}`
  );
}

function grafanaTraceHref(traceId: string) {
  const template = process.env.NEXT_PUBLIC_GRAFANA_TRACE_URL_TEMPLATE ?? "";
  if (!template || !traceId) {
    return "";
  }
  return template.replace("{traceId}", encodeURIComponent(traceId));
}

export default async function AgentRunPage({ params }: AgentRunPageProps) {
  const { organizationId, workspaceId, agentRunId } = await params;
  const [workspaceContext, detail] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getAgentRun(organizationId, workspaceId, agentRunId),
  ]);

  if (!detail) {
    notFound();
  }

  const chatHref = detail.run.conversationId
    ? `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
        workspaceId
      )}/chat/${encodeURIComponent(detail.run.conversationId)}`
    : "";
  const traceHref = grafanaTraceHref(detail.run.traceId ?? "");

  return (
    <AppShell
      active="workspace-runs"
      actions={
        <div className="flex gap-2">
          <AgentRunActions
            canCancel={detail.run.canCancel}
            canRerun={detail.run.canRerun}
            organizationId={organizationId}
            runId={detail.run.id}
            workspaceId={workspaceId}
          />
          <Button asChild size="sm" variant="outline">
            <Link
              href={`/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
                workspaceId
              )}/agent-runs`}
            >
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
          {traceHref ? (
            <Button asChild size="sm" variant="outline">
              <a href={traceHref} rel="noreferrer" target="_blank">
                <ExternalLink className="size-4" />
                Trace
              </a>
            </Button>
          ) : null}
        </div>
      }
      eyebrow="Agent Run"
      title="Run Trace"
      workspaceContext={workspaceContext}
    >
      <AgentRunDetailClient
        agentRunId={agentRunId}
        initialDetail={detail}
        organizationId={organizationId}
        workspaceId={workspaceId}
      />
    </AppShell>
  );
}
