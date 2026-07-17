"use client";

import { apiStreamFetch, apiUrl } from "@/lib/api/client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { Bot, Info, Loader2, Pencil, Send, Square } from "lucide-react";
import Link from "next/link";
import {
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Badge } from "@/components/ui/badge";
import { AsyncFeedback } from "@/components/ui/async-feedback";
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
import { workspaceAgentsDecideToolApproval } from "@/lib/api/generated/workspace-agents/workspace-agents";
import { cn } from "@/lib/utils";

import type { LlmCredentialRead } from "../../llm-credentials/types";
import {
  agentRunIdFromMessage,
  credentialLabel,
  isToolActivityPart,
  messageText,
  MessageAvatar,
  MessageLabel,
  MessageMarkdown,
  ToolActivity,
  toolActivities,
  uiMessages,
  type MessagePart,
  type ToolActivityData,
  type ToolActivityPart,
} from "./agent-chat-messages";

type AgentChatClientProps = {
  agent: AgentRead;
  conversation?: WorkspaceConversationRead | null;
  credentials: LlmCredentialRead[];
  initialMessages?: ConversationMessageRead[];
  organization: OrganizationRead;
  workspaceId: string;
};


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
  const chatApi = `/api/v1/organizations/${organization.id}/workspaces/${workspaceId}/agents/${agent.id}/chat`;
  const persistedMessages = useMemo(() => uiMessages(initialMessages), [initialMessages]);
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: apiUrl(chatApi),
        credentials: "include",
        fetch: apiStreamFetch,
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
      const data = await workspaceAgentsDecideToolApproval(
        organization.id,
        workspaceId,
        agent.id,
        approvalId,
        { decision }
      );
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
              <div aria-live="polite" className="flex items-center gap-3" role="status">
                <MessageAvatar role="assistant" />
                <div className="flex items-center gap-2 rounded-lg border border-[var(--outline-variant)] bg-white px-3 py-2 text-sm text-[var(--on-surface-variant)] shadow-[var(--shadow-card)]">
                  <Loader2 className="size-4 animate-spin" />
                  Thinking
                </div>
              </div>
            ) : null}

            {error ? (
              <AsyncFeedback className="flex items-center justify-between gap-3" variant="error">
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
              </AsyncFeedback>
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
