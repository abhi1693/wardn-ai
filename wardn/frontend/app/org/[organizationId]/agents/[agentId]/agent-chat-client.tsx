"use client";

import { useChat } from "@ai-sdk/react";
import { TextStreamChatTransport, type UIMessage } from "ai";
import { Bot, Check, Copy, Info, Loader2, Pencil, Send, Square } from "lucide-react";
import Link from "next/link";
import { type ComponentPropsWithoutRef, type FormEvent, useMemo, useState } from "react";
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

function messageText(parts: Array<{ type: string; text?: string }>) {
  return parts
    .filter((part) => part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}

function textPart(text: string) {
  return { type: "text" as const, text };
}

function uiMessageParts(message: ConversationMessageRead): UIMessage["parts"] {
  const parts = message.parts?.filter(
    (part): part is { type: "text"; text: string } =>
      part.type === "text" && typeof part.text === "string"
  );
  return parts?.length ? parts : [textPart(message.content)];
}

function uiMessages(messages: ConversationMessageRead[] = []): UIMessage[] {
  return messages.map((message) => ({
    id: message.id,
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
  const chatApi = `/api/organizations/${organization.id}/workspaces/${workspaceId}/agents/${agent.id}/chat`;
  const persistedMessages = useMemo(() => uiMessages(initialMessages), [initialMessages]);
  const transport = useMemo(
    () =>
      new TextStreamChatTransport({
        api: chatApi,
      }),
    [chatApi]
  );
  const { error, messages, sendMessage, status, stop } = useChat({
    id: conversation?.id,
    messages: persistedMessages,
    transport,
  });
  const isRunning = status === "submitted" || status === "streaming";
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
    await sendMessage({ text });
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-140px)] w-full max-w-6xl flex-col">
      <div className="sticky top-0 z-10 border-b border-[var(--outline-variant)] bg-[var(--background)]/95 py-3 backdrop-blur">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{agent.name}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Badge variant="outline">{agent.modelName || "No model"}</Badge>
              <Badge variant={agent.serverCount > 0 ? "secondary" : "outline"}>
                {serverLabel}
              </Badge>
              <Badge variant={agent.toolCount > 0 ? "secondary" : "outline"}>{toolLabel}</Badge>
            </div>
          </div>
          <Dialog>
            <DialogTrigger asChild>
              <Button size="sm" type="button" variant="outline">
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
                  <div className="rounded-md border border-[var(--outline-variant)] px-3 py-2">
                    <div className="font-mono text-sm">{agent.modelName || "No model"}</div>
                  </div>
                </section>

                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                    Credential
                  </h3>
                  <div className="rounded-md border border-[var(--outline-variant)] px-3 py-2">
                    <div className="truncate">
                      {credentialLabel(credentials, agent.providerCredentialId)}
                    </div>
                  </div>
                </section>

                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--on-surface-variant)]">
                    MCP servers
                  </h3>
                  <div className="flex items-center justify-between rounded-md border border-[var(--outline-variant)] px-3 py-2">
                    <span>Bound to this chat</span>
                    <Badge variant={agent.serverCount > 0 ? "secondary" : "outline"}>
                      {serverLabel}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between rounded-md border border-[var(--outline-variant)] px-3 py-2">
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
                  <div className="space-y-3 rounded-md border border-[var(--outline-variant)] px-3 py-3">
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

      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-1 py-6">
        <div className="flex-1 space-y-5 pb-6">
          {messages.length === 0 ? (
            <div className="flex min-h-80 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--outline-variant)] text-center">
              <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
                <Bot className="size-5" />
              </div>
              <div className="text-sm font-medium">Start a conversation</div>
            </div>
          ) : (
            messages.map((message) => {
              const text = messageText(message.parts);
              return (
                <div
                  className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}
                  key={message.id}
                >
                  <div
                    className={cn(
                      "max-w-[88%] overflow-hidden rounded-lg border px-4 py-3 text-sm leading-6",
                      message.role === "user"
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-[var(--outline-variant)] bg-white"
                    )}
                  >
                    <MessageMarkdown role={message.role} text={text} />
                  </div>
                </div>
              );
            })
          )}
          {status === "submitted" ? (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-lg border border-[var(--outline-variant)] bg-white px-3 py-2 text-sm text-[var(--on-surface-variant)]">
                <Loader2 className="size-4 animate-spin" />
                Thinking
              </div>
            </div>
          ) : null}
        </div>

        {error ? (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error.message}
          </div>
        ) : null}
      </div>

      <div className="sticky bottom-0 border-t border-[var(--outline-variant)] bg-[var(--background)]/95 py-3 backdrop-blur">
        <form
          className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-lg border border-[var(--outline-variant)] bg-white p-2 shadow-[var(--shadow-card)]"
          onSubmit={submitMessage}
        >
          <textarea
            className="max-h-40 min-h-12 flex-1 resize-none rounded-md border-0 bg-transparent px-2 py-2 text-sm outline-none"
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
            <Button aria-label="Stop response" onClick={stop} size="icon" type="button">
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
  );
}
