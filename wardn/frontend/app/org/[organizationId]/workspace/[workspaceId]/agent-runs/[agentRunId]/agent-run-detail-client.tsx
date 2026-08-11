"use client";

import {
  Activity,
  AlertTriangle,
  BadgeDollarSign,
  CheckCircle2,
  CircleDot,
  Clock,
  Database,
  FileText,
  History,
  Link2,
  ListChecks,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Shield,
  Sparkles,
  Timer,
  Wrench,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/atoms/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import { apiErrorMessage, apiRequest } from "@/lib/api/client";
import type {
  AgentRunDeliveryRecipientRead,
  AgentRunDetailResponse,
  AgentRunStepRead,
} from "@/lib/api/generated/model";
import {
  formatUserDateTime,
  parseUserDateTime,
  userDateTimeWithSecondsOptions,
} from "@/lib/date-time";
import { cn } from "@/lib/utils";

type AgentRunDetailClientProps = {
  agentRunId: string;
  initialDetail: AgentRunDetailResponse;
  organizationId: string;
  workspaceId: string;
};

const POLL_INTERVAL_MS = 2500;
const STALE_AFTER_MS = 150_000;

function isActiveRun(status: string) {
  return status === "running" || status === "submitted";
}

function statusVariant(status: string) {
  if (status === "succeeded" || status === "completed" || status === "sent") {
    return "success" as const;
  }
  if (status === "failed" || status === "blocked" || status === "not_configured") {
    return "destructive" as const;
  }
  if (status === "running" || status === "submitted" || status === "waiting_confirmation") {
    return "secondary" as const;
  }
  if (status === "available" || status === "processed") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function parseTime(value?: string | null) {
  const date = parseUserDateTime(value);
  return date ? date.getTime() : null;
}

function formatDate(value?: string | null) {
  return formatUserDateTime(value, "Not finished", userDateTimeWithSecondsOptions, "en");
}

function formatDuration(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
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

function triggerLabel(triggerType: string) {
  const labels: Record<string, string> = {
    chat: "Chat",
    telegram: "Telegram",
    whatsapp: "WhatsApp",
    whatsapp_local: "WhatsApp",
  };
  return labels[triggerType] ?? triggerType;
}

function providerLabel(provider: string) {
  const labels: Record<string, string> = {
    chat: "Built-in chat",
    telegram: "Telegram",
    whatsapp: "WhatsApp",
    whatsapp_local: "WhatsApp",
  };
  return labels[provider] ?? provider;
}

function outputKindLabel(outputKind?: string | null) {
  if (outputKind === "approval") {
    return "Approval";
  }
  if (outputKind === "empty") {
    return "No output";
  }
  if (outputKind === "assistant") {
    return "Assistant";
  }
  return outputKind || "Output";
}

function recipientName(recipient: AgentRunDeliveryRecipientRead) {
  return (
    recipient.displayName?.trim() ||
    recipient.externalThreadId?.trim() ||
    providerLabel(recipient.provider ?? "") ||
    recipient.routeType
  );
}

function recipientMeta(recipient: AgentRunDeliveryRecipientRead) {
  const parts = [
    providerLabel(recipient.provider ?? ""),
    recipient.routeType,
    recipient.externalThreadId,
  ].filter(Boolean);
  return parts.join(" / ");
}

function latestActivityTime(detail: AgentRunDetailResponse) {
  const times = [
    parseTime(detail.run.updatedAt),
    parseTime(detail.run.startedAt),
    parseTime(detail.run.finishedAt),
    ...detail.steps.flatMap((step) => [parseTime(step.updatedAt), parseTime(step.createdAt)]),
  ].filter((value): value is number => value !== null);
  return times.length > 0 ? Math.max(...times) : Date.now();
}

function activeStep(detail: AgentRunDetailResponse) {
  return (
    [...detail.steps]
      .reverse()
      .find((step) => step.status === "running" || step.status === "submitted") ??
    detail.steps.at(-1) ??
    null
  );
}

function compactText(value: unknown, maxLength = 260) {
  if (typeof value !== "string") {
    return "";
  }
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1)}...`;
}

function stepSummary(step: AgentRunStepRead) {
  const payload = step.payload ?? {};
  return (
    compactText(payload.message) ||
    compactText(payload.error) ||
    compactText(payload.result) ||
    compactText(payload.content) ||
    ""
  );
}

function formatPayload(payload: AgentRunStepRead["payload"]) {
  if (!payload || Object.keys(payload).length === 0) {
    return "";
  }
  return JSON.stringify(payload, null, 2);
}

type RunSkillEvent = {
  id: string;
  sequence: number;
  eventType: "selected" | "search" | "fetch" | "activity";
  toolName: string;
  status: string;
  skillName: string;
  skillId: string;
  query: string;
  fetchedSkillId: string;
  resultCount: number | null;
  summary: string;
  createdAt: string;
};

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parsedJsonObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== "string" || !value.trim().startsWith("{")) {
    return {};
  }
  try {
    const parsed = JSON.parse(value);
    return objectValue(parsed);
  } catch {
    return {};
  }
}

function skillEventSummary({
  eventType,
  query,
  resultCount,
  fetchedSkillId,
  status,
  error,
}: {
  eventType: RunSkillEvent["eventType"];
  query: string;
  resultCount: number | null;
  fetchedSkillId: string;
  status: string;
  error: string;
}) {
  if (error) {
    return error;
  }
  if (eventType === "selected") {
    return "The model selected a Wardn skill capability through run_tool.";
  }
  if (eventType === "search") {
    const countText =
      resultCount === null
        ? "results pending"
        : `${resultCount} result${resultCount === 1 ? "" : "s"}`;
    return `Searched Wardn Hub for "${query}" and returned ${countText}.`;
  }
  if (eventType === "fetch") {
    return `Fetched ${fetchedSkillId || "a skill bundle"} for this run.`;
  }
  return `Recorded skill activity with status ${status || "unknown"}.`;
}

function skillEventFromStep(step: AgentRunStepRead): RunSkillEvent | null {
  const payload = objectValue(step.payload);
  const details = objectValue(payload.details);
  const selection = objectValue(details.selection);
  let skill = selection.toolType === "skill" ? objectValue(selection.skill) : {};
  let eventType: RunSkillEvent["eventType"] = skill.skillId ? "selected" : "activity";

  if (!skill.skillId) {
    skill = objectValue(details.skill);
    if (!skill.skillId) {
      return null;
    }
    const rawToolName = stringValue(skill.toolName);
    if (rawToolName === "wardn_search_skills") {
      eventType = "search";
    } else if (rawToolName === "wardn_get_skill") {
      eventType = "fetch";
    }
  }

  const argumentsPayload = objectValue(payload.arguments);
  const result = parsedJsonObject(payload.result);
  const query = stringValue(argumentsPayload.query) || stringValue(result.query);
  const fetchedSkillId =
    stringValue(argumentsPayload.skillId) || stringValue(result.id) || stringValue(result.skillId);
  const resultCount = numberValue(result.count);
  const status = stringValue(payload.status) || step.status;
  const toolName =
    stringValue(selection.displayName) || stringValue(payload.toolName) || step.title;

  return {
    id: step.id,
    sequence: step.sequence,
    eventType,
    toolName,
    status,
    skillName: stringValue(skill.skillName) || "find-skills",
    skillId: stringValue(skill.skillId) || "abhi1693/wardn-hub/find-skills",
    query,
    fetchedSkillId,
    resultCount,
    summary: skillEventSummary({
      eventType,
      query,
      resultCount,
      fetchedSkillId,
      status,
      error: stringValue(payload.error),
    }),
    createdAt: step.createdAt,
  };
}

function stepPayload(step: AgentRunStepRead) {
  return objectValue(step.payload);
}

function payloadApprovalId(step: AgentRunStepRead) {
  const payload = stepPayload(step);
  const approval = objectValue(payload.approval);
  return stringValue(payload.approvalId) || stringValue(approval.id);
}

function isToolStep(step: AgentRunStepRead) {
  return (
    step.stepType === "tool_call" ||
    step.stepType === "tool_result" ||
    step.stepType === "tool_progress" ||
    step.stepType === "tool_discovery"
  );
}

function isApprovalStep(step: AgentRunStepRead) {
  return (
    step.stepType.includes("approval") ||
    step.status === "requires_confirmation" ||
    Boolean(payloadApprovalId(step))
  );
}

function isGuardrailStep(step: AgentRunStepRead) {
  return step.stepType === "guardrail_decision";
}

function isOutputStep(step: AgentRunStepRead) {
  return step.stepType === "model_output";
}

function isErrorStep(step: AgentRunStepRead) {
  return (
    step.stepType === "error" ||
    step.status === "failed" ||
    step.status === "blocked" ||
    step.status === "expired" ||
    Boolean(stringValue(stepPayload(step).error))
  );
}

function uniqueValues(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function auditDetailList(values: string[], fallback: string, limit = 3) {
  const visible = uniqueValues(values).slice(0, limit);
  if (visible.length === 0) {
    return fallback;
  }
  const remaining = uniqueValues(values).length - visible.length;
  return remaining > 0 ? `${visible.join(", ")} +${remaining}` : visible.join(", ");
}

function auditStatusVariant(
  tone: "danger" | "info" | "neutral" | "success" | "warning"
) {
  if (tone === "danger") {
    return "destructive" as const;
  }
  if (tone === "success") {
    return "success" as const;
  }
  if (tone === "warning" || tone === "info") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function SkillEventBadge({ event }: { event: RunSkillEvent }) {
  if (event.eventType === "search") {
    return <Badge variant="secondary">Search</Badge>;
  }
  if (event.eventType === "fetch") {
    return <Badge variant="secondary">Fetch</Badge>;
  }
  if (event.eventType === "selected") {
    return <Badge variant="outline">Selected</Badge>;
  }
  return <Badge variant="outline">Activity</Badge>;
}

function currentActivityLabel(detail: AgentRunDetailResponse, step: AgentRunStepRead | null) {
  if (!isActiveRun(detail.run.status)) {
    return detail.run.status === "succeeded" ? "Run completed" : "Run stopped";
  }
  if (!step) {
    return "Preparing model request";
  }
  if (step.status === "running" || step.status === "submitted") {
    return step.title || step.stepType;
  }
  return `Waiting on model response after ${step.title || step.stepType}`;
}

function currentActivityDescription(detail: AgentRunDetailResponse, step: AgentRunStepRead | null) {
  if (detail.run.error) {
    return detail.run.error;
  }
  if (!isActiveRun(detail.run.status)) {
    return detail.run.finishedAt
      ? `Finished ${formatDate(detail.run.finishedAt)}.`
      : "No active work is currently running.";
  }
  if (!step) {
    return "The run has been created, but no model or tool step has been persisted yet.";
  }
  const summary = stepSummary(step);
  if (summary) {
    return summary;
  }
  if (step.status === "running" || step.status === "submitted") {
    return "The agent is still working on this step.";
  }
  return "The last tool step finished and the agent is waiting for the model to continue.";
}

function StepIcon({ step }: { step: AgentRunStepRead }) {
  if (step.status === "failed" || step.status === "blocked") {
    return <XCircle className="size-4 text-red-600" />;
  }
  if (step.status === "completed" || step.status === "succeeded" || step.status === "allow") {
    return <CheckCircle2 className="size-4 text-emerald-600" />;
  }
  if (step.stepType.includes("tool")) {
    return <Wrench className="size-4 text-blue-600" />;
  }
  return <CircleDot className="size-4 text-muted-foreground" />;
}

function Metric({
  description,
  icon: Icon,
  label,
  value,
}: {
  description: string;
  icon: typeof Timer;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-muted-foreground">{label}</div>
          <Icon className="size-4 text-muted-foreground" />
        </div>
        <div className="mt-2 text-2xl font-semibold tracking-normal">{value}</div>
        <div className="mt-1 text-xs leading-5 text-muted-foreground">{description}</div>
      </CardContent>
    </Card>
  );
}

function AuditRow({
  badge,
  detail,
  href,
  icon: Icon,
  label,
  tone = "neutral",
}: {
  badge: string;
  detail: string;
  href?: string;
  icon: typeof Activity;
  label: string;
  tone?: "danger" | "info" | "neutral" | "success" | "warning";
}) {
  const content = (
    <>
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-md border",
            tone === "danger"
              ? "border-red-200 bg-red-50 text-red-700"
              : tone === "warning"
                ? "border-amber-200 bg-amber-50 text-amber-700"
                : tone === "success"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-border bg-muted text-muted-foreground"
          )}
        >
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">{label}</div>
          <div className="truncate text-xs leading-5 text-muted-foreground">{detail}</div>
        </div>
      </div>
      <Badge variant={auditStatusVariant(tone)}>{badge}</Badge>
    </>
  );
  const className =
    "flex min-h-14 items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0";
  if (href) {
    return (
      <Link className={cn(className, "transition-colors hover:bg-muted/50")} href={href}>
        {content}
      </Link>
    );
  }
  return <div className={className}>{content}</div>;
}

function AuditRecordPanel({
  deliveryRecipients,
  detail,
  observabilityHref,
  previousRunHref,
  runtimeHref,
  workspaceRunsHref,
}: {
  deliveryRecipients: AgentRunDeliveryRecipientRead[];
  detail: AgentRunDetailResponse;
  observabilityHref: string;
  previousRunHref: string;
  runtimeHref: string;
  workspaceRunsHref: string;
}) {
  const inputSteps = detail.steps.filter((step) => step.stepType === "model_input");
  const toolSteps = detail.steps.filter(isToolStep);
  const approvalSteps = detail.steps.filter(isApprovalStep);
  const guardrailSteps = detail.steps.filter(isGuardrailStep);
  const outputSteps = detail.steps.filter(isOutputStep);
  const errorSteps = detail.steps.filter(isErrorStep);
  const retrySteps = detail.steps.filter((step) => step.stepType.includes("resume"));
  const failedRecipients = deliveryRecipients.filter((recipient) => recipient.status === "failed");
  const messageCount = inputSteps.reduce((sum, step) => {
    const count = numberValue(stepPayload(step).messageCount);
    return sum + (count ?? 0);
  }, 0);
  const approvalCount = uniqueValues(
    approvalSteps.map((step) => payloadApprovalId(step) || step.id)
  ).length;
  const runtimeInvocationCount = uniqueValues(
    detail.steps.map((step) => step.mcpToolInvocationId ?? "")
  ).length;
  const errorCount = errorSteps.length + failedRecipients.length + (detail.run.error ? 1 : 0);
  const retryCount = retrySteps.length + (detail.run.previousAgentRunId ? 1 : 0);

  return (
    <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <ListChecks className="size-4 text-muted-foreground" />
            <h2 className="text-base font-semibold tracking-normal">Audit Record</h2>
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            Inputs, tools, approvals, guardrails, outputs, errors, retries, and runtime links.
          </div>
        </div>
        <Badge variant={errorCount > 0 ? "destructive" : "success"}>
          {errorCount > 0 ? `${errorCount} issue${errorCount === 1 ? "" : "s"}` : "Complete"}
        </Badge>
      </div>
      <div className="grid gap-0 lg:grid-cols-2">
        <div className="border-b border-border lg:border-r">
          <AuditRow
            badge={inputSteps.length ? `${inputSteps.length}` : "None"}
            detail={
              inputSteps.length
                ? `${formatInteger(messageCount || inputSteps.length)} context message${
                    (messageCount || inputSteps.length) === 1 ? "" : "s"
                  } captured`
                : "No persisted model input step"
            }
            href="#activity-timeline"
            icon={FileText}
            label="Input and context"
            tone={inputSteps.length ? "success" : "warning"}
          />
          <AuditRow
            badge={`${toolSteps.length}`}
            detail={auditDetailList(
              toolSteps.map((step) => step.title || stringValue(stepPayload(step).toolName)),
              "No MCP tools called"
            )}
            href="#activity-timeline"
            icon={Wrench}
            label="Tools called"
            tone={toolSteps.length ? "success" : "neutral"}
          />
          <AuditRow
            badge={`${approvalCount}`}
            detail={auditDetailList(
              approvalSteps.map((step) => step.title || payloadApprovalId(step)),
              "No approval request recorded"
            )}
            href="#activity-timeline"
            icon={CheckCircle2}
            label="Approvals requested"
            tone={approvalCount > 0 ? "warning" : "success"}
          />
          <AuditRow
            badge={`${guardrailSteps.length}`}
            detail={auditDetailList(
              guardrailSteps.map((step) => {
                const payload = stepPayload(step);
                return stringValue(payload.policyName) || stringValue(payload.mode) || step.title;
              }),
              "No guardrail decision recorded"
            )}
            href="#activity-timeline"
            icon={Shield}
            label="Guardrails triggered"
            tone={guardrailSteps.some((step) => step.status === "deny") ? "danger" : "info"}
          />
        </div>
        <div>
          <AuditRow
            badge={`${outputSteps.length + deliveryRecipients.length}`}
            detail={`${formatInteger(outputSteps.length)} model output step${
              outputSteps.length === 1 ? "" : "s"
            } · ${formatInteger(deliveryRecipients.length)} recipient${
              deliveryRecipients.length === 1 ? "" : "s"
            }`}
            href={deliveryRecipients.length > 0 ? "#output-recipients" : "#activity-timeline"}
            icon={Send}
            label="Outputs produced"
            tone={outputSteps.length + deliveryRecipients.length > 0 ? "success" : "warning"}
          />
          <AuditRow
            badge={`${errorCount}`}
            detail={
              errorCount > 0
                ? auditDetailList(
                    [
                      detail.run.error,
                      ...errorSteps.map((step) => stringValue(stepPayload(step).error) || step.title),
                      ...failedRecipients.map((recipient) => recipient.error || recipientName(recipient)),
                    ],
                    "Errors recorded"
                  )
                : "No run, step, or delivery errors"
            }
            href={errorCount > 0 ? "#activity-timeline" : undefined}
            icon={errorCount > 0 ? AlertTriangle : CheckCircle2}
            label="Errors"
            tone={errorCount > 0 ? "danger" : "success"}
          />
          <AuditRow
            badge={`${retryCount}`}
            detail={
              retryCount > 0
                ? `${formatInteger(retrySteps.length)} resume event${
                    retrySteps.length === 1 ? "" : "s"
                  } · ${detail.run.previousAgentRunId ? "rerun lineage present" : "no previous run"}`
                : detail.run.canRerun
                  ? "Run can be rerun from this state"
                  : "No retry or resume state recorded"
            }
            href={previousRunHref || workspaceRunsHref}
            icon={RotateCcw}
            label="Retry state"
            tone={retryCount > 0 ? "warning" : "info"}
          />
          <AuditRow
            badge={`${runtimeInvocationCount}`}
            detail={
              runtimeInvocationCount > 0
                ? `${formatInteger(runtimeInvocationCount)} linked MCP invocation${
                    runtimeInvocationCount === 1 ? "" : "s"
                  }`
                : "Open runtime and observability logs for correlated sessions"
            }
            href={runtimeInvocationCount > 0 ? observabilityHref : runtimeHref}
            icon={Link2}
            label="Runtime and session logs"
            tone={runtimeInvocationCount > 0 ? "success" : "info"}
          />
        </div>
      </div>
    </section>
  );
}

export function AgentRunDetailClient({
  agentRunId,
  initialDetail,
  organizationId,
  workspaceId,
}: AgentRunDetailClientProps) {
  const [detail, setDetail] = useState(initialDetail);
  const [now, setNow] = useState(() => Date.now());
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");

  const detailPath = `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(workspaceId)}/agent-runs/${encodeURIComponent(agentRunId)}`;
  const workspaceBasePath = `/org/${encodeURIComponent(
    organizationId
  )}/workspace/${encodeURIComponent(workspaceId)}`;
  const workspaceRunsHref = `${workspaceBasePath}/agent-runs`;
  const observabilityHref = `${workspaceBasePath}/observability`;
  const runtimeHref = `${workspaceBasePath}/runtime`;
  const runIsActive = isActiveRun(detail.run.status);
  const lastActivity = useMemo(() => latestActivityTime(detail), [detail]);
  const lastActivityAge = now - lastActivity;
  const stale = runIsActive && lastActivityAge > STALE_AFTER_MS;
  const step = activeStep(detail);
  const started = parseTime(detail.run.startedAt) ?? now;
  const finished = parseTime(detail.run.finishedAt);
  const elapsed = (finished ?? now) - started;
  const skillEvents = useMemo(
    () =>
      detail.steps
        .map((runStep) => skillEventFromStep(runStep))
        .filter((event): event is RunSkillEvent => event !== null),
    [detail.steps]
  );
  const skillSearches = skillEvents.filter((event) => event.eventType === "search").length;
  const skillFetches = skillEvents.filter((event) => event.eventType === "fetch").length;
  const deliveryRecipients = detail.deliveryRecipients ?? [];
  const previousRunHref = detail.run.previousAgentRunId
    ? `${workspaceRunsHref}/${encodeURIComponent(detail.run.previousAgentRunId)}`
    : "";

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!runIsActive) {
      return;
    }
    let cancelled = false;

    async function refreshDetail() {
      setRefreshing(true);
      try {
        const nextDetail = await apiRequest<AgentRunDetailResponse>(detailPath, {
          timeoutMs: 15_000,
        });
        if (!cancelled) {
          setDetail(nextDetail);
          setRefreshError("");
        }
      } catch (error) {
        if (!cancelled) {
          setRefreshError(apiErrorMessage(error, "Could not refresh run details."));
        }
      } finally {
        if (!cancelled) {
          setRefreshing(false);
        }
      }
    }

    void refreshDetail();
    const timer = window.setInterval(refreshDetail, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [detailPath, runIsActive]);

  return (
    <div className="space-y-4">
      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Activity className="size-4 text-muted-foreground" />
              <h2 className="text-base font-semibold tracking-normal">Run Trace</h2>
              <Badge variant={statusVariant(detail.run.status)}>{detail.run.status}</Badge>
              {runIsActive ? (
                <Badge className="gap-1" variant="secondary">
                  <RefreshCw className={cn("size-3", refreshing ? "animate-spin" : "")} />
                  Live
                </Badge>
              ) : null}
            </div>
            <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
              {detail.run.id}
            </div>
          </div>
          <div className="text-right text-xs leading-5 text-muted-foreground">
            <div>Started {formatDate(detail.run.startedAt)}</div>
            <div>Last activity {formatDuration(lastActivityAge)} ago</div>
          </div>
        </div>
        {stale ? (
          <div className="flex gap-3 border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <div>
              <div className="font-medium">No new activity for {formatDuration(lastActivityAge)}</div>
              <div className="mt-0.5 text-amber-800">
                The run is still marked active, but the last persisted step is old. The agent is
                most likely waiting on the model provider or a stream finalizer.
              </div>
            </div>
          </div>
        ) : null}
        {refreshError ? (
          <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
            {refreshError}
          </div>
        ) : null}
        {detail.run.error ? (
          <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
            {detail.run.error}
          </div>
        ) : null}
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          description={runIsActive ? "Measured live while the stream is open." : "Total run time."}
          icon={Timer}
          label="Elapsed"
          value={formatDuration(elapsed)}
        />
        <Metric
          description={`${formatInteger(detail.run.inputTokens ?? 0)} input, ${formatInteger(
            detail.run.outputTokens ?? 0
          )} output.`}
          icon={Database}
          label="Tokens"
          value={formatInteger(detail.run.totalTokens ?? 0)}
        />
        <Metric
          description="Estimated from configured model pricing."
          icon={BadgeDollarSign}
          label="Cost"
          value={formatCurrency(detail.run.costUsd ?? 0)}
        />
        <Metric
          description="MCP invocations attributed to this run."
          icon={Wrench}
          label="Tool calls"
          value={formatInteger(detail.run.toolCalls ?? 0)}
        />
      </section>

      <AuditRecordPanel
        deliveryRecipients={deliveryRecipients}
        detail={detail}
        observabilityHref={observabilityHref}
        previousRunHref={previousRunHref}
        runtimeHref={runtimeHref}
        workspaceRunsHref={workspaceRunsHref}
      />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <CardTitle>Current Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-3">
              <div
                className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-md border",
                  stale
                    ? "border-amber-200 bg-amber-50 text-amber-700"
                    : runIsActive
                      ? "border-blue-200 bg-blue-50 text-blue-700"
                      : "border-emerald-200 bg-emerald-50 text-emerald-700"
                )}
              >
                {stale ? (
                  <AlertTriangle className="size-4" />
                ) : runIsActive ? (
                  <Activity className="size-4" />
                ) : (
                  <CheckCircle2 className="size-4" />
                )}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold">{currentActivityLabel(detail, step)}</div>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {currentActivityDescription(detail, step)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Run Metadata</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Trigger</span>
              <span className="font-medium">{triggerLabel(detail.run.triggerType)}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Finished</span>
              <span className="text-right font-medium">{formatDate(detail.run.finishedAt)}</span>
            </div>
            {previousRunHref ? (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Previous run</span>
                <Link
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs font-medium transition-colors hover:bg-muted"
                  href={previousRunHref}
                  title={detail.run.previousAgentRunId ?? ""}
                >
                  <History className="size-3.5" />
                  Open previous run
                </Link>
              </div>
            ) : null}
            {detail.run.traceId ? (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Trace</span>
                <span className="max-w-40 truncate font-mono text-xs" title={detail.run.traceId}>
                  {detail.run.traceId}
                </span>
              </div>
            ) : null}
            {detail.run.spanId ? (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Span</span>
                <span className="max-w-40 truncate font-mono text-xs" title={detail.run.spanId}>
                  {detail.run.spanId}
                </span>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </section>

      {deliveryRecipients.length > 0 ? (
        <section
          className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]"
          id="output-recipients"
        >
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 px-5 py-4">
            <div>
              <div className="flex items-center gap-2">
                <Send className="size-4 text-muted-foreground" />
                <h2 className="text-base font-semibold tracking-normal">Output Recipients</h2>
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {deliveryRecipients.length} output recipient
                {deliveryRecipients.length === 1 ? "" : "s"} recorded for this run.
              </div>
            </div>
          </div>
          <div className="divide-y divide-border/80">
            {deliveryRecipients.map((recipient, index) => (
              <div
                className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_auto]"
                key={recipient.id ?? `${recipient.source}-${index}`}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="truncate text-sm font-semibold">
                      {recipientName(recipient)}
                    </div>
                    <Badge variant="outline">{outputKindLabel(recipient.outputKind)}</Badge>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {recipientMeta(recipient)}
                  </div>
                  {recipient.error ? (
                    <div className="mt-2 text-xs leading-5 text-red-700">{recipient.error}</div>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-start justify-end gap-2">
                  <Badge variant={statusVariant(recipient.status)}>{recipient.status}</Badge>
                  {recipient.deliveredAt ? (
                    <span className="text-xs leading-6 text-muted-foreground">
                      {formatDate(recipient.deliveredAt)}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section
        className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]"
        id="activity-timeline"
      >
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-muted-foreground" />
              <h2 className="text-base font-semibold tracking-normal">Skill Usage</h2>
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              {skillEvents.length > 0
                ? `${skillEvents.length} skill event${skillEvents.length === 1 ? "" : "s"} recorded.`
                : "No skill was invoked in this run."}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant={skillEvents.length > 0 ? "success" : "secondary"}>
              {skillEvents.length > 0 ? "Used" : "Not used"}
            </Badge>
            <Badge variant="outline">{skillSearches} search</Badge>
            <Badge variant="outline">{skillFetches} fetch</Badge>
          </div>
        </div>
        {skillEvents.length === 0 ? (
          <div className="px-5 py-8 text-sm leading-6 text-muted-foreground">
            The agent had no persisted skill selection, Wardn Hub search, or skill fetch event for
            this run. Tool calls and model activity are still shown in the full timeline below.
          </div>
        ) : (
          <div className="divide-y divide-border/80">
            {skillEvents.map((event) => (
              <div
                className="grid gap-4 px-5 py-4 lg:grid-cols-[180px_minmax(0,1fr)_140px]"
                key={event.id}
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {event.eventType === "search" ? (
                      <Search className="size-4 text-blue-600" />
                    ) : (
                      <Sparkles className="size-4 text-emerald-600" />
                    )}
                    Step {event.sequence}
                  </div>
                  <SkillEventBadge event={event} />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold">{event.toolName}</h3>
                    <Badge variant="outline">{event.skillName}</Badge>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{event.summary}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    {event.query ? <span>Query: {event.query}</span> : null}
                    {event.fetchedSkillId ? <span>Skill: {event.fetchedSkillId}</span> : null}
                    {event.resultCount !== null ? <span>Results: {event.resultCount}</span> : null}
                  </div>
                </div>
                <div className="flex items-start justify-end">
                  <Badge variant={statusVariant(event.status)}>{event.status || "recorded"}</Badge>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between gap-3 border-b border-border/80 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-normal">Activity Timeline</h2>
            <div className="mt-1 text-sm text-muted-foreground">
              {detail.steps.length} persisted steps
            </div>
          </div>
          <Clock className="size-4 text-muted-foreground" />
        </div>
        <div className="divide-y divide-border/80">
          {detail.steps.length === 0 ? (
            <div className="px-5 py-8 text-sm text-muted-foreground">
              No steps have been recorded for this run yet.
            </div>
          ) : (
            detail.steps.map((runStep) => {
              const payload = formatPayload(runStep.payload);
              const summary = stepSummary(runStep);
              return (
                <div
                  className="grid gap-4 px-5 py-4 lg:grid-cols-[190px_minmax(0,1fr)]"
                  key={runStep.id}
                >
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <StepIcon step={runStep} />
                      Step {runStep.sequence}
                    </div>
                    <Badge variant={statusVariant(runStep.status || "recorded")}>
                      {runStep.status || "recorded"}
                    </Badge>
                    <div className="text-xs leading-5 text-muted-foreground">
                      {formatDate(runStep.createdAt)}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold">
                        {runStep.title || runStep.stepType}
                      </h3>
                      <Badge variant="outline">{runStep.stepType}</Badge>
                    </div>
                    {summary ? (
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">{summary}</p>
                    ) : null}
                    {payload ? (
                      <details className="mt-3">
                        <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                          Payload
                        </summary>
                        <pre
                          className={cn(
                            "mt-2 max-h-96 overflow-auto rounded-md border border-border",
                            "bg-muted/40 p-3 text-xs leading-5"
                          )}
                        >
                          {payload}
                        </pre>
                      </details>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
