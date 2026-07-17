import type { UIMessage } from "ai";
import {
  Bot,
  Check,
  CheckCircle2,
  CircleAlert,
  Copy,
  ListTree,
  Loader2,
  ShieldOff,
  Square,
  UserRound,
  Wrench,
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
  id?: string;
  status?: string;
};
export type ToolActivityData = {
  approval?: ToolApprovalData;
  arguments?: unknown;
  error?: string;
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

export function uiMessages(messages: ConversationMessageRead[] = []): UIMessage[] {
  return messages.map((message) => ({
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

export function MessageAvatar({ role }: { role: MessageRole }) {
  if (role === "user") {
    return (
      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-primary-foreground">
        <UserRound className="size-4" />
      </div>
    );
  }
  return (
    <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-[var(--outline-variant)] bg-white text-primary">
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

export function ToolActivity({
  approvalDecisions = {},
  activities,
  onDecideApproval,
  traceHref,
}: {
  approvalDecisions?: Record<string, string>;
  activities: ToolActivityPart[];
  onDecideApproval?: (activity: ToolActivityPart, decision: "approve" | "deny") => void;
  traceHref?: string;
}) {
  if (activities.length === 0) {
    return null;
  }
  return (
    <details
      className="mb-2 rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-low)]"
      open
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-medium text-[var(--on-surface-variant)]">
        <span className="flex min-w-0 items-center gap-2">
          <Wrench className="size-3.5 shrink-0" />
          <span>Tool steps</span>
        </span>
        <span className="flex items-center gap-2">
          {traceHref ? (
            <Link
              className="inline-flex items-center gap-1 rounded-sm border border-[var(--outline-variant)] bg-white px-2 py-0.5 text-xs text-[var(--on-surface)] hover:bg-[var(--surface-container)]"
              href={traceHref}
            >
              <ListTree className="size-3" />
              Trace
            </Link>
          ) : null}
          <Badge variant="outline">{toolActivitySummary(activities)}</Badge>
        </span>
      </summary>
      <div className="border-t border-[var(--outline-variant)] px-3 py-2">
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
            const progress = toolActivityProgress(activity);
            const activityMessage =
              isFailed || isBlocked || isDenied || needsConfirmation
                ? activity.data?.error ?? toolActivityStatusLabel(status)
                : activity.data?.message ?? toolActivityStatusLabel(status);
            return (
              <div
                className="grid grid-cols-[2rem_minmax(0,1fr)] gap-2 border-b border-[var(--outline-variant)] py-2 text-xs last:border-b-0"
                key={activity.id ?? `${activity.data?.toolName}-${status}`}
              >
                <div className="flex flex-col items-center">
                  <span className="flex size-6 items-center justify-center rounded-sm border border-[var(--outline-variant)] bg-white font-mono text-[11px] text-[var(--on-surface-variant)]">
                    {index + 1}
                  </span>
                  {index < activities.length - 1 ? (
                    <span className="mt-1 w-px flex-1 bg-[var(--outline-variant)]" />
                  ) : null}
                </div>
                <div className="min-w-0">
                  <div className="flex min-w-0 items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-2 font-medium text-[var(--on-surface)]">
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
                    <details className="mt-2 rounded border border-[var(--outline-variant)] bg-white">
                      <summary className="cursor-pointer px-2 py-1.5 font-medium text-[var(--on-surface-variant)]">
                        Arguments
                      </summary>
                      <pre className="max-h-52 overflow-auto border-t border-[var(--outline-variant)] px-2 py-2 font-mono text-[11px] leading-5 text-[var(--on-surface)] whitespace-pre-wrap">
                        {args}
                      </pre>
                    </details>
                  ) : null}
                  {result ? (
                    <details className="mt-2 rounded border border-[var(--outline-variant)] bg-white">
                      <summary className="cursor-pointer px-2 py-1.5 font-medium text-[var(--on-surface-variant)]">
                        Result
                      </summary>
                      <pre className="max-h-52 overflow-auto border-t border-[var(--outline-variant)] px-2 py-2 font-mono text-[11px] leading-5 text-[var(--on-surface)] whitespace-pre-wrap">
                        {result}
                      </pre>
                    </details>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
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
