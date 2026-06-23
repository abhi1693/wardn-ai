"use client";

import { useChat } from "@ai-sdk/react";
import { TextStreamChatTransport } from "ai";
import { Bot, Loader2, Send, Square } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AgentRead, OrganizationRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

type AgentChatClientProps = {
  agent: AgentRead;
  organization: OrganizationRead;
};

function messageText(parts: Array<{ type: string; text?: string }>) {
  return parts
    .filter((part) => part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}

export function AgentChatClient({ agent, organization }: AgentChatClientProps) {
  const [input, setInput] = useState("");
  const transport = useMemo(
    () =>
      new TextStreamChatTransport({
        api: `/api/organizations/${organization.id}/agents/${agent.id}/chat`,
      }),
    [agent.id, organization.id]
  );
  const { error, messages, sendMessage, status, stop } = useChat({ transport });
  const isRunning = status === "submitted" || status === "streaming";

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
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="min-h-[calc(100vh-160px)]">
        <CardHeader className="border-b border-[var(--outline-variant)]">
          <CardTitle>{agent.name}</CardTitle>
          <CardDescription>
            {agent.modelName || "No model selected"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex min-h-[calc(100vh-270px)] flex-col gap-4 p-4">
          <div className="flex-1 space-y-4 overflow-y-auto">
            {messages.length === 0 ? (
              <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--outline-variant)] text-center">
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
                    className={cn(
                      "flex",
                      message.role === "user" ? "justify-end" : "justify-start"
                    )}
                    key={message.id}
                  >
                    <div
                      className={cn(
                        "max-w-[78%] whitespace-pre-wrap rounded-lg border px-3 py-2 text-sm leading-6",
                        message.role === "user"
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-[var(--outline-variant)] bg-white"
                      )}
                    >
                      {text}
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
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error.message}
            </div>
          ) : null}

          <form className="flex gap-2" onSubmit={submitMessage}>
            <textarea
              className="min-h-12 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm"
              disabled={isRunning}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Message this agent"
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
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
          <div className="flex items-center justify-between gap-3">
            <span className="text-[var(--on-surface-variant)]">Model</span>
            <span className="font-mono">{agent.modelName || "none"}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-[var(--on-surface-variant)]">Tools</span>
            <span>{agent.toolCount}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
