"use client";

import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  KeyRound,
  Link2,
  Loader2,
  MessageCircle,
  QrCode,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Smartphone,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { StatusDot } from "@/components/atoms/status-dot";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  ChatProviderConnectionCreate,
  ChatProviderConnectionRead,
  ChatProviderPairingStatusResponse,
  ChatProviderWorkspaceMemberRead,
  SecretStoreRead,
} from "@/lib/api/generated/model";
import {
  workspaceChatProvidersCreate,
  workspaceChatProvidersPairingStatus,
  workspaceChatProvidersResetPairingQr,
  workspaceChatProvidersUpdate,
} from "@/lib/api/generated/workspace-chat-providers/workspace-chat-providers";
import { formatUserDateTime } from "@/lib/date-time";
import { cn } from "@/lib/utils";

type ProviderType = "whatsapp_local" | "telegram" | "slack";

type ChatProviderFormClientProps = {
  basePath: string;
  connection?: ChatProviderConnectionRead;
  defaultWhatsappBridgeBaseUrl: string;
  mode: "create" | "edit";
  organizationId: string;
  secretStores: SecretStoreRead[];
  workspaceId: string;
  workspaceMembers: ChatProviderWorkspaceMemberRead[];
};

const NO_THREAD_VALUE = "__none__";

const providerOptions = [
  {
    value: "whatsapp_local" as const,
    label: "WhatsApp local",
    shortLabel: "WhatsApp",
    icon: Smartphone,
    detail: "Pair a personal WhatsApp linked device.",
  },
  {
    value: "telegram" as const,
    label: "Telegram bot",
    shortLabel: "Telegram",
    icon: Bot,
    detail: "Connect a workspace Telegram bot.",
  },
  {
    value: "slack" as const,
    label: "Slack app",
    shortLabel: "Slack",
    icon: MessageCircle,
    detail: "Connect Slack mentions and direct messages.",
  },
];

