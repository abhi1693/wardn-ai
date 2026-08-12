"use client";

import { apiStreamFetch, apiUrl } from "@/lib/api/client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import {
  Activity,
  AlertTriangle,
  Bot,
  ClipboardCheck,
  Cpu,
  Database,
  History,
  ImageIcon,
  Info,
  KeyRound,
  ListTree,
  Loader2,
  Network,
  PanelRight,
  Palette,
  PencilLine,
  RotateCcw,
  Send,
  ServerCrash,
  ShieldAlert,
  ShieldCheck,
  Smile,
  Square,
  TimerOff,
  UserRound,
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

import { Badge } from "@/components/atoms/badge";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { DeferredRender } from "@/components/molecules/deferred-render";
import { Button } from "@/components/atoms/button";
import { Input } from "@/components/atoms/input";
import { Label } from "@/components/atoms/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/atoms/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import type {
  AgentRead,
  ConversationMessageRead,
  OrganizationRead,
  WorkspaceConversationRead,
} from "@/lib/api/generated/model";
import { llmProviderCredentialsListModels } from "@/lib/api/generated/llm-provider-credentials/llm-provider-credentials";
import {
  workspaceAgentsQuickStart,
  workspaceAgentsGetConversation,
  workspaceAgentsDecideToolApproval,
  workspaceAgentsUpdateWorkspaceAssistantModel,
  workspaceAgentsUpdateWorkspaceAssistantPersonality,
} from "@/lib/api/generated/workspace-agents/workspace-agents";
import { formatUserShortDate } from "@/lib/date-time";
import { cn } from "@/lib/utils";

