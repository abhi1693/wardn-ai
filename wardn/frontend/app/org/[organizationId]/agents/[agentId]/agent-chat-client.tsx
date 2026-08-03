"use client";

import { apiStreamFetch, apiUrl } from "@/lib/api/client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import {
  AlertTriangle,
  Bot,
  Cpu,
  Database,
  Info,
  KeyRound,
  ListTree,
  Loader2,
  Network,
  PanelRight,
  Send,
  ShieldCheck,
  Square,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type FormEvent,
  type RefObject,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  AgentRead,
  ConversationMessageRead,
  OrganizationRead,
  WorkspaceConversationRead,
} from "@/lib/api/generated/model";
import { llmProviderCredentialsListModels } from "@/lib/api/generated/llm-provider-credentials/llm-provider-credentials";
import {
  workspaceAgentsQuickStart,
  workspaceAgentsDecideToolApproval,
  workspaceAgentsUpdateWorkspaceAssistantModel,
} from "@/lib/api/generated/workspace-agents/workspace-agents";
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
  reasoningSummaries,
  ToolActivity,
  toolActivities,
  uiMessages,
  type MessagePart,
  type ToolActivityData,
  type ToolActivityPart,
} from "./agent-chat-messages";

type AgentChatClientProps = {
  agent: AgentRead;
  canManageModel?: boolean;
  conversation?: WorkspaceConversationRead | null;
  credentials: LlmCredentialRead[];
  initialMessages?: ConversationMessageRead[];
  organization: OrganizationRead;
  workspaceId: string;
};

type ChatStatProps = {
  detail: string;
  icon: LucideIcon;
  label: string;
  tone?: "danger" | "info" | "neutral" | "success" | "warning";
  value: string;
};

type ModelSwitcherProps = {
  agent: AgentRead;
  canManageModel: boolean;
  credentials: LlmCredentialRead[];
  onAgentChange: (agent: AgentRead) => void;
  organizationId: string;
  workspaceId: string;
};

type ProviderModel = {
  id: string;
  name: string;
};

type ChatComposerProps = {
  agent: AgentRead;
  input: string;
  isDisabled?: boolean;
  isRunning: boolean;
  onInputChange: (value: string) => void;
  onStop: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  serverLabel: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  toolLabel: string;
};

const toneClassNames: Record<NonNullable<ChatStatProps["tone"]>, string> = {
  danger: "border-red-200 bg-red-50 text-red-700",
  info: "border-sky-200 bg-sky-50 text-sky-700",
  neutral: "border-border bg-muted text-muted-foreground",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
};

const promptSuggestions = [
  "Summarize recent workspace activity.",
  "Check which MCP tools are available.",
  "Review the latest failed agent runs.",
];

function pluralize(value: number, singular: string, plural = `${singular}s`) {
  return value === 1 ? singular : plural;
}

function compactCount(value: number) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
    notation: "compact",
  }).format(value);
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

function credentialName(credential: LlmCredentialRead) {
  return `${credential.name} (${providerLabel(credential)})`;
}

function credentialAvailableForWorkspace(
  credential: LlmCredentialRead,
  workspaceId: string
) {
  if (credential.status !== "active") {
    return false;
  }
  if (credential.visibility !== "workspace") {
    return true;
  }
  return credential.workspaceId === workspaceId;
}

function chatCommandName(value: string) {
  const trimmed = value.trim();
  if (!trimmed.startsWith("/")) {
    return "";
  }
  return trimmed.split(/\s+/, 1)[0].slice(1).toLowerCase();
}

function displayDate(value?: string | null) {
  if (!value) {
    return "No activity";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No activity";
  }
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

function ChatStat({
  detail,
  icon: Icon,
  label,
  tone = "neutral",
  value,
}: ChatStatProps) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-3 shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-md border",
            toneClassNames[tone]
          )}
        >
          <Icon className="size-3.5" />
        </span>
      </div>
      <div className="mt-3 text-xl font-semibold leading-7 text-foreground">{value}</div>
      <div className="mt-1 truncate text-xs text-muted-foreground">{detail}</div>
    </div>
  );
}

function StatusBadge({ agent }: { agent: AgentRead }) {
  return (
    <Badge variant={agent.isActive ? "success" : "secondary"}>
      {agent.isActive ? "Active" : "Inactive"}
    </Badge>
  );
}