function randomSecret() {
  const cryptoValue = globalThis.crypto?.randomUUID?.();
  if (cryptoValue) {
    return `wardn_${cryptoValue.replaceAll("-", "")}`;
  }
  return `wardn_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

function defaultBridgeUserId() {
  return Date.now().toString().slice(-8);
}

function isSlackTeamId(value: string) {
  return /^T[A-Z0-9]+$/.test(value.trim());
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function boolConfigDefault(config: unknown, defaultValue: boolean, ...keys: string[]) {
  const values = record(config);
  for (const key of keys) {
    if (typeof values[key] === "boolean") {
      return values[key] === true;
    }
  }
  return defaultValue;
}

function stringConfig(config: unknown, ...keys: string[]) {
  const values = record(config);
  for (const key of keys) {
    const value = values[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function arrayConfig(config: unknown, ...keys: string[]) {
  const values = record(config);
  for (const key of keys) {
    const value = values[key];
    if (Array.isArray(value)) {
      return value.map((item) => String(item).trim()).filter(Boolean);
    }
  }
  return [];
}

function objectArrayConfig(config: unknown, ...keys: string[]) {
  const values = record(config);
  for (const key of keys) {
    const value = values[key];
    if (Array.isArray(value)) {
      return value.filter((item): item is Record<string, unknown> => {
        return Boolean(item && typeof item === "object" && !Array.isArray(item));
      });
    }
  }
  return [];
}

function stringList(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listText(values: string[]) {
  return Array.from(new Set(values.map((item) => item.trim()).filter(Boolean))).join("\n");
}

function appendListValue(values: string[], value: string) {
  const normalized = value.trim();
  if (!normalized) {
    return values;
  }
  return Array.from(new Set([...values, normalized]));
}

function removeListValue(values: string[], value: string) {
  const normalized = value.trim();
  return values.filter((item) => item.trim() !== normalized);
}

function friendlyIdentityId(value?: string | null) {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) {
    return "";
  }
  const [user] = trimmed.split("@", 1);
  const normalized = user.split(":", 1)[0];
  if (/^\d{8,16}$/.test(normalized)) {
    return `+${normalized}`;
  }
  return normalized || trimmed;
}

function identityLabel(identity: NonNullable<ChatProviderConnectionRead["knownIdentities"]>[number]) {
  return (
    identity.displayName?.trim() ||
    friendlyIdentityId(identity.externalUserId) ||
    friendlyIdentityId(identity.externalThreadId) ||
    "Unknown sender"
  );
}

function linkedThreadLabel(
  identities: NonNullable<ChatProviderConnectionRead["knownIdentities"]>,
  threadId: string
) {
  const identity = identities.find((item) => item.externalThreadId === threadId);
  return identity ? identityLabel(identity) : friendlyIdentityId(threadId) || threadId;
}

function approvalRouteType(route: Record<string, unknown>) {
  return String(route.route_type ?? route.routeType ?? "").trim();
}

function approvalRouteUserId(route: Record<string, unknown>) {
  return String(route.user_id ?? route.userId ?? "").trim();
}

function approvalRouteThreadId(route: Record<string, unknown>) {
  return String(route.external_thread_id ?? route.externalThreadId ?? "").trim();
}

function approvalRoutesConfig(config: unknown) {
  return objectArrayConfig(config, "approval_routes", "approvalRoutes");
}

function workspaceMemberLabel(member: ChatProviderWorkspaceMemberRead) {
  return member.displayName?.trim() || member.email || "Workspace member";
}

function providerOption(provider: string) {
  return providerOptions.find((option) => option.value === provider) ?? providerOptions[0];
}

function displayDate(value?: string | null) {
  return formatUserDateTime(
    value,
    "Never",
    { day: "numeric", hour: "numeric", minute: "2-digit", month: "short" },
    "en-US"
  );
}

function displayHost(value: string) {
  if (!value) {
    return "Not configured";
  }
  try {
    const parsed = new URL(value);
    return parsed.host;
  } catch {
    return value;
  }
}

function defaultProviderName(provider: ProviderType) {
  if (provider === "telegram") {
    return "Workspace Telegram";
  }
  if (provider === "slack") {
    return "Workspace Slack";
  }
  return "Personal WhatsApp";
}

function statusLabel(
  connection: ChatProviderConnectionRead,
  pairing?: ChatProviderPairingStatusResponse
) {
  if (!connection.isActive) {
    return "Paused";
  }
  if (connection.provider !== "whatsapp_local") {
    return "Active";
  }
  if (!pairing) {
    return "Checking";
  }
  if (pairing.status === "connected") {
    return "Connected";
  }
  if (pairing.status === "waiting_for_scan") {
    return "Waiting for scan";
  }
  if (pairing.status === "not_configured") {
    return "Bridge missing";
  }
  if (pairing.status === "error") {
    return "Bridge error";
  }
  if (pairing.status === "needs_pairing") {
    return "Pairing required";
  }
  return "Disconnected";
}

function statusTone(
  connection: ChatProviderConnectionRead,
  pairing?: ChatProviderPairingStatusResponse
) {
  if (!connection.isActive) {
    return "neutral" as const;
  }
  if (connection.provider !== "whatsapp_local") {
    return "success" as const;
  }
  if (pairing?.status === "connected") {
    return "success" as const;
  }
  if (pairing?.status === "error" || pairing?.status === "not_configured") {
    return "danger" as const;
  }
  return "warning" as const;
}

function mergePairingStatus(
  current: ChatProviderPairingStatusResponse | undefined,
  next: ChatProviderPairingStatusResponse,
  options: { preserveQr: boolean }
) {
  const { preserveQr } = options;
  if (next.status === "connected" || next.status === "error" || next.qrPayload || !preserveQr) {
    return next;
  }
  const currentQr = current?.qrPayload ?? "";
  if (!currentQr) {
    return next;
  }
  return {
    ...next,
    qrExpiresAt: current?.qrExpiresAt ?? next.qrExpiresAt,
    qrPayload: currentQr,
  };
}

function initialApprovalThreadMap(
  config: unknown,
  workspaceMembers: ChatProviderWorkspaceMemberRead[]
) {
  const memberIds = new Set(workspaceMembers.map((member) => member.userId));
  const routes = approvalRoutesConfig(config);
  return Object.fromEntries(
    routes
      .filter((route) => approvalRouteType(route) === "workspace_member")
      .map((route) => [approvalRouteUserId(route), approvalRouteThreadId(route)] as const)
      .filter(([userId]) => userId && memberIds.has(userId))
  );
}

export function ChatProviderFormClient({
  basePath,
  connection,
  defaultWhatsappBridgeBaseUrl,
  mode,
  organizationId,
  secretStores,
  workspaceId,
  workspaceMembers,
}: ChatProviderFormClientProps) {
  const router = useRouter();
  const activeSecretStores = secretStores.filter((store) => store.isActive);
  const normalizedDefaultBridgeUrl = defaultWhatsappBridgeBaseUrl.trim();
  const initialConfig = record(connection?.config);
  const [provider, setProvider] = useState<ProviderType>(
    (connection?.provider as ProviderType | undefined) ?? "whatsapp_local"
  );
  const [name, setName] = useState(connection?.name ?? "Personal WhatsApp");
  const [isActive, setIsActive] = useState(connection?.isActive ?? true);
  const [bridgeBaseUrl, setBridgeBaseUrl] = useState(
    stringConfig(initialConfig, "bridge_base_url", "bridgeBaseUrl") || normalizedDefaultBridgeUrl
  );
  const [bridgeUserId, setBridgeUserId] = useState(
    stringConfig(initialConfig, "bridge_user_id", "bridgeUserId", "account_name", "accountName") ||
      connection?.externalId ||
      defaultBridgeUserId()
  );
  const [secretStoreId, setSecretStoreId] = useState(activeSecretStores[0]?.id ?? "");
  const [webhookSecret, setWebhookSecret] = useState(randomSecret);
  const [botToken, setBotToken] = useState("");
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackAppId, setSlackAppId] = useState(stringConfig(initialConfig, "app_id", "appId"));
  const [slackBotUserId, setSlackBotUserId] = useState(
    stringConfig(initialConfig, "bot_user_id", "botUserId")
  );
  const [allowAllSenders, setAllowAllSenders] = useState(
    boolConfigDefault(initialConfig, true, "allow_all_senders", "allowAllSenders")
  );
  const [allowedSenderIds, setAllowedSenderIds] = useState(
    listText(arrayConfig(initialConfig, "allowed_sender_ids", "allowedSenderIds"))
  );
  const [allowedChatIds, setAllowedChatIds] = useState(
    listText(arrayConfig(initialConfig, "allowed_chat_ids", "allowedChatIds"))
  );
  const [approvalThreadsByUserId, setApprovalThreadsByUserId] = useState<
    Record<string, string>
  >(() => initialApprovalThreadMap(initialConfig, workspaceMembers));
  const [pairingStatus, setPairingStatus] = useState<
    ChatProviderPairingStatusResponse | undefined
  >();
  const [isSaving, setIsSaving] = useState(false);
  const [isPairingBusy, setIsPairingBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const knownIdentities = connection?.knownIdentities ?? [];
  const selectedChatIds = stringList(allowedChatIds);
  const selectedApproverCount = Object.keys(approvalThreadsByUserId).length;
  const missingApprovalLinks = Object.entries(approvalThreadsByUserId)
    .filter(([, threadId]) => !threadId.trim())
    .map(([userId]) => userId);

  const selectedApprovalThreadIds = useMemo(
    () => new Set(Object.values(approvalThreadsByUserId).filter(Boolean)),
    [approvalThreadsByUserId]
  );

  function applyProviderDefaults(nextProvider: ProviderType) {
    if (mode !== "create") {
      return;
    }
    setProvider(nextProvider);
    setName(defaultProviderName(nextProvider));
    if (nextProvider === "whatsapp_local") {
      setBridgeBaseUrl(normalizedDefaultBridgeUrl);
    }
    if (nextProvider === "slack") {
      setBridgeUserId("");
    } else {
      setBridgeUserId(defaultBridgeUserId());
    }
  }

  function setKnownConversationAllowed(threadId: string, checked: boolean) {
    const next = checked
      ? appendListValue(selectedChatIds, threadId)
      : removeListValue(selectedChatIds, threadId);
    setAllowedChatIds(listText(next));
  }

  function setWorkspaceMemberApproval(userId: string, checked: boolean) {
    setApprovalThreadsByUserId((current) => {
      if (!checked) {
        const next = { ...current };
        delete next[userId];
        return next;
      }
      return {
        ...current,
        [userId]: current[userId] ?? "",
      };
    });
  }

  function setWorkspaceMemberThread(userId: string, threadId: string) {
    setApprovalThreadsByUserId((current) => ({
      ...current,
      [userId]: threadId === NO_THREAD_VALUE ? "" : threadId,
    }));
  }

  function providerConfigPayload() {
    const memberLabels = new Map(
      workspaceMembers.map((member) => [member.userId, workspaceMemberLabel(member)])
    );
    const approvalRoutes = Object.entries(approvalThreadsByUserId).map(([userId, threadId]) => ({
      displayName: memberLabels.get(userId) ?? userId,
      externalThreadId: threadId,
      routeType: "workspace_member",
      userId,
    }));
    const common = {
      allowAllSenders: allowAllSenders,
      allowedChatIds: stringList(allowedChatIds),
      allowedSenderIds: stringList(allowedSenderIds),
      approvalRoutes,
      replyOnUnsupportedMessages: boolConfigDefault(
        initialConfig,
        false,
        "reply_on_unsupported_messages",
        "replyOnUnsupportedMessages"
      ),
    };
    if (provider === "whatsapp_local") {
      return {
        ...common,
        accountName: bridgeUserId.trim(),
        bridgeBaseUrl: bridgeBaseUrl.trim(),
        bridgeUserId: bridgeUserId.trim(),
        outboundWebhookUrl: stringConfig(
          initialConfig,
          "outbound_webhook_url",
          "outboundWebhookUrl"
        ),
      };
    }
    if (provider === "slack") {
      return {
        ...common,
        appId: slackAppId.trim(),
        botUserId: slackBotUserId.trim(),
        teamId: bridgeUserId.trim(),
      };
    }
    return common;
  }

  async function refreshPairingStatus(resetQr = false) {
    if (!connection || connection.provider !== "whatsapp_local") {
      return;
    }
    setIsPairingBusy(true);
    setError("");
    try {
      const status = resetQr
        ? await workspaceChatProvidersResetPairingQr(
            organizationId,
            workspaceId,
            connection.id,
            { timeoutMs: 35_000 }
          )
        : await workspaceChatProvidersPairingStatus(
            organizationId,
            workspaceId,
            connection.id,
            { timeoutMs: 15_000 }
          );
      setPairingStatus((current) =>
        mergePairingStatus(current, status, { preserveQr: !resetQr })
      );
      if (status.status === "error") {
        setError(status.message || "WhatsApp bridge status failed.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Pairing status could not be loaded.");
    } finally {
      setIsPairingBusy(false);
    }
  }

  useEffect(() => {
    if (!connection || connection.provider !== "whatsapp_local") {
      return;
    }
    const timeoutId = window.setTimeout(() => {
      void refreshPairingStatus(false);
    }, 0);
    return () => {
      window.clearTimeout(timeoutId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection?.id]);

  useEffect(() => {
    if (
      !connection ||
      connection.provider !== "whatsapp_local" ||
      !pairingStatus?.qrPayload ||
      pairingStatus.status === "connected"
    ) {
      return;
    }
    const activeConnection = connection;
    let ignore = false;
    async function pollPairingStatus() {
      try {
        const status = await workspaceChatProvidersPairingStatus(
          organizationId,
          workspaceId,
          activeConnection.id,
          { timeoutMs: 15_000 }
        );
        if (!ignore) {
          setPairingStatus((current) =>
            mergePairingStatus(current, status, { preserveQr: true })
          );
        }
      } catch {
        // Keep polling; transient bridge/API errors should not dismiss the QR.
      }
    }

    void pollPairingStatus();
    const intervalId = window.setInterval(() => {
      void pollPairingStatus();
    }, 3_000);
    return () => {
      ignore = true;
      window.clearInterval(intervalId);
    };
  }, [
    connection,
    organizationId,
    pairingStatus?.qrPayload,
    pairingStatus?.status,
    workspaceId,
  ]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName || isSaving || missingApprovalLinks.length > 0) {
      return;
    }
    setIsSaving(true);
    setError("");
    setNotice("");
    try {
      if (mode === "create") {
        const secretValues: Record<string, string> = { webhook_secret: webhookSecret.trim() };
        if (provider === "telegram") {
          secretValues.bot_token = botToken.trim();
        } else if (provider === "slack") {
          delete secretValues.webhook_secret;
          secretValues.app_token = slackAppToken.trim();
          secretValues.bot_token = botToken.trim();
        } else {
          secretValues.outbound_secret = webhookSecret.trim();
        }
        const payload: ChatProviderConnectionCreate = {
          config: providerConfigPayload(),
          displayName: normalizedName,
          externalId:
            provider === "slack"
              ? bridgeUserId.trim()
              : bridgeUserId.trim() || defaultBridgeUserId(),
          name: normalizedName,
          provider,
          secretStoreId,
          secretValues,
        };
        const created = await workspaceChatProvidersCreate(organizationId, workspaceId, payload);
        router.push(`${basePath}/${encodeURIComponent(created.id)}/edit`);
        return;
      }
      if (!connection) {
        return;
      }
      await workspaceChatProvidersUpdate(organizationId, workspaceId, connection.id, {
        config: providerConfigPayload(),
        displayName: normalizedName,
        isActive,
        name: normalizedName,
      });
      setNotice("Provider connection updated.");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider connection could not be saved.");
    } finally {
      setIsSaving(false);
    }
  }

  const canSave =
    name.trim().length > 0 &&
    missingApprovalLinks.length === 0 &&
    (mode === "edit" ||
      (secretStoreId.length > 0 &&
        (provider === "slack" || webhookSecret.trim().length > 0) &&
        (provider !== "telegram" || botToken.trim().length > 0) &&
        (provider !== "slack" ||
          (botToken.trim().length > 0 &&
            slackAppToken.trim().length > 0 &&
            isSlackTeamId(bridgeUserId))) &&
        (provider !== "whatsapp_local" || bridgeBaseUrl.trim().length > 0)));

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-card px-6 py-3 max-md:px-4">
        <Button asChild size="sm" type="button" variant="ghost">
          <Link href={basePath}>
            <ArrowLeft className="size-4" />
            Back
          </Link>
        </Button>
        <div className="flex items-center gap-2">
          <Button asChild type="button" variant="outline">
            <Link href={basePath}>Cancel</Link>
          </Button>
          <Button disabled={!canSave || isSaving} type="submit">
            {isSaving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            {mode === "create" ? "Create provider" : "Save changes"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 px-6 pb-6 max-md:px-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-4">
          {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
          {notice ? (
            <AsyncFeedback className="flex items-center gap-2" variant="success">
              <CheckCircle2 className="size-4" />
              {notice}
            </AsyncFeedback>
          ) : null}

          <Card>
            <CardHeader className="border-b border-border">
              <CardTitle className="flex items-center gap-2 text-base">
                <Settings2 className="size-4 text-muted-foreground" />
                Provider
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 p-4">
              {mode === "create" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {providerOptions.map((option) => {
                    const Icon = option.icon;
                    return (
                      <button
                        className={cn(
                          "flex min-h-20 items-start gap-3 rounded-md border bg-card p-3 text-left transition-colors",
                          provider === option.value
                            ? "border-ring ring-2 ring-ring/15"
                            : "border-border hover:border-ring/40"
                        )}
                        key={option.value}
                        onClick={() => applyProviderDefaults(option.value)}
                        type="button"
                      >
                        <div className="flex size-8 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                          <Icon className="size-4" />
                        </div>
                        <span>
                          <span className="block text-sm font-medium text-foreground">
                            {option.shortLabel}
                          </span>
                          <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                            {option.detail}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="chat-provider-name">Name</Label>
                  <Input
                    id="chat-provider-name"
                    maxLength={100}
                    onChange={(event) => setName(event.target.value)}
                    required
                    value={name}
                  />
                </div>
                {mode === "edit" ? (
                  <label className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm sm:mt-7">
                    <input
                      checked={isActive}
                      className="size-4 accent-primary"
                      onChange={(event) => setIsActive(event.target.checked)}
                      type="checkbox"
                    />
                    Active
                  </label>
                ) : provider === "telegram" || provider === "slack" ? (
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-bot-token">Bot token</Label>
                    <Input
                      autoComplete="off"
                      id="chat-provider-bot-token"
                      onChange={(event) => setBotToken(event.target.value)}
                      required
                      type="password"
                      value={botToken}
                    />
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-pairing">Pairing</Label>
                    <Input
                      disabled
                      id="chat-provider-pairing"
                      value={
                        normalizedDefaultBridgeUrl
                          ? `QR via ${displayHost(normalizedDefaultBridgeUrl)}`
                          : "WhatsApp bridge URL required"
                      }
                    />
                  </div>
                )}
              </div>

              {mode === "create" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-secret-store">Secret backend</Label>
                    {activeSecretStores.length > 0 ? (
                      <Select onValueChange={setSecretStoreId} value={secretStoreId}>
                        <SelectTrigger id="chat-provider-secret-store">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {activeSecretStores.map((store) => (
                            <SelectItem key={store.id} value={store.id}>
                              {store.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input disabled value="Connect a secret backend first" />
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-external">
                      {provider === "whatsapp_local"
                        ? "Bridge user ID"
                        : provider === "slack"
                          ? "Slack team ID"
                          : "External ID"}
                    </Label>
                    <Input
                      id="chat-provider-external"
                      maxLength={255}
                      onChange={(event) => setBridgeUserId(event.target.value)}
                      placeholder={provider === "slack" ? "T0123456789" : undefined}
                      required
                      value={bridgeUserId}
                    />
                  </div>
                  {provider === "whatsapp_local" ? (
                    <div className="space-y-2 sm:col-span-2">
                      <Label htmlFor="chat-provider-bridge">WhatsApp gateway URL</Label>
                      <Input
                        id="chat-provider-bridge"
                        maxLength={2048}
                        onChange={(event) => setBridgeBaseUrl(event.target.value)}
                        required
                        value={bridgeBaseUrl}
                      />
                    </div>
                  ) : null}
                  {provider === "slack" ? (
                    <>
                      <div className="space-y-2">
                        <Label htmlFor="chat-provider-slack-app">Slack app ID</Label>
                        <Input
                          id="chat-provider-slack-app"
                          maxLength={255}
                          onChange={(event) => setSlackAppId(event.target.value)}
                          value={slackAppId}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="chat-provider-slack-bot-user">Bot user ID</Label>
                        <Input
                          id="chat-provider-slack-bot-user"
                          maxLength={255}
                          onChange={(event) => setSlackBotUserId(event.target.value)}
                          value={slackBotUserId}
                        />
                      </div>
                    </>
                  ) : null}
                  <div className="space-y-2 sm:col-span-2">
                    <div className="flex items-center justify-between gap-3">
                      <Label htmlFor="chat-provider-webhook-secret">
                        {provider === "slack" ? "App-level token" : "Webhook secret"}
                      </Label>
                      {provider === "slack" ? null : (
                        <Button
                          onClick={() => setWebhookSecret(randomSecret())}
                          size="sm"
                          type="button"
                          variant="outline"
                        >
                          <KeyRound className="size-4" />
                          Generate
                        </Button>
                      )}
                    </div>
                    <Input
                      autoComplete="off"
                      id="chat-provider-webhook-secret"
                      onChange={(event) =>
                        provider === "slack"
                          ? setSlackAppToken(event.target.value)
                          : setWebhookSecret(event.target.value)
                      }
                      required
                      type={provider === "slack" ? "password" : "text"}
                      value={provider === "slack" ? slackAppToken : webhookSecret}
                    />
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {mode === "edit" && connection?.provider === "whatsapp_local" ? (
            <Card>
              <CardHeader className="border-b border-border">
                <CardTitle className="flex items-center gap-2 text-base">
                  <QrCode className="size-4 text-muted-foreground" />
                  Pairing
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 p-4 md:grid-cols-[220px_minmax(0,1fr)]">
                <div className="flex min-h-[220px] items-center justify-center rounded-md border border-border bg-muted/30 p-4">
                  {pairingStatus?.qrPayload ? (
                    <QRCodeSVG
                      className="rounded-sm bg-white p-2"
                      level="M"
                      size={184}
                      value={pairingStatus.qrPayload}
                    />
                  ) : (
                    <div className="text-center">
                      <div className="mx-auto flex size-12 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
                        {isPairingBusy ? (
                          <Loader2 className="size-5 animate-spin" />
                        ) : (
                          <QrCode className="size-5" />
                        )}
                      </div>
                      <div className="mt-3 text-sm font-medium">
                        {pairingStatus?.status === "connected" ? "Connected" : "No QR loaded"}
                      </div>
                    </div>
                  )}
                </div>
                <div className="space-y-4">
                  <div className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <StatusDot tone={statusTone(connection, pairingStatus)} />
                        <div className="truncate text-sm font-medium">
                          {statusLabel(connection, pairingStatus)}
                        </div>
                      </div>
                      <Badge
                        variant={pairingStatus?.status === "connected" ? "success" : "secondary"}
                      >
                        {pairingStatus?.status === "connected" ? "Ready" : "Pairing"}
                      </Badge>
                    </div>
                    {pairingStatus?.message ? (
                      <div className="mt-2 text-sm leading-5 text-muted-foreground">
                        {pairingStatus.message}
                      </div>
                    ) : null}
                    {pairingStatus?.phoneNumber ? (
                      <div className="mt-3 border-t border-border pt-3 text-sm">
                        Linked number: {pairingStatus.phoneNumber}
                      </div>
                    ) : null}
                  </div>
                  <Button
                    disabled={isPairingBusy}
                    onClick={() => refreshPairingStatus(true)}
                    type="button"
                  >
                    {isPairingBusy ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <QrCode className="size-4" />
                    )}
                    {pairingStatus?.qrPayload ? "Generate new QR" : "Show QR"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {mode === "edit" ? (
            <Card>
              <CardHeader className="border-b border-border">
                <CardTitle className="flex items-center gap-2 text-base">
                  <MessageCircle className="size-4 text-muted-foreground" />
                  Replies
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 p-4">
                <div className="flex flex-col gap-3 rounded-md border border-border p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-sm font-medium text-foreground">
                      {allowAllSenders ? "Every sender can start a chat" : "Only selected threads"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Reply access controls who can interact with this connected account.
                    </div>
                  </div>
                  <label className="flex items-center gap-3 text-sm">
                    <input
                      checked={allowAllSenders}
                      className="size-4 accent-primary"
                      onChange={(event) => setAllowAllSenders(event.target.checked)}
                      type="checkbox"
                    />
                    Allow all
                  </label>
                </div>

                {!allowAllSenders ? (
                  knownIdentities.length > 0 ? (
                    <div className="grid gap-2">
                      {knownIdentities.map((identity) => {
                        const checked = selectedChatIds.includes(identity.externalThreadId);
                        return (
                          <label
                            className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
                            key={identity.externalThreadId}
                          >
                            <span className="min-w-0">
                              <span className="block truncate font-medium text-foreground">
                                {identityLabel(identity)}
                              </span>
                              <span className="block truncate text-xs text-muted-foreground">
                                Last message {displayDate(identity.lastSeenAt)}
                              </span>
                            </span>
                            <input
                              checked={checked}
                              className="size-4 shrink-0 accent-primary"
                              onChange={(event) =>
                                setKnownConversationAllowed(
                                  identity.externalThreadId,
                                  event.target.checked
                                )
                              }
                              type="checkbox"
                            />
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                      No conversations have messaged this provider yet.
                    </div>
                  )
                ) : null}

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="edit-chat-provider-senders">Sender IDs</Label>
                    <textarea
                      className="min-h-24 w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/15"
                      id="edit-chat-provider-senders"
                      onChange={(event) => setAllowedSenderIds(event.target.value)}
                      value={allowedSenderIds}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-chat-provider-chats">Chat IDs</Label>
                    <textarea
                      className="min-h-24 w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/15"
                      id="edit-chat-provider-chats"
                      onChange={(event) => setAllowedChatIds(event.target.value)}
                      value={allowedChatIds}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {mode === "edit" ? (
            <Card>
              <CardHeader className="border-b border-border">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <ShieldCheck className="size-4 text-muted-foreground" />
                    Approvals
                  </CardTitle>
                  <Badge variant={selectedApproverCount > 0 ? "success" : "secondary"}>
                    {selectedApproverCount > 0
                      ? `${selectedApproverCount} linked`
                      : "No delivery route"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 p-4">
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                  Approval access and reply access are separate. Select a Wardn workspace member,
                  then link that member to a known thread on this provider. Without the linked
                  thread, Wardn cannot send the approval URL externally.
                </div>
                {knownIdentities.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                    No provider threads are known yet. Ask the approver to message this connected
                    account, refresh this page, then link that thread here.
                  </div>
                ) : null}

                {workspaceMembers.length > 0 ? (
                  <div className="grid gap-2">
                    {workspaceMembers.map((member) => {
                      const checked = Object.hasOwn(approvalThreadsByUserId, member.userId);
                      const threadId = approvalThreadsByUserId[member.userId] ?? "";
                      const missingLink = checked && !threadId;
                      return (
                        <div
                          className={cn(
                            "grid gap-3 rounded-md border px-3 py-3 text-sm lg:grid-cols-[minmax(0,1fr)_260px]",
                            missingLink ? "border-red-200 bg-red-50/40" : "border-border"
                          )}
                          key={`approval-${member.userId}`}
                        >
                          <label className="flex min-w-0 items-start gap-3">
                            <input
                              checked={checked}
                              className="mt-1 size-4 shrink-0 accent-primary"
                              onChange={(event) =>
                                setWorkspaceMemberApproval(member.userId, event.target.checked)
                              }
                              type="checkbox"
                            />
                            <span className="min-w-0">
                              <span className="flex min-w-0 items-center gap-2">
                                <span className="truncate font-medium text-foreground">
                                  {workspaceMemberLabel(member)}
                                </span>
                                <Badge className="shrink-0" variant="outline">
                                  {member.role}
                                </Badge>
                              </span>
                              <span className="mt-1 block truncate text-xs text-muted-foreground">
                                {member.email}
                              </span>
                            </span>
                          </label>
                          <div className="space-y-1">
                            <Select
                              disabled={!checked || knownIdentities.length === 0}
                              onValueChange={(value) =>
                                setWorkspaceMemberThread(member.userId, value)
                              }
                              value={threadId || NO_THREAD_VALUE}
                            >
                              <SelectTrigger aria-label={`Approval thread for ${member.email}`}>
                                <SelectValue placeholder="Link provider thread" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={NO_THREAD_VALUE}>No linked thread</SelectItem>
                                {knownIdentities.map((identity) => {
                                  const linkedToAnother =
                                    selectedApprovalThreadIds.has(identity.externalThreadId) &&
                                    threadId !== identity.externalThreadId;
                                  return (
                                    <SelectItem
                                      disabled={linkedToAnother}
                                      key={identity.externalThreadId}
                                      value={identity.externalThreadId}
                                    >
                                      {identityLabel(identity)}
                                      {linkedToAnother ? " (already linked)" : ""}
                                    </SelectItem>
                                  );
                                })}
                              </SelectContent>
                            </Select>
                            {missingLink ? (
                              <div className="text-xs text-red-700">
                                Select the provider thread for this approver.
                              </div>
                            ) : threadId ? (
                              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                                <Link2 className="size-3" />
                                Linked to {linkedThreadLabel(knownIdentities, threadId)}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                    No active workspace members are available for approval routing.
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>

        <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Card>
            <CardHeader className="border-b border-border">
              <CardTitle className="text-base">Summary</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Provider</span>
                <Badge variant="outline">{providerOption(provider).shortLabel}</Badge>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Replies</span>
                <span className="font-medium">{allowAllSenders ? "All senders" : "Restricted"}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Approval delivery</span>
                <span className="font-medium">
                  {selectedApproverCount > 0
                    ? `${selectedApproverCount} linked`
                    : "Not configured"}
                </span>
              </div>
              {missingApprovalLinks.length > 0 ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                  {missingApprovalLinks.length} selected approver
                  {missingApprovalLinks.length === 1 ? "" : "s"} need a linked provider thread.
                </div>
              ) : null}
              {mode === "edit" && connection ? (
                <>
                  <div className="border-t border-border pt-3" />
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">Known threads</span>
                    <span className="font-medium">{knownIdentities.length}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">Updated</span>
                    <span className="font-medium">{displayDate(connection.updatedAt)}</span>
                  </div>
                </>
              ) : null}
              {mode === "create" && activeSecretStores.length === 0 ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                  A secret backend is required before creating chat providers.
                </div>
              ) : null}
            </CardContent>
          </Card>

          {mode === "edit" && connection ? (
            <Card>
              <CardHeader className="border-b border-border">
                <CardTitle className="flex items-center gap-2 text-base">
                  <RefreshCw className="size-4 text-muted-foreground" />
                  Runtime
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Status</span>
                  <span className="flex items-center gap-2 font-medium">
                    <StatusDot tone={statusTone(connection, pairingStatus)} />
                    {statusLabel(connection, pairingStatus)}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Session</span>
                  <span className="truncate font-medium">
                    {pairingStatus?.phoneNumber || bridgeUserId}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Bridge</span>
                  <span className="truncate font-medium">
                    {connection.provider === "whatsapp_local"
                      ? displayHost(pairingStatus?.bridgeBaseUrl || bridgeBaseUrl)
                      : "Telegram API"}
                  </span>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </div>
    </form>
  );
}
