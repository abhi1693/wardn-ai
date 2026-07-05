"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import {
  Bot,
  Check,
  CheckCircle2,
  CircleAlert,
  Copy,
  Info,
  ListTree,
  Loader2,
  Pencil,
  Send,
  ShieldOff,
  Square,
  UserRound,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import {
  type ComponentPropsWithoutRef,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type {
  AgentRead,
  ConversationMessageRead,
  OrganizationRead,
  WorkspaceConversationRead,
} from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

import type { LlmCredentialRead } from "../../llm-credentials/types";

type AgentChatClientProps = {
  agent: AgentRead;
  conversation?: WorkspaceConversationRead | null;
  credentials: LlmCredentialRead[];
  initialMessages?: ConversationMessageRead[];
  organization: OrganizationRead;
  workspaceId: string;
};

type MessageRole = UIMessage["role"];
type MessagePart = UIMessage["parts"][number];
type ToolApprovalData = {
  id?: string;
  status?: string;
};
type ToolActivityData = {
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
type ToolActivityPart = MessagePart & {
  data?: ToolActivityData;
  id?: string;
  type: "data-tool-activity";
};

function isTextPart(part: MessagePart): part is Extract<MessagePart, { type: "text" }> {
  return part.type === "text" && typeof part.text === "string";
}

function messageText(parts: MessagePart[]) {
  return parts
    .filter(isTextPart)
    .map((part) => part.text)
    .join("");
}

function textPart(text: string) {
  return { type: "text" as const, text };
}

function uiMessageParts(message: ConversationMessageRead): UIMessage["parts"] {
  return message.parts?.length
    ? (message.parts as UIMessage["parts"])
    : ([textPart(message.content)] as UIMessage["parts"]);
}

function uiMessages(messages: ConversationMessageRead[] = []): UIMessage[] {
  return messages.map((message) => ({
    id: message.id,
    metadata: { agentRunId: message.agentRunId },
    role: message.role,
    parts: uiMessageParts(message),
  }));
}

function markdownText(children: ComponentPropsWithoutRef<"code">["children"]) {
  return Array.isArray(children) ? children.join("") : String(children ?? "");
}

function MarkdownCode({
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

function markdownComponents(role: MessageRole): Components {
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

function MessageMarkdown({ role, text }: { role: MessageRole; text: string }) {
  return (
    <ReactMarkdown components={markdownComponents(role)} remarkPlugins={[remarkGfm]}>
      {text}
    </ReactMarkdown>
  );
}

function MessageAvatar({ role }: { role: MessageRole }) {
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

function MessageLabel({ role }: { role: MessageRole }) {
  if (role === "user") {
    return "You";
  }
  if (role === "system") {
    return "System";
  }
  return "Assistant";
}

function isToolActivityPart(part: MessagePart): part is ToolActivityPart {
  return part.type === "data-tool-activity";
}

function toolActivities(parts: MessagePart[]) {
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

function toolActivitySummary(activities: ToolActivityPart[]) {
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

function toolActivityResult(activity: ToolActivityPart) {
  const result = activity.data?.result;
  if (result === undefined || result === null || result === "") {
    return "";
  }
  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}

function toolActivityProgress(activity: ToolActivityPart) {
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

function agentRunIdFromMessage(message: UIMessage) {
  const metadata = "metadata" in message ? message.metadata : null;
  if (!metadata || typeof metadata !== "object") {
    return null;
  }
  const value = (metadata as { agentRunId?: unknown }).agentRunId;
  return typeof value === "string" && value ? value : null;
}

function ToolActivity({
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
    <details className="mb-2 rounded-md border border-[var(--outline-variant)] bg-[var(--surface-container-low)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-medium text-[var(--on-surface-variant)]">
        <span className="flex min-w-0 items-center gap-2">
          <Wrench className="size-3.5 shrink-0" />
          <span>Tool activity</span>
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
        <div className="space-y-1.5">
          {activities.map((activity) => {
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
            const result = toolActivityResult(activity);
            const progress = toolActivityProgress(activity);
            return (
              <div
                className="rounded-md bg-white px-2.5 py-2 text-xs"
                key={activity.id ?? `${activity.data?.toolName}-${status}`}
              >
                <div className="flex items-start gap-2">
                  {isDone ? (
                    <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
                  ) : isBlocked || isDenied ? (
                    <ShieldOff className="mt-0.5 size-3.5 shrink-0 text-amber-700" />
                  ) : needsConfirmation ? (
                    <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
                  ) : isFailed ? (
                    <Square className="mt-0.5 size-3.5 shrink-0 text-red-600" />
                  ) : (
                    <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-[var(--on-surface-variant)]" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-[var(--on-surface)]">
                      {activity.data?.toolName ?? "MCP tool"}
                    </div>
                    <div className="mt-0.5 text-[var(--on-surface-variant)]">
                      {isFailed || isBlocked || isDenied || needsConfirmation
                        ? activity.data?.error ?? status
                        : activity.data?.message ?? status}
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
                  </div>
                </div>
                {isApprovalPending && onDecideApproval ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 pl-5">
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
                {result ? (
                  <details className="mt-2 rounded border border-[var(--outline-variant)] bg-[var(--surface-container-low)]">
                    <summary className="cursor-pointer px-2 py-1.5 font-medium text-[var(--on-surface-variant)]">
                      Result
                    </summary>
                    <pre className="max-h-52 overflow-auto border-t border-[var(--outline-variant)] px-2 py-2 font-mono text-[11px] leading-5 text-[var(--on-surface)] whitespace-pre-wrap">
                      {result}
                    </pre>
                  </details>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </details>
  );
}

function providerLabel(credential: LlmCredentialRead) {
  if (credential.provider === "openai_chatgpt" || credential.authMethod === "oauth") {
    return "OpenAI ChatGPT";
  }
  if (credential.provider === "openai") {
    return "OpenAI";
  }
  return credential.provider;
}

function credentialLabel(credentials: LlmCredentialRead[], credentialId?: string | null) {
  if (!credentialId) {
    return "No credential selected";
  }
  const credential = credentials.find((entry) => entry.id === credentialId);
  if (!credential) {
    return credentialId;
  }
  return `${credential.name} (${providerLabel(credential)})`;
}

export function AgentChatClient({
  agent,
  conversation = null,
  credentials,
  initialMessages = [],
  organization,
  workspaceId,
}: AgentChatClientProps) {
  const [input, setInput] = useState("");
  const [approvalDecisions, setApprovalDecisions] = useState<Record<string, string>>({});
  const [lastSubmittedText, setLastSubmittedText] = useState("");
  const chatApi = `/api/organizations/${organization.id}/workspaces/${workspaceId}/agents/${agent.id}/chat`;
  const persistedMessages = useMemo(() => uiMessages(initialMessages), [initialMessages]);
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: chatApi,
      }),
    [chatApi]
  );
  const { error, messages, sendMessage, setMessages, status, stop } = useChat({
    id: conversation?.id,
    messages: persistedMessages,
    transport,
  });
  const isRunning = status === "submitted" || status === "streaming";
  const transcriptViewportRef = useRef<HTMLDivElement | null>(null);
  const serverLabel = agent.serverCount === 1 ? "1 server" : `${agent.serverCount} servers`;
  const toolLabel = agent.toolCount === 1 ? "1 tool" : `${agent.toolCount} tools`;
  const editPath = `/org/${organization.id}/workspace/${workspaceId}/agents/${agent.id}/edit`;

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning) {
      return;
    }
    setInput("");
    setLastSubmittedText(text);
    await sendMessage({ text });
  }

  async function retryLastMessage() {
    const text = lastSubmittedText.trim();
    if (!text || isRunning) {
      return;
    }
    await sendMessage({ text });
  }

  function updateApprovalActivity(
    approvalId: string,
    update: { error?: string; result?: unknown; status: string }
  ) {
    setMessages((currentMessages) =>
      currentMessages.map((message) => ({
        ...message,
        parts: message.parts.map((part) => {
          if (!isToolActivityPart(part) || part.data?.approval?.id !== approvalId) {
            return part;
          }
          const nextData: ToolActivityData = {
            ...part.data,
            approval: {
              ...part.data.approval,
              status: update.status,
            },
            status: update.status,
          };
          if (update.result !== undefined && update.result !== "") {
            nextData.result = update.result;
          } else {
            delete nextData.result;
          }
          if (update.error) {
            nextData.error = update.error;
          } else {
            delete nextData.error;
          }
          return { ...part, data: nextData } as MessagePart;
        }),
      }))
    );
  }

  function appendAssistantMessage(message: ConversationMessageRead | null | undefined) {
    if (!message) {
      return;
    }
    const [nextMessage] = uiMessages([message]);
    setMessages((currentMessages) => {
      if (currentMessages.some((entry) => entry.id === nextMessage.id)) {
        return currentMessages;
      }
      return [...currentMessages, nextMessage];
    });
  }

  async function decideToolApproval(activity: ToolActivityPart, decision: "approve" | "deny") {
    const approvalId = activity.data?.approval?.id;
    if (!approvalId || approvalDecisions[approvalId]) {
      return;
    }
    setApprovalDecisions((current) => ({ ...current, [approvalId]: decision }));
    try {
      const response = await fetch(
        `/api/organizations/${organization.id}/workspaces/${workspaceId}/agents/${agent.id}/tool-approvals/${approvalId}`,
        {
          body: JSON.stringify({ decision }),
          headers: { "Content-Type": "application/json" },
          method: "POST",
        }
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "Approval failed");
      }
      updateApprovalActivity(approvalId, {
        error: typeof data.error === "string" ? data.error : "",
        result: data.result,
        status: typeof data.status === "string" ? data.status : "failed",
      });
      appendAssistantMessage(data.assistantMessage);
    } catch (approvalError) {
      updateApprovalActivity(approvalId, {
        error:
          approvalError instanceof Error
            ? approvalError.message
            : "Approval failed",
        status: "requires_confirmation",
      });
    } finally {
      setApprovalDecisions((current) => {
        const next = { ...current };
        delete next[approvalId];
        return next;
      });
    }
  }

  useEffect(() => {
    window.requestAnimationFrame(() => {
      const viewport = transcriptViewportRef.current;
      if (!viewport) {
        return;
      }
      viewport.scrollTop = viewport.scrollHeight;
    });
  }, [messages, status]);

  return (
    <div className="flex h-[calc(100dvh-4rem)] min-h-0 w-full flex-col overflow-hidden bg-white max-lg:h-[calc(100dvh-11.75rem)]">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="shrink-0 border-b border-[var(--outline-variant)] bg-white px-8 py-4 max-md:px-4">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-primary-foreground">
                  <Bot className="size-4" />
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold leading-6">{agent.name}</h2>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Badge className="font-mono" variant="outline">
                      {agent.modelName || "No model"}
                    </Badge>
                    <Badge variant={agent.serverCount > 0 ? "secondary" : "outline"}>
                      {serverLabel}
                    </Badge>
                    <Badge variant={agent.toolCount > 0 ? "secondary" : "outline"}>
                      {toolLabel}
                    </Badge>
                  </div>
                </div>
              </div>
            </div>

            <Dialog>
              <DialogTrigger asChild>
                <Button className="shrink-0" size="sm" type="button" variant="outline">
                  <Info className="size-4" />
                  Details
                </Button>
              </DialogTrigger>
              <DialogContent className="top-0 right-0 left-auto flex h-dvh max-w-md translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-y-0 border-r-0 p-0 sm:w-[420px]">
                <DialogHeader className="border-b border-[var(--outline-variant)] px-5 py-4">
                  <DialogTitle>{agent.name}</DialogTitle>
                  <DialogDescription>Workspace chat details</DialogDescription>
                </DialogHeader>
                <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5 text-sm">
                  <section className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                      Model
                    </h3>
                    <div className="rounded-md border border-[var(--outline-variant)] bg-white px-3 py-2">
                      <div className="font-mono text-sm">{agent.modelName || "No model"}</div>
                    </div>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                      Credential
                    </h3>
                    <div className="rounded-md border border-[var(--outline-variant)] bg-white px-3 py-2">
                      <div className="truncate">
                        {credentialLabel(credentials, agent.providerCredentialId)}
                      </div>
                    </div>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                      MCP servers
                    </h3>
                    <div className="flex items-center justify-between rounded-md border border-[var(--outline-variant)] bg-white px-3 py-2">
                      <span>Bound to this chat</span>
                      <Badge variant={agent.serverCount > 0 ? "secondary" : "outline"}>
                        {serverLabel}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between rounded-md border border-[var(--outline-variant)] bg-white px-3 py-2">
                      <span>Discovered tools</span>
                      <Badge variant={agent.toolCount > 0 ? "secondary" : "outline"}>
                        {toolLabel}
                      </Badge>
                    </div>
                  </section>

                  <section className="space-y-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                      Agent settings
                    </h3>
                    <div className="space-y-3 rounded-md border border-[var(--outline-variant)] bg-white px-3 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[var(--on-surface-variant)]">Status</span>
                        <Badge variant={agent.isActive ? "success" : "secondary"}>
                          {agent.isActive ? "Active" : "Inactive"}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[var(--on-surface-variant)]">Scope</span>
                        <span>{agent.scope}</span>
                      </div>
                      <Button asChild className="w-full" size="sm" variant="outline">
                        <Link href={editPath}>
                          <Pencil className="size-4" />
                          Edit agent
                        </Link>
                      </Button>
                    </div>
                  </section>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        </div>

        <div
          className="min-h-0 flex-1 overflow-y-auto bg-[var(--surface-bright)]"
          ref={transcriptViewportRef}
        >
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-7 px-8 py-8 max-md:px-4">
            {messages.length === 0 ? (
              <div className="flex min-h-96 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--outline-variant)] bg-white text-center shadow-[var(--shadow-card)]">
                <div className="mb-3 flex size-10 items-center justify-center rounded-md bg-[var(--surface-container)] text-primary">
                  <Bot className="size-5" />
                </div>
                <div className="text-sm font-semibold">Start a conversation</div>
                <div className="mt-1 text-sm text-[var(--on-surface-variant)]">
                  {serverLabel}
                  {agent.serverCount > 0 ? " connected" : ""}
                </div>
              </div>
            ) : (
              messages.map((message) => {
                const text = messageText(message.parts);
                const activities = toolActivities(message.parts);
                const isUser = message.role === "user";
                if (!text && activities.length === 0) {
                  return null;
                }
                const agentRunId = agentRunIdFromMessage(message);
                const traceHref = agentRunId
                  ? `/org/${organization.id}/workspace/${workspaceId}/agent-runs/${agentRunId}`
                  : undefined;
                return (
                  <div
                    className={cn("group flex gap-3", isUser ? "justify-end" : "justify-start")}
                    key={message.id}
                  >
                    {!isUser ? <MessageAvatar role={message.role} /> : null}
                    <div
                      className={cn(
                        "min-w-0",
                        isUser ? "max-w-[720px]" : "max-w-[900px] flex-1"
                      )}
                    >
                      <div
                        className={cn(
                          "mb-1.5 text-xs font-medium text-[var(--on-surface-variant)]",
                          isUser && "text-right"
                        )}
                      >
                        <MessageLabel role={message.role} />
                      </div>
                      <div
                        className={cn(
                          "overflow-hidden border px-4 py-3 text-sm leading-6",
                          isUser
                            ? "rounded-md border-primary bg-primary text-primary-foreground shadow-[var(--shadow-card)]"
                            : "rounded-lg border-[var(--outline-variant)] bg-white shadow-[0_1px_2px_rgb(15_23_42/0.04)]"
                        )}
                      >
                        {!isUser ? (
                          <ToolActivity
                            activities={activities}
                            approvalDecisions={approvalDecisions}
                            onDecideApproval={decideToolApproval}
                            traceHref={traceHref}
                          />
                        ) : null}
                        {text ? <MessageMarkdown role={message.role} text={text} /> : null}
                      </div>
                    </div>
                    {isUser ? <MessageAvatar role={message.role} /> : null}
                  </div>
                );
              })
            )}

            {status === "submitted" ? (
              <div className="flex items-center gap-3">
                <MessageAvatar role="assistant" />
                <div className="flex items-center gap-2 rounded-lg border border-[var(--outline-variant)] bg-white px-3 py-2 text-sm text-[var(--on-surface-variant)] shadow-[var(--shadow-card)]">
                  <Loader2 className="size-4 animate-spin" />
                  Thinking
                </div>
              </div>
            ) : null}

            {error ? (
              <div className="flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                <span>{error.message}</span>
                <Button
                  className="h-8 border-red-200 bg-white px-3 text-xs text-red-700 hover:bg-red-50"
                  disabled={!lastSubmittedText || isRunning}
                  onClick={retryLastMessage}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Retry
                </Button>
              </div>
            ) : null}
          </div>
        </div>

        <div className="shrink-0 border-t border-[var(--outline-variant)] bg-white px-8 py-4 max-md:px-4">
          <form
            className="mx-auto flex w-full max-w-5xl items-end gap-2 rounded-lg border border-[var(--outline-variant)] bg-white p-2 shadow-[0_8px_24px_rgb(15_23_42/0.08)] transition-colors focus-within:border-[var(--ring)] focus-within:ring-2 focus-within:ring-sky-100"
            onSubmit={submitMessage}
          >
            <textarea
              className="max-h-40 min-h-12 flex-1 resize-none rounded-md border-0 bg-transparent px-3 py-2 text-sm leading-6 outline-none placeholder:text-[var(--on-surface-variant)]"
              disabled={isRunning}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Message this workspace"
              value={input}
            />
            {isRunning ? (
              <Button
                aria-label="Stop response"
                onClick={stop}
                size="icon"
                type="button"
                variant="secondary"
              >
                <Square className="size-4" />
              </Button>
            ) : (
              <Button aria-label="Send message" disabled={!input.trim()} size="icon" type="submit">
                <Send className="size-4" />
              </Button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