import type { LlmCredentialRead } from "../../llm-credentials/types";
import {
  agentRunIdFromMessage,
  agentAvatarText,
  agentDisplayName,
  agentPersonality,
  agentTheme,
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

type PersonalityEditorProps = {
  agent: AgentRead;
  canManagePersonality: boolean;
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

const promptSuggestions: Array<{
  icon: LucideIcon;
  prompt: string;
  title: string;
}> = [
  {
    icon: ServerCrash,
    prompt: "Why did the latest failing MCP server or tool fail?",
    title: "MCP failures",
  },
  {
    icon: ShieldAlert,
    prompt: "Which agents can access production tools in this workspace?",
    title: "Production access",
  },
  {
    icon: ClipboardCheck,
    prompt: "What approvals are waiting on me?",
    title: "Approvals",
  },
  {
    icon: History,
    prompt: "What changed in this workspace today?",
    title: "Today's changes",
  },
  {
    icon: TimerOff,
    prompt: "Which scheduled tasks are failing repeatedly?",
    title: "Scheduled failures",
  },
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
  if (credential.provider === "anthropic") {
    return "Anthropic";
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

function hasUnresolvedToolActivity(messages: ReturnType<typeof uiMessages>) {
  return messages.some((message) =>
    toolActivities(message.parts).some((activity) =>
      ["requires_confirmation", "running"].includes(activity.data?.status ?? "")
    )
  );
}

function displayDate(value?: string | null) {
  return formatUserShortDate(value, "No activity");
}

function inputValue(value?: string | null) {
  return typeof value === "string" ? value : "";
}

function nullableTrimmed(value: string) {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function IdentityMark({ agent, className }: { agent: AgentRead; className?: string }) {
  const avatarUrl = agent.identity?.avatarUrl?.trim();
  const avatarText = agentAvatarText(agent);
  return (
    <span
      className={cn(
        "flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-card text-primary shadow-[var(--shadow-card)]",
        className
      )}
    >
      {avatarUrl ? (
        <span
          aria-label={agentDisplayName(agent)}
          className="size-full bg-cover bg-center"
          role="img"
          style={{ backgroundImage: `url(${avatarUrl})` }}
        />
      ) : (
        <span className="text-xs font-semibold">{avatarText}</span>
      )}
    </span>
  );
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
  agentsPath,
  approvalsPath,
  connectionsPath,
  credentials,
  observabilityPath,
  runsPath,
  runtimePath,
  scheduledTasksPath,
}: {
  agent: AgentRead;
  agentsPath: string;
  approvalsPath: string;
  connectionsPath: string;
  credentials: LlmCredentialRead[];
  observabilityPath: string;
  runsPath: string;
  runtimePath: string;
  scheduledTasksPath: string;
}) {
  const credential = credentialLabel(credentials, agent.providerCredentialId);
  const serverLabel = `${agent.serverCount} ${pluralize(agent.serverCount, "server")}`;
  const toolLabel = `${agent.toolCount} ${pluralize(agent.toolCount, "tool")}`;
  const modelLabel = agent.modelName || "No model";
  const displayName = agentDisplayName(agent);
  const theme = agentTheme(agent);
  const personality = agentPersonality(agent);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <section className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex items-start gap-3">
          <IdentityMark agent={agent} className="size-10 bg-primary text-primary-foreground" />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-sm font-semibold leading-5">{displayName}</h2>
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
          <div className="text-sm font-semibold">Identity</div>
          <UserRound className="size-4 text-muted-foreground" />
        </div>
        <div className="space-y-3 text-sm">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
              <Smile className="size-4 shrink-0" />
              Name
            </span>
            <span className="truncate text-right text-xs font-medium text-foreground">
              {displayName}
            </span>
          </div>
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
              <Palette className="size-4 shrink-0" />
              Theme
            </span>
            <span className="truncate text-right text-xs font-medium text-foreground">
              {theme || "Not set"}
            </span>
          </div>
          <div className="rounded-md border border-border bg-muted/35 px-3 py-2 text-xs leading-5 text-muted-foreground">
            {personality || "No personality guidance set."}
          </div>
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
            <Link href={agentsPath}>
              <Bot className="size-4" />
              Agents
            </Link>
          </Button>
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
          <Button asChild className="justify-start" size="sm" variant="outline">
            <Link href={approvalsPath}>
              <ClipboardCheck className="size-4" />
              Approvals
            </Link>
          </Button>
          <Button asChild className="justify-start" size="sm" variant="outline">
            <Link href={observabilityPath}>
              <Activity className="size-4" />
              Observability
            </Link>
          </Button>
          <Button asChild className="justify-start" size="sm" variant="outline">
            <Link href={runtimePath}>
              <ServerCrash className="size-4" />
              Runtime
            </Link>
          </Button>
          <Button asChild className="justify-start" size="sm" variant="outline">
            <Link href={scheduledTasksPath}>
              <TimerOff className="size-4" />
              Scheduled tasks
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

function PersonalityEditor({
  agent,
  canManagePersonality,
  onAgentChange,
  organizationId,
  workspaceId,
}: PersonalityEditorProps) {
  const [open, setOpen] = useState(false);
  const [identityName, setIdentityName] = useState(inputValue(agent.identity?.name));
  const [identityTheme, setIdentityTheme] = useState(inputValue(agent.identity?.theme));
  const [identityEmoji, setIdentityEmoji] = useState(inputValue(agent.identity?.emoji));
  const [identityAvatar, setIdentityAvatar] = useState(inputValue(agent.identity?.avatar));
  const [identityAvatarUrl, setIdentityAvatarUrl] = useState(
    inputValue(agent.identity?.avatarUrl)
  );
  const [personality, setPersonality] = useState(inputValue(agent.personality));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const displayName = agentDisplayName(agent);
  const theme = agentTheme(agent);

  function resetFields() {
    setIdentityName(inputValue(agent.identity?.name));
    setIdentityTheme(inputValue(agent.identity?.theme));
    setIdentityEmoji(inputValue(agent.identity?.emoji));
    setIdentityAvatar(inputValue(agent.identity?.avatar));
    setIdentityAvatarUrl(inputValue(agent.identity?.avatarUrl));
    setPersonality(inputValue(agent.personality));
  }

  function updateOpen(nextOpen: boolean) {
    setOpen(nextOpen);
    setError("");
    if (nextOpen) {
      resetFields();
    }
  }

  async function savePersonality() {
    if (isSaving) {
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      const updatedAgent = await workspaceAgentsUpdateWorkspaceAssistantPersonality(
        organizationId,
        workspaceId,
        {
          identity: {
            avatar: nullableTrimmed(identityAvatar),
            avatarUrl: nullableTrimmed(identityAvatarUrl),
            emoji: nullableTrimmed(identityEmoji),
            name: nullableTrimmed(identityName),
            theme: nullableTrimmed(identityTheme),
          },
          personality: nullableTrimmed(personality),
        }
      );
      onAgentChange(updatedAgent);
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Personality could not be saved.");
    } finally {
      setIsSaving(false);
    }
  }

  if (!canManagePersonality) {
    return (
      <Badge className="h-8 gap-1.5 px-2.5" variant="outline">
        <UserRound className="size-3.5" />
        <span className="max-w-40 truncate">{displayName}</span>
      </Badge>
    );
  }

  return (
    <Dialog onOpenChange={updateOpen} open={open}>
      <DialogTrigger asChild>
        <Button size="sm" type="button" variant="outline">
          <UserRound className="size-4" />
          <span className="max-w-40 truncate">{displayName}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Agent personality</DialogTitle>
          <DialogDescription>
            Set the identity and persona used in chat responses.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="agent-identity-name">Name</Label>
              <Input
                id="agent-identity-name"
                maxLength={50}
                onChange={(event) => setIdentityName(event.target.value)}
                placeholder={agent.name}
                value={identityName}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-identity-theme">Theme</Label>
              <Input
                id="agent-identity-theme"
                maxLength={120}
                onChange={(event) => setIdentityTheme(event.target.value)}
                placeholder="evidence-first operator"
                value={identityTheme}
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="agent-identity-emoji">Emoji or marker</Label>
              <Input
                id="agent-identity-emoji"
                maxLength={32}
                onChange={(event) => setIdentityEmoji(event.target.value)}
                placeholder="W"
                value={identityEmoji}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-identity-avatar">Avatar</Label>
              <Input
                id="agent-identity-avatar"
                maxLength={512}
                onChange={(event) => setIdentityAvatar(event.target.value)}
                placeholder="W"
                value={identityAvatar}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-identity-avatar-url">Avatar URL</Label>
            <div className="flex items-center gap-2">
              <ImageIcon className="size-4 text-muted-foreground" />
              <Input
                id="agent-identity-avatar-url"
                maxLength={1024}
                onChange={(event) => setIdentityAvatarUrl(event.target.value)}
                placeholder="https://example.com/avatar.png"
                value={identityAvatarUrl}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-personality">Personality</Label>
            <textarea
              className="min-h-36 w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm leading-6 outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/15 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60"
              id="agent-personality"
              maxLength={4000}
              onChange={(event) => setPersonality(event.target.value)}
              placeholder="Be concise, practical, and clear about what you are checking."
              value={personality}
            />
            <div className="flex justify-between gap-3 text-xs text-muted-foreground">
              <span>{theme || "No theme set"}</span>
              <span>{personality.length}/4000</span>
            </div>
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
            <Button disabled={isSaving} onClick={savePersonality} type="button">
              {isSaving ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <PencilLine className="size-4" />
              )}
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
  const hasPendingConversationUpdate = useMemo(
    () => hasUnresolvedToolActivity(messages),
    [messages]
  );
  const isComposerDisabled = isStartingNewChat;
  const transcriptViewportRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const workspaceBasePath = `/org/${organization.id}/workspace/${workspaceId}`;
  const agentsPath = `${workspaceBasePath}/agents`;
  const approvalsPath = `${workspaceBasePath}/agents/${currentAgent.id}`;
  const runsPath = `${workspaceBasePath}/agent-runs`;
  const connectionsPath = `${workspaceBasePath}/install`;
  const observabilityPath = `${workspaceBasePath}/observability`;
  const runtimePath = `${workspaceBasePath}/runtime`;
  const scheduledTasksPath = `${workspaceBasePath}/scheduled-tasks`;
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

  async function submitPromptText(text: string) {
    if (!text || isRunning || isStartingNewChat) {
      return;
    }
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

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning || isStartingNewChat) {
      return;
    }
    setInput("");
    await submitPromptText(text);
  }

  async function resubmitPrompt(text: string) {
    await submitPromptText(text.trim());
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

  useEffect(() => {
    if (!conversation?.id || isRunning || !hasPendingConversationUpdate) {
      return;
    }
    const conversationId = conversation.id;
    const abortController = new AbortController();
    let timeoutId: number | undefined;

    async function refreshConversation() {
      try {
        const data = await workspaceAgentsGetConversation(
          organization.id,
          workspaceId,
          conversationId,
          { signal: abortController.signal }
        );
        const nextMessages = uiMessages(data.messages);
        setMessages((currentMessages) => {
          if (JSON.stringify(currentMessages) === JSON.stringify(nextMessages)) {
            return currentMessages;
          }
          return nextMessages;
        });
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
      } finally {
        if (!abortController.signal.aborted) {
          timeoutId = window.setTimeout(refreshConversation, 2500);
        }
      }
    }

    timeoutId = window.setTimeout(refreshConversation, 1000);
    return () => {
      abortController.abort();
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [
    conversation?.id,
    hasPendingConversationUpdate,
    isRunning,
    organization.id,
    setMessages,
    workspaceId,
  ]);

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-background text-foreground">
      <div className="absolute right-5 top-4 z-10 flex shrink-0 items-center gap-2">
        <PersonalityEditor
          agent={currentAgent}
          canManagePersonality={canManageModel}
          onAgentChange={setCurrentAgent}
          organizationId={organization.id}
          workspaceId={workspaceId}
        />
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
        <Button asChild size="sm" variant="outline">
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
              <DialogTitle>{agentDisplayName(currentAgent)}</DialogTitle>
              <DialogDescription>Workspace chat context</DialogDescription>
            </DialogHeader>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <ContextPanel
                agent={currentAgent}
                agentsPath={agentsPath}
                approvalsPath={approvalsPath}
                connectionsPath={connectionsPath}
                credentials={credentials}
                observabilityPath={observabilityPath}
                runsPath={runsPath}
                runtimePath={runtimePath}
                scheduledTasksPath={scheduledTasksPath}
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
              <IdentityMark agent={currentAgent} className="mb-5 size-11" />
              <h2 className="text-2xl font-semibold leading-8 text-foreground">
                Ask {agentDisplayName(currentAgent)} about this workspace
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
                {agentTheme(currentAgent) || currentAgent.name} is using{" "}
                {currentAgent.modelName || "no selected model"} with {serverLabel} and {toolLabel}{" "}
                available.
              </p>
              <div className="mt-6 grid w-full max-w-3xl gap-2 sm:grid-cols-2">
                {promptSuggestions.map((suggestion) => {
                  const SuggestionIcon = suggestion.icon;
                  return (
                    <button
                      className="flex min-h-12 items-center gap-3 rounded-md border border-border bg-card px-3 py-2 text-left text-sm leading-5 shadow-[var(--shadow-card)] transition-colors hover:border-ring/40 hover:bg-muted/35"
                      key={suggestion.prompt}
                      onClick={() => setSuggestion(suggestion.prompt)}
                      type="button"
                    >
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted/50 text-muted-foreground">
                        <SuggestionIcon className="size-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block font-medium text-foreground">
                          {suggestion.title}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {suggestion.prompt}
                        </span>
                      </span>
                    </button>
                  );
                })}
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
                <DeferredRender asChild estimatedHeight={140} key={message.id}>
                  <article
                    className={cn("group flex", isUser ? "justify-end" : "justify-start")}
                  >
                  <div
                    className={cn(
                      "flex max-w-[min(100%,820px)] gap-3",
                      isUser ? "flex-row-reverse" : "w-full"
                    )}
                  >
                    <MessageAvatar agent={currentAgent} role={message.role} />
                    <div className={cn("min-w-0", isUser ? "max-w-[720px]" : "flex-1")}>
                      <div
                        className={cn(
                          "mb-1.5 flex items-center gap-2 text-xs font-medium text-muted-foreground",
                          isUser && "justify-end"
                        )}
                      >
                        <MessageLabel agent={currentAgent} role={message.role} />
                        {isUser && text ? (
                          <button
                            aria-label="Resubmit prompt"
                            className="inline-flex size-6 items-center justify-center rounded-md border border-border bg-card text-muted-foreground opacity-0 shadow-[var(--shadow-card)] transition hover:bg-muted hover:text-foreground focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-40"
                            disabled={isRunning || isStartingNewChat}
                            onClick={() => void resubmitPrompt(text)}
                            title="Resubmit prompt"
                            type="button"
                          >
                            <RotateCcw className="size-3.5" />
                          </button>
                        ) : null}
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
                </DeferredRender>
              );
            })
          )}

          {status === "submitted" ? (
            <div aria-live="polite" className="flex items-start gap-3" role="status">
              <MessageAvatar agent={currentAgent} role="assistant" />
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
