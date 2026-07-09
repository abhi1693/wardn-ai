import {
  ArrowLeft,
  BadgeDollarSign,
  Clock,
  Database,
  ExternalLink,
  ListTree,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AgentRunDetailResponse, AgentRunStepRead } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

type AgentRunPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; agentRunId: string }>;
};

async function getAgentRun(
  organizationId: string,
  workspaceId: string,
  agentRunId: string
): Promise<AgentRunDetailResponse | null> {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/workspaces/${encodeURIComponent(workspaceId)}/agent-runs/${encodeURIComponent(
          agentRunId
        )}`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as AgentRunDetailResponse;
  } catch {
    return null;
  }
}

function formatDate(value?: string | null) {
  if (!value) {
    return "Not finished";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatPayload(payload: AgentRunStepRead["payload"]) {
  if (!payload || Object.keys(payload).length === 0) {
    return "";
  }
  return JSON.stringify(payload, null, 2);
}

function statusVariant(status: string) {
  if (status === "succeeded" || status === "completed") {
    return "success" as const;
  }
  if (status === "running" || status === "submitted") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("en").format(value);
}

function formatCurrency(value: string | number) {
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  }).format(Number(value || 0));
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

  const chatHref = `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/chat/${encodeURIComponent(detail.run.conversationId ?? "")}`;
  const traceHref = grafanaTraceHref(detail.run.traceId ?? "");

  return (
    <AppShell
      active="workspace-chat"
      actions={
        detail.run.conversationId ? (
          <Button asChild size="sm" variant="outline">
            <Link href={chatHref}>
              <ArrowLeft className="size-4" />
              Back to chat
            </Link>
          </Button>
        ) : null
      }
      eyebrow="Agent Run"
      title="Run Trace"
      workspaceContext={workspaceContext}
    >
      <div className="space-y-4">
        <section className="rounded-lg border border-[var(--outline-variant)] bg-white shadow-[var(--shadow-card)]">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--outline-variant)] px-5 py-4">
            <div>
              <div className="flex items-center gap-2">
                <ListTree className="size-4 text-[var(--on-surface-variant)]" />
                <h2 className="text-lg font-semibold">Agent run</h2>
              </div>
              <div className="mt-1 font-mono text-xs text-[var(--on-surface-variant)]">
                {detail.run.id}
              </div>
            </div>
            <Badge variant={statusVariant(detail.run.status)}>{detail.run.status}</Badge>
          </div>
          <div className="grid gap-4 px-5 py-4 text-sm md:grid-cols-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                Trigger
              </div>
              <div className="mt-1">{detail.run.triggerType}</div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                Started
              </div>
              <div className="mt-1">{formatDate(detail.run.startedAt)}</div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                Finished
              </div>
              <div className="mt-1">{formatDate(detail.run.finishedAt)}</div>
            </div>
          </div>
          {detail.run.error ? (
            <div className="border-t border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
              {detail.run.error}
            </div>
          ) : null}
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-lg border border-[var(--outline-variant)] bg-white p-4 shadow-[var(--shadow-card)]">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-[var(--on-surface-variant)]">Tokens</div>
              <Database className="size-4 text-[var(--on-surface-variant)]" />
            </div>
            <div className="mt-2 text-2xl font-semibold">
              {formatInteger(detail.run.totalTokens ?? 0)}
            </div>
            <div className="mt-1 text-xs text-[var(--on-surface-variant)]">
              {formatInteger(detail.run.inputTokens ?? 0)} in,{" "}
              {formatInteger(detail.run.outputTokens ?? 0)} out
            </div>
          </div>
          <div className="rounded-lg border border-[var(--outline-variant)] bg-white p-4 shadow-[var(--shadow-card)]">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-[var(--on-surface-variant)]">Cost</div>
              <BadgeDollarSign className="size-4 text-[var(--on-surface-variant)]" />
            </div>
            <div className="mt-2 text-2xl font-semibold">
              {formatCurrency(detail.run.costUsd ?? 0)}
            </div>
            <div className="mt-1 text-xs text-[var(--on-surface-variant)]">
              Estimated from configured model pricing
            </div>
          </div>
          <div className="rounded-lg border border-[var(--outline-variant)] bg-white p-4 shadow-[var(--shadow-card)]">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-[var(--on-surface-variant)]">Tool calls</div>
              <Wrench className="size-4 text-[var(--on-surface-variant)]" />
            </div>
            <div className="mt-2 text-2xl font-semibold">
              {formatInteger(detail.run.toolCalls ?? 0)}
            </div>
            <div className="mt-1 text-xs text-[var(--on-surface-variant)]">
              MCP invocations attributed to this run
            </div>
          </div>
          <div className="rounded-lg border border-[var(--outline-variant)] bg-white p-4 shadow-[var(--shadow-card)]">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-[var(--on-surface-variant)]">Trace</div>
              <ListTree className="size-4 text-[var(--on-surface-variant)]" />
            </div>
            <div className="mt-2 min-w-0 font-mono text-sm">
              {detail.run.traceId ? (
                traceHref ? (
                  <a
                    className="inline-flex max-w-full items-center gap-1 truncate text-primary underline-offset-4 hover:underline"
                    href={traceHref}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <span className="truncate">{detail.run.traceId}</span>
                    <ExternalLink className="size-3 shrink-0" />
                  </a>
                ) : (
                  <span className="block truncate">{detail.run.traceId}</span>
                )
              ) : (
                <span className="text-[var(--on-surface-variant)]">Not recorded</span>
              )}
            </div>
            <div className="mt-1 truncate text-xs text-[var(--on-surface-variant)]">
              {detail.run.spanId || "No span id recorded"}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-[var(--outline-variant)] bg-white shadow-[var(--shadow-card)]">
          <div className="border-b border-[var(--outline-variant)] px-5 py-4">
            <h2 className="text-base font-semibold">Steps</h2>
          </div>
          <div className="divide-y divide-[var(--outline-variant)]">
            {detail.steps.length === 0 ? (
              <div className="px-5 py-6 text-sm text-[var(--on-surface-variant)]">
                No steps were recorded for this run.
              </div>
            ) : (
              detail.steps.map((step) => {
                const payload = formatPayload(step.payload);
                return (
                  <div className="grid gap-4 px-5 py-4 lg:grid-cols-[220px_1fr]" key={step.id}>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <Clock className="size-4 text-[var(--on-surface-variant)]" />
                        Step {step.sequence}
                      </div>
                      <Badge variant={statusVariant(step.status)}>{step.status || "recorded"}</Badge>
                      <div className="text-xs text-[var(--on-surface-variant)]">
                        {formatDate(step.createdAt)}
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold">{step.title || step.stepType}</h3>
                        <Badge variant="outline">{step.stepType}</Badge>
                      </div>
                      {payload ? (
                        <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-low)] p-3 text-xs leading-5">
                          {payload}
                        </pre>
                      ) : null}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
