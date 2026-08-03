import type { UIMessage } from "ai";
import {
  Bot,
  Brain,
  Check,
  CheckCircle2,
  CircleAlert,
  Copy,
  ListTree,
  Loader2,
  ShieldOff,
  Square,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { type ComponentPropsWithoutRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ConversationMessageRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

import type { LlmCredentialRead } from "../../llm-credentials/types";

export type MessageRole = UIMessage["role"];
export type MessagePart = UIMessage["parts"][number];
export type ToolApprovalData = {
  actionReview?: ActionReviewData;
  id?: string;
  status?: string;
};
export type ActionReviewData = {
  matchingPolicy?: {
    matchedPolicyIds?: string[];
    message?: string;
    mode?: string;
    policyId?: string | null;
    policyName?: string | null;
  };
  normalizedArguments?: unknown;
  targetConnection?: {
    configurationName?: string;
    installationId?: string;
    installType?: string;
    serverName?: string;
    serverVersion?: string;
  };
  targetEnvironment?: {
    configuredTarget?: string;
    provider?: string;
    runtimeKind?: string;
  };
  tool?: {
    name?: string;
    schemaId?: string;
    serverName?: string;
    title?: string;
  };
};
export type ToolActivityData = {
  approval?: ToolApprovalData;
  arguments?: unknown;
  details?: unknown;
  error?: string;
  failureReason?: string;
  message?: string;
  progress?: number;
  progressToken?: string | number;
  result?: unknown;
  status?: string;
  toolName?: string;
  total?: number;
};
export type ToolActivityPart = MessagePart & {
  data?: ToolActivityData;
  id?: string;
  type: "data-tool-activity";
};
export type ReasoningSummaryData = {
  summary?: string;
};
export type ReasoningSummaryPart = MessagePart & {
  data?: ReasoningSummaryData;
  id?: string;
  type: "data-reasoning-summary";
};

export function isTextPart(part: MessagePart): part is Extract<MessagePart, { type: "text" }> {
  return part.type === "text" && typeof part.text === "string";
}

export function messageText(parts: MessagePart[]) {
  return parts
    .filter(isTextPart)
    .map((part) => part.text)
    .join("");
}

export function textPart(text: string) {
  return { type: "text" as const, text };
}

export function uiMessageParts(message: ConversationMessageRead): UIMessage["parts"] {
  return message.parts?.length
    ? (message.parts as UIMessage["parts"])
    : ([textPart(message.content)] as UIMessage["parts"]);
}

function isCompactionMessage(message: ConversationMessageRead) {
  return (
    message.role === "system" &&
    message.parts?.some((part) => part.type === "data-chat-compaction")
  );
}

export function uiMessages(messages: ConversationMessageRead[] = []): UIMessage[] {
  const latestCompactionIndex = messages.findLastIndex(isCompactionMessage);
  const activeMessages =
    latestCompactionIndex >= 0 ? messages.slice(latestCompactionIndex + 1) : messages;
  return activeMessages
    .filter((message) => message.role !== "system")
    .map((message) => ({
      id: message.id,
      metadata: { agentRunId: message.agentRunId },
      role: message.role,
      parts: uiMessageParts(message),
    }));
}

export function markdownText(children: ComponentPropsWithoutRef<"code">["children"]) {
  return Array.isArray(children) ? children.join("") : String(children ?? "");
}

export function MarkdownCode({
  children,
  className,
  ...props
}: ComponentPropsWithoutRef<"code"> & { node?: unknown }) {
  const [copied, setCopied] = useState(false);
  const rawCode = markdownText(children).replace(/\n$/, "");
  const language = /language-(\S+)/.exec(className ?? "")?.[1] ?? "";
  const isBlock = Boolean(language) || rawCode.includes("\n");

  if (!isBlock) {
    return (
      <code
        className="rounded border border-[var(--outline-variant)] bg-[var(--surface-container)] px-1.5 py-0.5 font-mono text-[0.88em]"
        {...props}
      >
        {children}
      </code>
    );
  }

  async function copyCode() {
    await navigator.clipboard.writeText(rawCode);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="my-3 overflow-hidden rounded-md border border-[var(--outline-variant)] bg-slate-950 text-slate-50">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="font-mono text-xs text-slate-300">{language || "code"}</span>
        <Button
          className="h-7 border-white/15 bg-white/5 px-2 text-xs text-slate-100 hover:bg-white/10"
          onClick={copyCode}
          size="sm"
          type="button"
          variant="outline"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-x-auto p-3 text-sm leading-6">
        <code className={className} {...props}>
          {rawCode}
        </code>
      </pre>
    </div>
  );
}

export function markdownComponents(role: MessageRole): Components {
  const isUser = role === "user";
  const subtleText = isUser ? "text-primary-foreground/80" : "text-[var(--on-surface-variant)]";
  return {
    p({ children }) {
      return <p className="mb-3 last:mb-0">{children}</p>;
    },
    a({ children, href }) {
      return (
        <a
          className={cn(
            "font-medium underline underline-offset-4",
            isUser ? "text-primary-foreground" : "text-primary"
          )}
          href={href}
          rel="noreferrer"
          target="_blank"
        >
          {children}
        </a>
      );
    },
    code: MarkdownCode,
    pre({ children }) {
      return <>{children}</>;
    },
    ul({ children }) {
      return <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>;
    },
    li({ children }) {
      return <li className="pl-1">{children}</li>;
    },
    blockquote({ children }) {
      return (
        <blockquote
          className={cn(
            "my-3 border-l-2 pl-3",
            isUser ? "border-primary-foreground/40" : "border-[var(--outline)]",
            subtleText
          )}
        >
          {children}
        </blockquote>
      );
    },
    h1({ children }) {
      return <h1 className="mb-3 text-lg font-semibold">{children}</h1>;
    },
    h2({ children }) {
      return <h2 className="mb-2 text-base font-semibold">{children}</h2>;
    },
    h3({ children }) {
      return <h3 className="mb-2 text-sm font-semibold">{children}</h3>;
    },
    table({ children }) {
      return (
        <div className="my-3 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">{children}</table>
        </div>
      );
    },
    th({ children }) {
      return <th className="border border-[var(--outline-variant)] px-2 py-1">{children}</th>;
    },
    td({ children }) {
      return <td className="border border-[var(--outline-variant)] px-2 py-1">{children}</td>;
    },
    hr() {
      return <hr className="my-4 border-[var(--outline-variant)]" />;
    },
  };
}

export function MessageMarkdown({ role, text }: { role: MessageRole; text: string }) {
  return (
    <ReactMarkdown components={markdownComponents(role)} remarkPlugins={[remarkGfm]}>
      {text}
    </ReactMarkdown>
  );
}

export function ReasoningSummary({ summaries }: { summaries: ReasoningSummaryPart[] }) {
  const text = summaries
    .map((summary) => reasoningSummaryText(summary))
    .filter(Boolean)
    .join("\n\n");
  if (!text) {
    return null;
  }
  return (
    <details className="mb-2 rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-low)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-medium text-[var(--on-surface-variant)]">
        <span className="flex min-w-0 items-center gap-2">
          <Brain className="size-3.5 shrink-0" />
          <span>Thinking</span>
        </span>
        <Badge variant="outline">Reasoning summary</Badge>
      </summary>
      <div className="border-t border-[var(--outline-variant)] px-3 py-2 text-xs leading-5 text-[var(--on-surface-variant)]">
        <MessageMarkdown role="assistant" text={text} />
      </div>
    </details>
  );
}

export function MessageAvatar({ role }: { role: MessageRole }) {
  if (role === "user") {
    return (
      <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-[var(--shadow-card)]">
        <UserRound className="size-4" />
      </div>
    );
  }
  return (
    <div className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-primary shadow-[var(--shadow-card)]">
      <Bot className="size-4" />
    </div>
  );
}

export function MessageLabel({ role }: { role: MessageRole }) {
  if (role === "user") {
    return "You";
  }
  if (role === "system") {
    return "System";
  }
  return "Assistant";
}

export function isToolActivityPart(part: MessagePart): part is ToolActivityPart {
  return part.type === "data-tool-activity";
}

export function isReasoningSummaryPart(part: MessagePart): part is ReasoningSummaryPart {
  return part.type === "data-reasoning-summary";
}

export function reasoningSummaryText(part: ReasoningSummaryPart) {
  const summary = part.data?.summary;
  return typeof summary === "string" ? summary.trim() : "";
}

export function reasoningSummaries(parts: MessagePart[]) {
  const summaries = new Map<string, ReasoningSummaryPart>();
  for (const part of parts) {
    if (!isReasoningSummaryPart(part)) {
      continue;
    }
    const text = reasoningSummaryText(part);
    if (!text) {
      continue;
    }
    summaries.set(text, part);
  }
  return Array.from(summaries.values());
}

export function toolActivities(parts: MessagePart[]) {
  const activities = new Map<string, ToolActivityPart>();
  for (const part of parts) {
    if (!isToolActivityPart(part)) {
      continue;
    }
    const key = part.id ?? `${part.data?.toolName ?? "tool"}-${activities.size}`;
    activities.set(key, part);
  }
  return Array.from(activities.values());
}

export function toolActivitySummary(activities: ToolActivityPart[]) {
  const completed = activities.filter((activity) => activity.data?.status === "completed").length;
  const failed = activities.filter((activity) => activity.data?.status === "failed").length;
  const pending = activities.filter(
    (activity) => activity.data?.status === "requires_confirmation"
  ).length;
  const denied = activities.filter((activity) => activity.data?.status === "denied").length;
  const blocked = activities.filter((activity) => activity.data?.status === "blocked").length;
  if (failed > 0) {
    return `${failed} failed`;
  }
  if (pending > 0) {
    return `${pending} need approval`;
  }
  if (denied > 0) {
    return `${denied} denied`;
  }
  if (blocked > 0) {
    return `${blocked} blocked`;
  }
  if (completed === activities.length) {
    return `${completed} completed`;
  }
  return `${activities.length} running`;
}

export function toolActivityResult(activity: ToolActivityPart) {
  const result = activity.data?.result;
  if (result === undefined || result === null || result === "") {
    return "";
  }
  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}

export function toolActivityDetails(activity: ToolActivityPart) {
  const details = activity.data?.details;
  if (details === undefined || details === null || details === "") {
    return "";
  }
  return typeof details === "string" ? details : JSON.stringify(details, null, 2);
}

export function toolActivityArguments(activity: ToolActivityPart) {
  const args = activity.data?.arguments;
  if (args === undefined || args === null || args === "") {
    return "";
  }
  return typeof args === "string" ? args : JSON.stringify(args, null, 2);
}

export function toolActivityProgress(activity: ToolActivityPart) {
  const progress = activity.data?.progress;
  if (typeof progress !== "number" || !Number.isFinite(progress)) {
    return null;
  }
  const total = activity.data?.total;
  if (typeof total === "number" && Number.isFinite(total) && total > 0) {
    const percent = Math.max(0, Math.min(100, (progress / total) * 100));
    return {
      label: `${Math.round(percent)}%`,
      percent,
    };
  }
  return {
    label: `${progress}`,
    percent: null,
  };
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function actionReviewValue(review: ActionReviewData | undefined) {
  return review && typeof review === "object" ? review : null;
}

export function toolActivityActionReview(activity: ToolActivityPart) {
  const approvalReview = actionReviewValue(activity.data?.approval?.actionReview);
  if (approvalReview) {
    return approvalReview;
  }
  const details = objectValue(activity.data?.details);
  return actionReviewValue(details?.actionReview as ActionReviewData | undefined);
}

export function actionReviewArguments(review: ActionReviewData) {
  const args = review.normalizedArguments;
  if (args === undefined || args === null || args === "") {
    return "";
  }
  return typeof args === "string" ? args : JSON.stringify(args, null, 2);
}

export function toolActivityStatusLabel(status: string) {
  if (status === "requires_confirmation") {
    return "Needs approval";
  }
  return status.replace(/_/g, " ");
}

export function agentRunIdFromMessage(message: UIMessage) {
  const metadata = "metadata" in message ? message.metadata : null;
  if (!metadata || typeof metadata !== "object") {
    return null;
  }
  const value = (metadata as { agentRunId?: unknown }).agentRunId;
  return typeof value === "string" && value ? value : null;
}

export function ActionReview({ review }: { review: ActionReviewData }) {
  const connection = review.targetConnection ?? {};
  const environment = review.targetEnvironment ?? {};
  const tool = review.tool ?? {};
  const policy = review.matchingPolicy ?? {};
  const args = actionReviewArguments(review);
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
      value: [stringValue(tool.name), stringValue(tool.title)].filter(Boolean).join(" / "),
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
  ].filter((row) => row.value);

  return (
    <div className="mt-3 rounded border border-amber-200 bg-amber-50/70 text-xs text-amber-950">
      <div className="border-b border-amber-200 px-3 py-2 font-medium">Action review</div>
      <dl className="grid gap-2 px-3 py-2 sm:grid-cols-[9rem_minmax(0,1fr)]">
        {rows.map((row) => (
          <div className="contents" key={row.label}>
            <dt className="font-medium text-amber-900">{row.label}</dt>
            <dd className="min-w-0 break-words font-mono text-[11px] text-amber-950">
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
      {stringValue(policy.message) ? (
        <div className="border-t border-amber-200 px-3 py-2 text-amber-900">
          {policy.message}
        </div>
      ) : null}
      {args ? (
        <details className="border-t border-amber-200">
          <summary className="cursor-pointer px-3 py-2 font-medium text-amber-900">
            Normalized arguments
          </summary>
          <pre className="max-h-52 overflow-auto border-t border-amber-200 px-3 py-2 font-mono text-[11px] leading-5 whitespace-pre-wrap">
            {args}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

export function ToolActivity({
  approvalDecisions = {},
  activities,
  onDecideApproval,
  summaries = [],
  traceHref,
}: {
  approvalDecisions?: Record<string, string>;
  activities: ToolActivityPart[];
  onDecideApproval?: (activity: ToolActivityPart, decision: "approve" | "deny") => void;
  summaries?: ReasoningSummaryPart[];
  traceHref?: string;
}) {
  const reasoningText = summaries
    .map((summary) => reasoningSummaryText(summary))
    .filter(Boolean)
    .join("\n\n");
  if (activities.length === 0 && !reasoningText) {
    return null;
  }
  const summaryBadge = activities.length > 0 ? toolActivitySummary(activities) : "Reasoning";
  const shouldOpen =
    Boolean(reasoningText) ||
    activities.some((activity) => {
      const status = activity.data?.status ?? "running";
      return status !== "completed";
    });
  return (
    <details
      className="mb-3 rounded-md border border-border bg-muted/35"
      open={shouldOpen}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-medium text-muted-foreground">
        <span className="flex min-w-0 items-center gap-2">
          <Brain className="size-3.5 shrink-0" />
          <span>Agent activity</span>
        </span>
        <span className="flex items-center gap-2">
          {traceHref ? (
            <Link
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-2 py-0.5 text-xs text-foreground hover:bg-muted"
              href={traceHref}
            >
              <ListTree className="size-3" />
              Trace
            </Link>
          ) : null}
          {reasoningText ? <Badge variant="outline">Reasoning summary</Badge> : null}
          <Badge variant="outline">{summaryBadge}</Badge>
        </span>
      </summary>
      <div className="border-t border-border px-3 py-2">
        {reasoningText ? (
          <div className="mb-3 rounded border border-border bg-card px-2 py-2 text-xs leading-5 text-muted-foreground">
            <MessageMarkdown role="assistant" text={reasoningText} />
          </div>
        ) : null}
        {activities.length > 0 ? (
        <div>
          {activities.map((activity, index) => {
            const status = activity.data?.status ?? "running";
            const isDone = status === "completed";
            const isFailed = status === "failed";
            const isBlocked = status === "blocked";
            const isDenied = status === "denied";
            const needsConfirmation = status === "requires_confirmation";
            const approvalId = activity.data?.approval?.id ?? "";
            const isApprovalPending =
              needsConfirmation &&
              approvalId &&
              (activity.data?.approval?.status ?? "pending") === "pending";
            const decisionInFlight = approvalId ? approvalDecisions[approvalId] : "";
            const args = toolActivityArguments(activity);
            const result = toolActivityResult(activity);
            const details = toolActivityDetails(activity);
            const progress = toolActivityProgress(activity);
            const failureReason = activity.data?.failureReason ?? "";
            const actionReview = needsConfirmation ? toolActivityActionReview(activity) : null;
            const activityMessage =
              isFailed || isBlocked || isDenied || needsConfirmation
                ? activity.data?.error ?? toolActivityStatusLabel(status)
                : activity.data?.message ?? toolActivityStatusLabel(status);
            return (
              <div
                className="grid grid-cols-[2rem_minmax(0,1fr)] gap-2 border-b border-border py-2 text-xs last:border-b-0"
                key={activity.id ?? `${activity.data?.toolName}-${status}`}
              >
                <div className="flex flex-col items-center">
                  <span className="flex size-6 items-center justify-center rounded-sm border border-border bg-card font-mono text-[11px] text-muted-foreground">
                    {index + 1}
                  </span>
                  {index < activities.length - 1 ? (
                    <span className="mt-1 w-px flex-1 bg-border" />
                  ) : null}
                </div>
                <div className="min-w-0">
                  <div className="flex min-w-0 items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-2 font-medium text-foreground">
                        {isDone ? (
                          <CheckCircle2 className="size-3.5 shrink-0 text-emerald-600" />
                        ) : isBlocked || isDenied ? (
                          <ShieldOff className="size-3.5 shrink-0 text-amber-700" />
                        ) : needsConfirmation ? (
                          <CircleAlert className="size-3.5 shrink-0 text-amber-600" />
                        ) : isFailed ? (
                          <Square className="size-3.5 shrink-0 text-red-600" />
                        ) : (
                          <Loader2 className="size-3.5 shrink-0 animate-spin text-[var(--on-surface-variant)]" />
                        )}
                        <span className="min-w-0 truncate">
                          {activity.data?.toolName ?? "MCP tool"}
                        </span>
                      </div>
                      <div className="mt-1 break-words text-[var(--on-surface-variant)]">
                        {activityMessage}
                      </div>
                    </div>
                    <Badge className="shrink-0 capitalize" variant="outline">
                      {toolActivityStatusLabel(status)}
                    </Badge>
                  </div>
                  {failureReason ? (
                    <div className="mt-2">
                      <Badge className="font-mono" variant="secondary">
                        {failureReason}
                      </Badge>
                    </div>
                  ) : null}
                  {progress ? (
                    <div className="mt-2 max-w-sm">
                      {progress.percent !== null ? (
                        <div className="h-1.5 overflow-hidden rounded-sm bg-[var(--surface-container)]">
                          <div
                            className="h-full rounded-sm bg-[var(--primary)] transition-[width]"
                            style={{ width: `${progress.percent}%` }}
                          />
                        </div>
                      ) : null}
                      <div className="mt-1 font-mono text-[11px] text-[var(--on-surface-variant)]">
                        {progress.label}
                      </div>
                    </div>
                  ) : null}
                  {actionReview ? <ActionReview review={actionReview} /> : null}
                  {isApprovalPending && onDecideApproval ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button
                        className="h-8 px-2.5 text-xs"
                        disabled={Boolean(decisionInFlight)}
                        onClick={() => onDecideApproval(activity, "approve")}
                        size="sm"
                        type="button"
                      >
                        {decisionInFlight === "approve" ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <CheckCircle2 className="size-3.5" />
                        )}
                        Approve
                      </Button>
                      <Button
                        className="h-8 px-2.5 text-xs"
                        disabled={Boolean(decisionInFlight)}
                        onClick={() => onDecideApproval(activity, "deny")}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        {decisionInFlight === "deny" ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <ShieldOff className="size-3.5" />
                        )}
                        Deny
                      </Button>
                    </div>
                  ) : null}
                  {args ? (
                    <details className="mt-2 rounded border border-border bg-card">
                      <summary className="cursor-pointer px-2 py-1.5 font-medium text-muted-foreground">
                        Arguments
                      </summary>
                      <pre className="max-h-52 overflow-auto border-t border-border px-2 py-2 font-mono text-[11px] leading-5 text-foreground whitespace-pre-wrap">
                        {args}
                      </pre>
                    </details>
                  ) : null}
                  {details ? (
                    <details className="mt-2 rounded border border-border bg-card">
                      <summary className="cursor-pointer px-2 py-1.5 font-medium text-muted-foreground">
                        Evidence
                      </summary>
                      <pre className="max-h-52 overflow-auto border-t border-border px-2 py-2 font-mono text-[11px] leading-5 text-foreground whitespace-pre-wrap">
                        {details}
                      </pre>
                    </details>
                  ) : null}
                  {result ? (
                    <details className="mt-2 rounded border border-border bg-card">
                      <summary className="cursor-pointer px-2 py-1.5 font-medium text-muted-foreground">
                        Result
                      </summary>
                      <pre className="max-h-52 overflow-auto border-t border-border px-2 py-2 font-mono text-[11px] leading-5 text-foreground whitespace-pre-wrap">
                        {result}
                      </pre>
                    </details>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
        ) : null}
      </div>
    </details>
  );
}

export function providerLabel(credential: LlmCredentialRead) {
  if (credential.provider === "openai_chatgpt" || credential.authMethod === "oauth") {
    return "OpenAI ChatGPT";
  }
  if (credential.provider === "openai") {
    return "OpenAI";
  }
  return credential.provider;
}

export function credentialLabel(credentials: LlmCredentialRead[], credentialId?: string | null) {
  if (!credentialId) {
    return "No credential selected";
  }
  const credential = credentials.find((entry) => entry.id === credentialId);
  if (!credential) {
    return credentialId;
  }
  return `${credential.name} (${providerLabel(credential)})`;
}
