"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  ShieldCheck,
  ShieldOff,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";

import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  AgentToolApprovalDecisionResponse,
  AgentToolApprovalRead,
} from "@/lib/api/generated/model";
import { workspaceAgentsDecideToolApproval } from "@/lib/api/generated/workspace-agents/workspace-agents";
import { apiErrorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type ApprovalDecisionClientProps = {
  agentId: string;
  approvalId: string;
  initialApproval: AgentToolApprovalRead;
  organizationId: string;
  workspaceId: string;
};

type Decision = "approve" | "deny";
type FeedbackVariant = "error" | "info" | "progress" | "success";

type Feedback = {
  message: string;
  variant: FeedbackVariant;
};

type JsonRecord = Record<string, unknown>;

function jsonRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function nestedRecord(value: unknown, key: string) {
  return jsonRecord(jsonRecord(value)[key]);
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function formatDate(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatJson(value: unknown) {
  if (value === undefined || value === null || value === "") {
    return "";
  }
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function statusVariant(status: string) {
  if (status === "completed") {
    return "success" as const;
  }
  if (status === "failed") {
    return "destructive" as const;
  }
  if (status === "pending" || status === "running") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function statusLabel(status: string) {
  if (status === "pending") {
    return "Needs approval";
  }
  if (status === "completed") {
    return "Approved";
  }
  return status.replace(/_/g, " ");
}

function errorMessage(error: unknown) {
  const body =
    error && typeof error === "object" && "body" in error
      ? (error as { body?: unknown }).body
      : undefined;
  return apiErrorMessage(
    body,
    error instanceof Error ? error.message : "Approval request failed."
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  if (!value) {
    return null;
  }
  return (
    <div className="grid gap-1 border-b border-border/70 py-3 last:border-b-0 sm:grid-cols-[9rem_minmax(0,1fr)]">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words font-mono text-sm text-foreground">{value}</dd>
    </div>
  );
}

function ReviewPanel({ approval }: { approval: AgentToolApprovalRead }) {
  const review = approval.actionReview ?? {};
  const connection = nestedRecord(review, "targetConnection");
  const environment = nestedRecord(review, "targetEnvironment");
  const tool = nestedRecord(review, "tool");
  const policy = nestedRecord(review, "matchingPolicy");
  const rows = [
    {
      label: "Connection",
      value: [
        stringValue(connection.serverName),
        stringValue(connection.configurationName),
      ]
        .filter(Boolean)
        .join(" / "),
    },
    {
      label: "Environment",
      value: [
        stringValue(environment.configuredTarget),
        stringValue(environment.provider),
      ]
        .filter(Boolean)
        .join(" / "),
    },
    {
      label: "Tool",
      value: [
        stringValue(tool.name) || approval.toolName,
        stringValue(tool.title),
      ]
        .filter(Boolean)
        .join(" / "),
    },
    {
      label: "Policy",
      value: [
        stringValue(policy.mode),
        stringValue(policy.policyName),
      ]
        .filter(Boolean)
        .join(" / "),
    },
    {
      label: "Installation",
      value: approval.installationId,
    },
    {
      label: "Tool schema",
      value: approval.toolSchemaId,
    },
  ];

  return (
    <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Wrench className="size-4 text-muted-foreground" />
          Execution Target
        </div>
      </div>
      <dl className="px-4">
        {rows.map((row) => (
          <ReviewRow key={row.label} label={row.label} value={row.value} />
        ))}
      </dl>
      {stringValue(policy.message) ? (
        <div className="border-t border-border px-4 py-3 text-sm text-muted-foreground">
          {stringValue(policy.message)}
        </div>
      ) : null}
    </section>
  );
}

export function ApprovalDecisionClient({
  agentId,
  approvalId,
  initialApproval,
  organizationId,
  workspaceId,
}: ApprovalDecisionClientProps) {
  const [status, setStatus] = useState(initialApproval.status);
  const [result, setResult] = useState(initialApproval.result ?? "");
  const [error, setError] = useState(initialApproval.error ?? "");
  const [inFlightDecision, setInFlightDecision] = useState<Decision | "">("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [decisionResponse, setDecisionResponse] =
    useState<AgentToolApprovalDecisionResponse | null>(null);
  const argumentsJson = useMemo(
    () => formatJson(initialApproval.arguments),
    [initialApproval.arguments]
  );
  const isPending = status === "pending";
  const actionTitle =
    status === "pending"
      ? "Review the requested tool call"
      : status === "completed"
        ? "Approval completed"
        : "Approval closed";

  async function decide(decision: Decision) {
    setInFlightDecision(decision);
    setFeedback({
      message: decision === "approve" ? "Approving tool call..." : "Denying tool call...",
      variant: "progress",
    });
    try {
      const response = await workspaceAgentsDecideToolApproval(
        organizationId,
        workspaceId,
        agentId,
        approvalId,
        { decision }
      );
      setDecisionResponse(response);
      setStatus(response.status);
      setResult(response.result ?? "");
      setError(response.error ?? "");
      setFeedback({
        message:
          response.status === "completed"
            ? "Tool call approved and completed."
            : response.status === "denied"
              ? "Tool call denied."
              : `Approval is now ${statusLabel(response.status)}.`,
        variant: response.status === "failed" ? "error" : "success",
      });
    } catch (caught) {
      setFeedback({ message: errorMessage(caught), variant: "error" });
    } finally {
      setInFlightDecision("");
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="border-b border-border px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="flex size-9 items-center justify-center rounded-md border border-border bg-muted">
                  {status === "completed" ? (
                    <CheckCircle2 className="size-4 text-emerald-600" />
                  ) : status === "failed" ? (
                    <AlertTriangle className="size-4 text-red-600" />
                  ) : status === "denied" ? (
                    <ShieldOff className="size-4 text-amber-700" />
                  ) : (
                    <ShieldCheck className="size-4 text-muted-foreground" />
                  )}
                </span>
                <div className="min-w-0">
                  <h2 className="text-lg leading-6 font-semibold">{actionTitle}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {initialApproval.toolName} requested permission before it runs.
                  </p>
                </div>
              </div>
            </div>
            <Badge className="capitalize" variant={statusVariant(status)}>
              {statusLabel(status)}
            </Badge>
          </div>
        </div>

        <div className="grid gap-5 px-5 py-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-md border border-border bg-muted/30 px-3 py-3">
              <div className="text-xs text-muted-foreground">Tool</div>
              <div className="mt-1 truncate font-mono text-sm">{initialApproval.toolName}</div>
            </div>
            <div className="rounded-md border border-border bg-muted/30 px-3 py-3">
              <div className="text-xs text-muted-foreground">Requested</div>
              <div className="mt-1 flex items-center gap-2 text-sm">
                <Clock3 className="size-3.5 text-muted-foreground" />
                {formatDate(initialApproval.createdAt)}
              </div>
            </div>
            <div className="rounded-md border border-border bg-muted/30 px-3 py-3">
              <div className="text-xs text-muted-foreground">Last updated</div>
              <div className="mt-1 text-sm">{formatDate(initialApproval.updatedAt)}</div>
            </div>
          </div>

          {feedback ? (
            <AsyncFeedback variant={feedback.variant}>{feedback.message}</AsyncFeedback>
          ) : null}

          {isPending ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                disabled={Boolean(inFlightDecision)}
                onClick={() => decide("approve")}
                type="button"
              >
                {inFlightDecision === "approve" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="size-4" />
                )}
                Approve
              </Button>
              <Button
                disabled={Boolean(inFlightDecision)}
                onClick={() => decide("deny")}
                type="button"
                variant="outline"
              >
                {inFlightDecision === "deny" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ShieldOff className="size-4" />
                )}
                Deny
              </Button>
            </div>
          ) : (
            <div
              className={cn(
                "rounded-md border px-3 py-2 text-sm",
                status === "completed"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : status === "failed"
                    ? "border-red-200 bg-red-50 text-red-700"
                    : "border-border bg-muted/40 text-muted-foreground"
              )}
            >
              This approval can no longer be changed.
            </div>
          )}

          {argumentsJson ? (
            <section className="rounded-md border border-border">
              <div className="border-b border-border px-3 py-2 text-sm font-medium">
                Arguments
              </div>
              <pre className="max-h-[28rem] overflow-auto px-3 py-3 font-mono text-xs leading-5 whitespace-pre-wrap">
                {argumentsJson}
              </pre>
            </section>
          ) : null}

          {result ? (
            <section className="rounded-md border border-border">
              <div className="border-b border-border px-3 py-2 text-sm font-medium">
                Result
              </div>
              <pre className="max-h-80 overflow-auto px-3 py-3 font-mono text-xs leading-5 whitespace-pre-wrap">
                {result}
              </pre>
            </section>
          ) : null}

          {error ? (
            <AsyncFeedback variant="error">{error}</AsyncFeedback>
          ) : null}

          {decisionResponse?.assistantMessage?.content ? (
            <section className="rounded-md border border-border bg-muted/25">
              <div className="border-b border-border px-3 py-2 text-sm font-medium">
                Assistant Follow-Up
              </div>
              <div className="px-3 py-3 text-sm leading-6">
                {decisionResponse.assistantMessage.content}
              </div>
            </section>
          ) : null}
        </div>
      </section>

      <div className="grid content-start gap-5">
        <ReviewPanel
          approval={{
            ...initialApproval,
            error,
            result,
            status,
          }}
        />
        <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
          <div className="border-b border-border px-4 py-3 text-sm font-semibold">
            Decision Scope
          </div>
          <div className="grid gap-3 px-4 py-4 text-sm text-muted-foreground">
            <p>
              This approval is limited to the stored tool call and its exact arguments.
            </p>
            <p>
              Approval runs the tool once. Denial stops the pending agent run.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