function ContextPanel({
  agent,
  connectionsPath,
  credentials,
  runsPath,
}: {
  agent: AgentRead;
  connectionsPath: string;
  credentials: LlmCredentialRead[];
  runsPath: string;
}) {
  const credential = credentialLabel(credentials, agent.providerCredentialId);
  const serverLabel = `${agent.serverCount} ${pluralize(agent.serverCount, "server")}`;
  const toolLabel = `${agent.toolCount} ${pluralize(agent.toolCount, "tool")}`;
  const modelLabel = agent.modelName || "No model";

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <section className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Bot className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-sm font-semibold leading-5">{agent.name}</h2>
              <StatusBadge agent={agent} />
            </div>
            <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted-foreground">
              {agent.description || "Workspace assistant"}
            </p>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <ChatStat
            detail="Bound servers"
            icon={Network}
            label="Connections"
            tone={agent.serverCount > 0 ? "success" : "warning"}
            value={compactCount(agent.serverCount)}
          />
          <ChatStat
            detail="Callable tools"
            icon={Wrench}
            label="Tools"
            tone={agent.toolCount > 0 ? "success" : "neutral"}
            value={compactCount(agent.toolCount)}
          />
        </div>
      </section>

      <section className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-sm font-semibold">Runtime context</div>
          <Cpu className="size-4 text-muted-foreground" />
        </div>
        <div className="space-y-3 text-sm">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
              <Database className="size-4 shrink-0" />
              Model
            </span>
            <span className="truncate font-mono text-xs text-foreground">{modelLabel}</span>
          </div>
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
              <KeyRound className="size-4 shrink-0" />
              Credential
            </span>
            <span className="truncate text-right text-xs font-medium text-foreground">
              {credential}
            </span>
          </div>
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
              <ShieldCheck className="size-4 shrink-0" />
              Scope
            </span>
            <Badge variant="outline">{agent.scope}</Badge>
          </div>
        </div>
      </section>

      <section className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="mb-3 text-sm font-semibold">Workspace links</div>
        <div className="grid gap-2">
          <Button asChild className="justify-start" size="sm" variant="outline">
            <Link href={runsPath}>
              <ListTree className="size-4" />
              Agent runs
            </Link>
          </Button>
          <Button asChild className="justify-start" size="sm" variant="outline">
            <Link href={connectionsPath}>
              <Network className="size-4" />
              Connections
            </Link>
          </Button>
        </div>
      </section>

      <section className="mt-auto rounded-md border border-border bg-muted/40 p-4">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Info className="size-4" />
          Conversation state
        </div>
        <div className="mt-2 text-xs leading-5 text-muted-foreground">
          {serverLabel}, {toolLabel}, updated {displayDate(agent.updatedAt)}.
        </div>
      </section>
    </div>
  );
}

function ModelSwitcher({
  agent,
  canManageModel,
  credentials,
  onAgentChange,
  organizationId,
  workspaceId,
}: ModelSwitcherProps) {
  const availableCredentials = useMemo(
    () =>
      credentials.filter((credential) =>
        credentialAvailableForWorkspace(credential, workspaceId)
      ),
    [credentials, workspaceId]
  );
  const currentCredentialId =
    agent.providerCredentialId &&
    availableCredentials.some((entry) => entry.id === agent.providerCredentialId)
      ? agent.providerCredentialId
      : availableCredentials[0]?.id ?? "";
  const [open, setOpen] = useState(false);
  const [credentialId, setCredentialId] = useState(currentCredentialId);
  const [modelName, setModelName] = useState(agent.modelName ?? "");
  const [modelOptions, setModelOptions] = useState<ProviderModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");

  function updateOpen(nextOpen: boolean) {
    setOpen(nextOpen);
    if (nextOpen) {
      setCredentialId(currentCredentialId);
      setModelName(agent.modelName ?? "");
    }
    setModelOptions([]);
    setError("");
  }

  useEffect(() => {
    if (!open || !credentialId) {
      return;
    }
    const abortController = new AbortController();
    const preferredModel = credentialId === currentCredentialId ? agent.modelName ?? "" : "";

    async function loadModels() {
      setIsLoadingModels(true);
      setError("");
      try {
        const data = await llmProviderCredentialsListModels(organizationId, credentialId, {
          signal: abortController.signal,
        });
        const models = Array.isArray((data as { models?: unknown }).models)
          ? ((data as { models: ProviderModel[] }).models ?? [])
          : [];
        setModelOptions(models);
        if (preferredModel && models.some((model) => model.id === preferredModel)) {
          setModelName(preferredModel);
        } else {
          setModelName(models[0]?.id ?? "");
        }
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setModelOptions([]);
        setError(caught instanceof Error ? caught.message : "Models could not be loaded.");
      } finally {
        if (!abortController.signal.aborted) {
          setIsLoadingModels(false);
        }
      }
    }

    void loadModels();
    return () => abortController.abort();
  }, [agent.modelName, credentialId, currentCredentialId, open, organizationId]);

  async function saveModel() {
    if (!credentialId || !modelName || isSaving || isLoadingModels) {
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      const updatedAgent = await workspaceAgentsUpdateWorkspaceAssistantModel(
        organizationId,
        workspaceId,
        {
          providerCredentialId: credentialId,
          modelName,
        }
      );
      onAgentChange(updatedAgent);
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Model could not be changed.");
    } finally {
      setIsSaving(false);
    }
  }

  if (!canManageModel) {
    return (
      <Badge className="h-8 gap-1.5 px-2.5 font-mono" variant="outline">
        <Cpu className="size-3.5" />
        {agent.modelName || "No model"}
      </Badge>
    );
  }

  return (
    <Dialog onOpenChange={updateOpen} open={open}>
      <DialogTrigger asChild>
        <Button
          disabled={availableCredentials.length === 0}
          size="sm"
          type="button"
          variant="outline"
        >
          <Cpu className="size-4" />
          <span className="max-w-48 truncate font-mono text-xs">
            {agent.modelName || "Select model"}
          </span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Chat model</DialogTitle>
          <DialogDescription>
            Select the LLM credential and model used by this workspace assistant.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Credential</div>
            <Select
              disabled={availableCredentials.length === 0 || isSaving}
              onValueChange={(value) => {
                setCredentialId(value);
                setModelName("");
              }}
              value={credentialId}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select credential" />
              </SelectTrigger>
              <SelectContent>
                {availableCredentials.map((credential) => (
                  <SelectItem key={credential.id} value={credential.id}>
                    {credentialName(credential)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Model</div>
            <Select
              disabled={!credentialId || isLoadingModels || isSaving || Boolean(error)}
              onValueChange={setModelName}
              value={modelName}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    isLoadingModels
                      ? "Loading models"
                      : credentialId
                        ? "Select model"
                        : "Select credential"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.name || model.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

          <div className="flex justify-end gap-2">
            <Button
              disabled={isSaving}
              onClick={() => setOpen(false)}
              type="button"
              variant="outline"
            >
              Cancel
            </Button>
            <Button
              disabled={!credentialId || !modelName || isLoadingModels || isSaving}
              onClick={saveModel}
              type="button"
            >
              {isSaving ? <Loader2 className="size-4 animate-spin" /> : null}
              Save
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ChatComposer({
  agent,
  input,
  isDisabled = false,
  isRunning,
  onInputChange,
  onStop,
  onSubmit,
  serverLabel,
  textareaRef,
  toolLabel,
}: ChatComposerProps) {
  return (
    <form
      className="w-full overflow-hidden rounded-md border border-border bg-card shadow-[var(--shadow-float)] transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-sky-100"
      onSubmit={onSubmit}
    >
      <div className="flex items-end gap-2 p-2">
        <textarea
          className="max-h-44 min-h-14 flex-1 resize-none rounded-md border-0 bg-transparent px-3 py-2 text-sm leading-6 outline-none placeholder:text-muted-foreground"
          disabled={isRunning || isDisabled}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && isRunning) {
              event.preventDefault();
              onStop();
            }
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Message this workspace"
          ref={textareaRef}
          value={input}
        />
        {isRunning ? (
          <Button
            aria-label="Stop response"
            onClick={onStop}
            size="icon"
            type="button"
            variant="secondary"
          >
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            aria-label="Send message"
            disabled={!input.trim() || isDisabled}
            size="icon"
            type="submit"
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-border bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
        <Badge className="font-mono" variant="outline">
          {agent.modelName || "No model"}
        </Badge>
        <Badge variant={agent.serverCount > 0 ? "secondary" : "outline"}>{serverLabel}</Badge>
        <Badge variant={agent.toolCount > 0 ? "secondary" : "outline"}>{toolLabel}</Badge>
      </div>
    </form>
  );
}

export function AgentChatClient({
  agent,
  canManageModel = false,
  conversation = null,
  credentials,
  initialMessages = [],
  organization,
  workspaceId,
}: AgentChatClientProps) {
  const router = useRouter();
  const [currentAgent, setCurrentAgent] = useState(agent);
  const [input, setInput] = useState("");
  const [approvalDecisions, setApprovalDecisions] = useState<Record<string, string>>({});
  const [commandError, setCommandError] = useState("");
  const [isStartingNewChat, setIsStartingNewChat] = useState(false);
  const [lastSubmittedText, setLastSubmittedText] = useState("");
  const chatApi = `/api/v1/organizations/${organization.id}/workspaces/${workspaceId}/agents/${currentAgent.id}/chat`;
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
  const isComposerDisabled = isStartingNewChat;
  const transcriptViewportRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const workspaceBasePath = `/org/${organization.id}/workspace/${workspaceId}`;
  const runsPath = `${workspaceBasePath}/agent-runs`;
  const connectionsPath = `${workspaceBasePath}/install`;
  const serverLabel = `${currentAgent.serverCount} ${pluralize(
    currentAgent.serverCount,
    "server"
  )}`;
  const toolLabel = `${currentAgent.toolCount} ${pluralize(
    currentAgent.toolCount,
    "tool"
  )}`;
  const conversationTitle = conversation?.title?.trim() || "New conversation";
  const messageCount = messages.filter((message) => message.role !== "system").length;
  const isEmptyConversation = messages.length === 0 && !error && status !== "submitted";

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning || isStartingNewChat) {
      return;
    }
    setInput("");
    setCommandError("");
    if (chatCommandName(text) === "new") {
      setIsStartingNewChat(true);
      try {
        const nextConversation = await workspaceAgentsQuickStart(
          organization.id,
          workspaceId
        );
        router.push(
          `/org/${encodeURIComponent(organization.id)}/workspace/${encodeURIComponent(
            workspaceId
          )}/chat/${encodeURIComponent(nextConversation.conversation.id)}`
        );
      } catch (caught) {
        setCommandError(caught instanceof Error ? caught.message : "New chat could not be started.");
      } finally {
        setIsStartingNewChat(false);
      }
      return;
    }
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
        currentAgent.id,
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

  function setSuggestion(value: string) {
    setInput(value);
    window.requestAnimationFrame(() => textareaRef.current?.focus());
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

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 176)}px`;
  }, [input]);

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-background text-foreground">
      <div className="absolute right-5 top-4 z-10 flex shrink-0 items-center gap-2">
        <ModelSwitcher
          agent={currentAgent}
          canManageModel={canManageModel}
          credentials={credentials}
          onAgentChange={setCurrentAgent}
          organizationId={organization.id}
          workspaceId={workspaceId}
        />
        {!isEmptyConversation ? (
          <div className="mr-1 hidden max-w-[360px] items-center gap-2 rounded-md border border-border bg-card/85 px-3 py-1.5 text-xs text-muted-foreground shadow-[var(--shadow-card)] backdrop-blur lg:flex">
            <span className="truncate font-medium text-foreground">{conversationTitle}</span>
            <span className="text-border">/</span>
            <span>{messageCount} {pluralize(messageCount, "message")}</span>
          </div>
        ) : null}
        <Button asChild className="max-md:hidden" size="sm" variant="outline">
          <Link href={runsPath}>
            <ListTree className="size-4" />
            Runs
          </Link>
        </Button>
        <Dialog>
          <DialogTrigger asChild>
            <Button size="sm" type="button" variant="outline">
              <PanelRight className="size-4" />
              Context
            </Button>
          </DialogTrigger>
          <DialogContent className="top-0 right-0 left-auto flex h-dvh max-w-md translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-y-0 border-r-0 p-0 sm:w-[420px]">
            <DialogHeader className="border-b border-border px-5 py-4">
              <DialogTitle>{currentAgent.name}</DialogTitle>
              <DialogDescription>Workspace chat context</DialogDescription>
            </DialogHeader>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <ContextPanel
                agent={currentAgent}
                connectionsPath={connectionsPath}
                credentials={credentials}
                runsPath={runsPath}
              />
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div
        className="min-h-0 flex-1 overflow-y-auto bg-[linear-gradient(180deg,var(--surface-bright)_0%,var(--background)_54%,var(--surface)_100%)]"
        ref={transcriptViewportRef}
      >
        <div
          className={cn(
            "mx-auto flex w-full max-w-4xl flex-col px-5 md:px-8",
            isEmptyConversation ? "min-h-full justify-center py-12" : "gap-6 py-8 pt-20"
          )}
        >
          {isEmptyConversation ? (
            <div className="mx-auto flex w-full max-w-3xl flex-col items-center text-center">
              <div className="mb-5 flex size-11 items-center justify-center rounded-md border border-border bg-card text-primary shadow-[var(--shadow-card)]">
                <Bot className="size-5" />
              </div>
              <h2 className="text-2xl font-semibold leading-8 text-foreground">
                How can I help with this workspace?
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
                {currentAgent.name} is using {currentAgent.modelName || "no selected model"} with{" "}
                {serverLabel} and {toolLabel} available.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {promptSuggestions.map((suggestion) => (
                  <button
                    className="min-h-8 rounded-full border border-border bg-card px-3 py-1.5 text-sm leading-5 shadow-[var(--shadow-card)] transition-colors hover:border-ring/40 hover:bg-muted/35"
                    key={suggestion}
                    onClick={() => setSuggestion(suggestion)}
                    type="button"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
              <div className="mt-4 w-full max-w-2xl">
                <ChatComposer
                  agent={currentAgent}
                  input={input}
                  isDisabled={isComposerDisabled}
                  isRunning={isRunning}
                  onInputChange={setInput}
                  onStop={stop}
                  onSubmit={submitMessage}
                  serverLabel={serverLabel}
                  textareaRef={textareaRef}
                  toolLabel={toolLabel}
                />
              </div>
            </div>
          ) : (
            messages.map((message) => {
              const text = messageText(message.parts);
              const activities = toolActivities(message.parts);
              const summaries = reasoningSummaries(message.parts);
              const isUser = message.role === "user";
              if (!text && activities.length === 0 && summaries.length === 0) {
                return null;
              }
              const agentRunId = agentRunIdFromMessage(message);
              const traceHref = agentRunId
                ? `${workspaceBasePath}/agent-runs/${agentRunId}`
                : undefined;
              return (
                <article
                  className={cn("group flex", isUser ? "justify-end" : "justify-start")}
                  key={message.id}
                >
                  <div
                    className={cn(
                      "flex max-w-[min(100%,820px)] gap-3",
                      isUser ? "flex-row-reverse" : "w-full"
                    )}
                  >
                    <MessageAvatar role={message.role} />
                    <div className={cn("min-w-0", isUser ? "max-w-[720px]" : "flex-1")}>
                      <div
                        className={cn(
                          "mb-1.5 flex items-center gap-2 text-xs font-medium text-muted-foreground",
                          isUser && "justify-end"
                        )}
                      >
                        <MessageLabel role={message.role} />
                        {!isUser && traceHref ? (
                          <Link
                            className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                            href={traceHref}
                          >
                            <ListTree className="size-3" />
                            Trace
                          </Link>
                        ) : null}
                      </div>
                      <div
                        className={cn(
                          "overflow-hidden rounded-md border px-4 py-3 text-sm leading-6 shadow-[var(--shadow-card)]",
                          isUser
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-card"
                        )}
                      >
                        {!isUser ? (
                          <ToolActivity
                            activities={activities}
                            approvalDecisions={approvalDecisions}
                            onDecideApproval={decideToolApproval}
                            summaries={summaries}
                          />
                        ) : null}
                        {text ? <MessageMarkdown role={message.role} text={text} /> : null}
                      </div>
                    </div>
                  </div>
                </article>
              );
            })
          )}

          {status === "submitted" ? (
            <div aria-live="polite" className="flex items-start gap-3" role="status">
              <MessageAvatar role="assistant" />
              <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground shadow-[var(--shadow-card)]">
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
          {commandError ? (
            <AsyncFeedback variant="error">{commandError}</AsyncFeedback>
          ) : null}
        </div>
      </div>

      {!isEmptyConversation ? (
        <div className="shrink-0 border-t border-border bg-card/95 px-4 py-3 backdrop-blur md:px-6">
          {!currentAgent.isActive ? (
            <div className="mx-auto mb-3 flex max-w-4xl items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <AlertTriangle className="size-4 shrink-0" />
              This agent is inactive.
            </div>
          ) : null}
          <div className="mx-auto w-full max-w-4xl">
            <ChatComposer
              agent={currentAgent}
              input={input}
              isDisabled={isComposerDisabled}
              isRunning={isRunning}
              onInputChange={setInput}
              onStop={stop}
              onSubmit={submitMessage}
              serverLabel={serverLabel}
              textareaRef={textareaRef}
              toolLabel={toolLabel}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
