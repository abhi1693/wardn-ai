"use client";

import {
  Bot,
  KeyRound,
  Loader2,
  MessageCircle,
  Pause,
  Play,
  Plus,
  QrCode,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Smartphone,
  Trash2,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { StatusDot } from "@/components/atoms/status-dot";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  ChatProviderWorkspaceMemberRead,
  ChatProviderPairingStatusResponse,
  SecretStoreRead,
} from "@/lib/api/generated/model";
import {
  workspaceChatProvidersDelete,
  workspaceChatProvidersPairingStatus,
  workspaceChatProvidersResetPairingQr,
  workspaceChatProvidersUpdate,
} from "@/lib/api/generated/workspace-chat-providers/workspace-chat-providers";
import { formatUserDateTime } from "@/lib/date-time";
import { cn } from "@/lib/utils";

type ProviderType = "whatsapp_local" | "telegram";

type ChatProvidersClientProps = {
  connections: ChatProviderConnectionRead[];
  organizationId: string;
  workspaceId: string;
};

type ProviderOption = {
  value: ProviderType;
  label: string;
  shortLabel: string;
  icon: typeof Smartphone;
};

const providerOptions: ProviderOption[] = [
  {
    value: "whatsapp_local",
    label: "WhatsApp local",
    shortLabel: "WhatsApp",
    icon: Smartphone,
  },
  {
    value: "telegram",
    label: "Telegram bot",
    shortLabel: "Telegram",
    icon: Bot,
  },
];

const needsSetupStatuses = new Set(["not_configured", "needs_pairing", "error"]);

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

function providerApprovalRouteCount(config: unknown) {
  return approvalRoutesConfig(config).filter(
    (route) =>
      approvalRouteType(route) === "workspace_member" &&
      approvalRouteUserId(route) &&
      approvalRouteThreadId(route)
  ).length;
}

function providerUnlinkedApprovalRouteCount(config: unknown) {
  return approvalRoutesConfig(config).filter(
    (route) =>
      approvalRouteType(route) === "workspace_member" &&
      approvalRouteUserId(route) &&
      !approvalRouteThreadId(route)
  ).length;
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
  if (!pairing || pairing.status === "waiting_for_scan") {
    return "warning" as const;
  }
  if (pairing.status === "connected") {
    return "success" as const;
  }
  if (pairing.status === "error" || pairing.status === "not_configured") {
    return "danger" as const;
  }
  return "warning" as const;
}

function badgeVariant(
  connection: ChatProviderConnectionRead,
  pairing?: ChatProviderPairingStatusResponse
) {
  const tone = statusTone(connection, pairing);
  if (tone === "success") {
    return "success" as const;
  }
  if (tone === "danger") {
    return "destructive" as const;
  }
  return "secondary" as const;
}

function connectionNeedsSetup(
  connection: ChatProviderConnectionRead,
  pairing?: ChatProviderPairingStatusResponse
) {
  return (
    !connection.isActive ||
    (connection.provider === "whatsapp_local" &&
      (!pairing || needsSetupStatuses.has(pairing.status)))
  );
}

function providerCounts(
  connections: ChatProviderConnectionRead[],
  pairingStatuses: Record<string, ChatProviderPairingStatusResponse>
) {
  const whatsapp = connections.filter((connection) => connection.provider === "whatsapp_local");
  const active = connections.filter((connection) => connection.isActive).length;
  const connected = whatsapp.filter(
    (connection) => pairingStatuses[connection.id]?.status === "connected"
  ).length;
  const needsSetup = connections.filter((connection) =>
    connectionNeedsSetup(connection, pairingStatuses[connection.id])
  ).length;
  return { active, connected, needsSetup, total: connections.length, whatsapp: whatsapp.length };
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

export function ConnectProviderDialog({
  activeSecretStores,
  connectionCount,
  defaultWhatsappBridgeBaseUrl,
  isCreating,
  onCreate,
  onOpenChange,
  open,
}: {
  activeSecretStores: SecretStoreRead[];
  connectionCount: number;
  defaultWhatsappBridgeBaseUrl: string;
  isCreating: boolean;
  onCreate: (payload: ChatProviderConnectionCreate) => Promise<void>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const normalizedDefaultBridgeUrl = defaultWhatsappBridgeBaseUrl.trim();
  const [provider, setProvider] = useState<ProviderType>("whatsapp_local");
  const [name, setName] = useState("Personal WhatsApp");
  const [bridgeBaseUrl, setBridgeBaseUrl] = useState(normalizedDefaultBridgeUrl);
  const [bridgeUserId, setBridgeUserId] = useState(defaultBridgeUserId);
  const [secretStoreId, setSecretStoreId] = useState(activeSecretStores[0]?.id ?? "");
  const [webhookSecret, setWebhookSecret] = useState(randomSecret);
  const [botToken, setBotToken] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  function applyProviderDefaults(nextProvider: ProviderType) {
    setProvider(nextProvider);
    setName(
      nextProvider === "telegram"
        ? "Workspace Telegram"
        : connectionCount > 0
          ? `Personal WhatsApp ${connectionCount + 1}`
          : "Personal WhatsApp"
    );
    if (nextProvider === "whatsapp_local") {
      setBridgeBaseUrl(normalizedDefaultBridgeUrl);
    }
    setAdvancedOpen(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    const normalizedBridgeUserId = bridgeUserId.trim() || defaultBridgeUserId();
    const secretValues: Record<string, string> = { webhook_secret: webhookSecret.trim() };
    if (provider === "telegram") {
      secretValues.bot_token = botToken.trim();
    } else {
      secretValues.outbound_secret = webhookSecret.trim();
    }

    const payload: ChatProviderConnectionCreate =
      provider === "telegram"
        ? {
            config: {
              allowAllSenders: true,
              allowedChatIds: [],
              allowedSenderIds: [],
              approvalRoutes: [],
              replyOnUnsupportedMessages: false,
            },
            displayName: normalizedName,
            externalId: normalizedBridgeUserId,
            name: normalizedName,
            provider,
            secretStoreId,
            secretValues,
          }
        : {
            config: {
              accountName: normalizedBridgeUserId,
              allowAllSenders: true,
              allowedChatIds: [],
              allowedSenderIds: [],
              approvalRoutes: [],
              bridgeBaseUrl: bridgeBaseUrl.trim(),
              bridgeUserId: normalizedBridgeUserId,
              replyOnUnsupportedMessages: false,
            },
            displayName: normalizedName,
            externalId: normalizedBridgeUserId,
            name: normalizedName,
            provider,
            secretStoreId,
            secretValues,
          };

    await onCreate(payload);
    setWebhookSecret(randomSecret());
    setBotToken("");
  }

  const canCreate =
    name.trim().length > 0 &&
    secretStoreId.length > 0 &&
    webhookSecret.trim().length > 0 &&
    (provider !== "telegram" || botToken.trim().length > 0) &&
    (provider !== "whatsapp_local" || bridgeBaseUrl.trim().length > 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Connect provider</DialogTitle>
          <DialogDescription>Pair a workspace chat entrypoint.</DialogDescription>
        </DialogHeader>

        <form className="space-y-5" onSubmit={submit}>
          <div className="grid gap-2 sm:grid-cols-2">
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
                  <div>
                    <div className="text-sm font-medium text-foreground">
                      {option.shortLabel}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-muted-foreground">
                      {option.value === "whatsapp_local"
                        ? "Personal number pairing"
                        : "Bot token integration"}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

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
            {provider === "whatsapp_local" ? (
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
            ) : (
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
            )}
          </div>

          <div className="rounded-md border border-border">
            <div className="p-3">
              <div>
                <div className="text-sm font-medium text-foreground">Replies</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Open while pairing. Restrict replies from Edit after conversations appear.
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-md border border-border">
            <button
              className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm font-medium"
              onClick={() => setAdvancedOpen((current) => !current)}
              type="button"
            >
              <span className="flex items-center gap-2">
                <Settings2 className="size-4 text-muted-foreground" />
                Advanced
              </span>
              <span className="text-xs text-muted-foreground">
                {advancedOpen ? "Hide" : "Show"}
              </span>
            </button>
            {advancedOpen ? (
              <div className="grid gap-3 border-t border-border p-3 sm:grid-cols-2">
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
                    {provider === "whatsapp_local" ? "Bridge user ID" : "External ID"}
                  </Label>
                  <Input
                    id="chat-provider-external"
                    maxLength={255}
                    onChange={(event) => setBridgeUserId(event.target.value)}
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
                <div className="space-y-2 sm:col-span-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label htmlFor="chat-provider-webhook-secret">Webhook secret</Label>
                    <Button
                      onClick={() => setWebhookSecret(randomSecret())}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      <KeyRound className="size-4" />
                      Generate
                    </Button>
                  </div>
                  <Input
                    autoComplete="off"
                    id="chat-provider-webhook-secret"
                    onChange={(event) => setWebhookSecret(event.target.value)}
                    required
                    value={webhookSecret}
                  />
                </div>
              </div>
            ) : null}
          </div>

          {activeSecretStores.length === 0 ? (
            <AsyncFeedback variant="error">
              A secret backend is required before creating chat providers.
            </AsyncFeedback>
          ) : null}

          <DialogFooter>
            <Button
              onClick={() => onOpenChange(false)}
              type="button"
              variant="outline"
            >
              Cancel
            </Button>
            <Button disabled={!canCreate || isCreating} type="submit">
              {isCreating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              {isCreating ? "Creating" : "Create connection"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EditProviderDialog({
  connection,
  isSaving,
  onOpenChange,
  onSave,
  open,
  workspaceMembers,
}: {
  connection: ChatProviderConnectionRead;
  isSaving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (
    connection: ChatProviderConnectionRead,
    payload: {
      config: Record<string, unknown>;
      displayName: string;
      isActive: boolean;
      name: string;
    }
  ) => Promise<void>;
  open: boolean;
  workspaceMembers: ChatProviderWorkspaceMemberRead[];
}) {
  const initialConfig = record(connection.config);
  const [name, setName] = useState(connection.name);
  const [isActive, setIsActive] = useState(connection.isActive);
  const [allowAllSenders, setAllowAllSenders] = useState(
    boolConfigDefault(initialConfig, true, "allow_all_senders", "allowAllSenders")
  );
  const [allowedSenderIds, setAllowedSenderIds] = useState(
    listText(arrayConfig(initialConfig, "allowed_sender_ids", "allowedSenderIds"))
  );
  const [allowedChatIds, setAllowedChatIds] = useState(
    listText(arrayConfig(initialConfig, "allowed_chat_ids", "allowedChatIds"))
  );
  const initialApprovalRoutes = approvalRoutesConfig(initialConfig);
  const [selectedApprovalMemberIds, setSelectedApprovalMemberIds] = useState(() =>
    Array.from(
      new Set(
        initialApprovalRoutes
          .filter((route) => approvalRouteType(route) === "workspace_member")
          .map(approvalRouteUserId)
          .filter((userId) =>
            workspaceMembers.some((member) => member.userId === userId)
          )
      )
    )
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const config = record(connection.config);
  const knownIdentities = connection.knownIdentities ?? [];
  const selectedChatIds = stringList(allowedChatIds);

  function setKnownConversationAllowed(threadId: string, checked: boolean) {
    const next = checked
      ? appendListValue(selectedChatIds, threadId)
      : removeListValue(selectedChatIds, threadId);
    setAllowedChatIds(listText(next));
  }

  function setWorkspaceMemberApproval(userId: string, checked: boolean) {
    setSelectedApprovalMemberIds((current) => {
      return checked
        ? appendListValue(current, userId)
        : removeListValue(current, userId);
    });
  }

  function providerConfigPayload() {
    const memberLabels = new Map(
      workspaceMembers.map((member) => [member.userId, workspaceMemberLabel(member)])
    );
    const approvalRoutes = selectedApprovalMemberIds.map((userId) => ({
      displayName: memberLabels.get(userId) ?? userId,
      routeType: "workspace_member",
      userId,
    }));
    const common = {
      allowAllSenders: allowAllSenders,
      allowedChatIds: stringList(allowedChatIds),
      allowedSenderIds: stringList(allowedSenderIds),
      approvalRoutes,
      replyOnUnsupportedMessages: boolConfigDefault(
        config,
        false,
        "reply_on_unsupported_messages",
        "replyOnUnsupportedMessages"
      ),
    };
    if (connection.provider === "whatsapp_local") {
      return {
        ...common,
        accountName: stringConfig(config, "account_name", "accountName"),
        bridgeBaseUrl: stringConfig(config, "bridge_base_url", "bridgeBaseUrl"),
        bridgeUserId: stringConfig(config, "bridge_user_id", "bridgeUserId"),
        outboundWebhookUrl: stringConfig(config, "outbound_webhook_url", "outboundWebhookUrl"),
      };
    }
    return common;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName || isSaving) {
      return;
    }
    await onSave(connection, {
      config: providerConfigPayload(),
      displayName: normalizedName,
      isActive,
      name: normalizedName,
    });
  }

  const canSave = name.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit provider</DialogTitle>
          <DialogDescription>{providerOption(connection.provider).shortLabel}</DialogDescription>
        </DialogHeader>

        <form className="space-y-5" onSubmit={submit}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="edit-chat-provider-name">Name</Label>
              <Input
                id="edit-chat-provider-name"
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </div>
            <label className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm sm:mt-7">
              <input
                checked={isActive}
                className="size-4 accent-primary"
                onChange={(event) => setIsActive(event.target.checked)}
                type="checkbox"
              />
              Active
            </label>
          </div>

          <div className="rounded-md border border-border">
            <div className="flex flex-col gap-3 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-sm font-medium text-foreground">Replies</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {allowAllSenders ? "Open to every sender" : "Only selected conversations"}
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
              <div className="space-y-3 p-3">
                {knownIdentities.length > 0 ? (
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
                )}

                <div className="rounded-md border border-border">
                  <button
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm font-medium"
                    onClick={() => setAdvancedOpen((current) => !current)}
                    type="button"
                  >
                    <span>Advanced IDs</span>
                    <span className="text-xs text-muted-foreground">
                      {advancedOpen ? "Hide" : "Show"}
                    </span>
                  </button>
                  {advancedOpen ? (
                    <div className="grid gap-3 border-t border-border p-3 sm:grid-cols-2">
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
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>

          <div className="rounded-md border border-border">
            <div className="flex flex-col gap-3 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-sm font-medium text-foreground">Approvals</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {selectedApprovalMemberIds.length > 0
                    ? "Approval links are available to selected workspace members"
                    : "No approval delivery route is configured"}
                </div>
              </div>
              <Badge variant={selectedApprovalMemberIds.length > 0 ? "success" : "secondary"}>
                {selectedApprovalMemberIds.length > 0
                  ? `${selectedApprovalMemberIds.length} selected`
                  : "No delivery route"}
              </Badge>
            </div>
            <div className="space-y-3 p-3">
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                Reply access does not grant approval access. Select workspace owners,
                admins, or trusted members here. Approval links stay inside Wardn and are never
                sent to the external chat that triggered the request.
              </div>

              {workspaceMembers.length > 0 ? (
                <div className="grid gap-2">
                  {workspaceMembers.map((member) => {
                    const checked = selectedApprovalMemberIds.includes(member.userId);
                    return (
                      <label
                        className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
                        key={`approval-${member.userId}`}
                      >
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
                        <input
                          checked={checked}
                          className="size-4 shrink-0 accent-primary"
                          onChange={(event) =>
                            setWorkspaceMemberApproval(member.userId, event.target.checked)
                          }
                          type="checkbox"
                        />
                      </label>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                  No active workspace members are available for approval routing.
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button onClick={() => onOpenChange(false)} type="button" variant="outline">
              Cancel
            </Button>
            <Button disabled={!canSave || isSaving} type="submit">
              {isSaving ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Settings2 className="size-4" />
              )}
              {isSaving ? "Saving" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PairingDialog({
  connection,
  onOpenChange,
  onRefresh,
  open,
  pairingStatus,
  busy,
}: {
  busy: boolean;
  connection: ChatProviderConnectionRead | null;
  onOpenChange: (open: boolean) => void;
  onRefresh: (connection: ChatProviderConnectionRead) => Promise<void>;
  open: boolean;
  pairingStatus?: ChatProviderPairingStatusResponse;
}) {
  const isConnected = pairingStatus?.status === "connected";
  const qrPayload = pairingStatus?.qrPayload ?? "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Connect WhatsApp</DialogTitle>
          <DialogDescription>{connection?.name ?? "Workspace WhatsApp"}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-5 md:grid-cols-[220px_minmax(0,1fr)]">
          <div className="flex min-h-[220px] items-center justify-center rounded-md border border-border bg-muted/30 p-4">
            {qrPayload ? (
              <QRCodeSVG
                className="rounded-sm bg-white p-2"
                level="M"
                size={184}
                value={qrPayload}
              />
            ) : (
              <div className="text-center">
                <div className="mx-auto flex size-12 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
                  {busy ? (
                    <Loader2 className="size-5 animate-spin" />
                  ) : (
                    <QrCode className="size-5" />
                  )}
                </div>
                <div className="mt-3 text-sm font-medium">
                  {isConnected ? "Connected" : "No QR loaded"}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="grid gap-2">
              {[
                { label: "Create connection", done: true },
                { label: "QR shown", done: isConnected || Boolean(qrPayload) },
                { label: "Phone linked", done: isConnected },
              ].map((step, index) => (
                <div
                  className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm"
                  key={step.label}
                >
                  <div
                    className={cn(
                      "flex size-6 items-center justify-center rounded-full border text-xs font-semibold",
                      step.done
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border-border bg-muted text-muted-foreground"
                    )}
                  >
                    {index + 1}
                  </div>
                  <span>{step.label}</span>
                </div>
              ))}
            </div>

            <div className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <StatusDot
                    tone={
                      pairingStatus?.status === "connected"
                        ? "success"
                        : pairingStatus?.status === "error" ||
                            pairingStatus?.status === "not_configured"
                          ? "danger"
                          : "warning"
                    }
                  />
                  <div className="truncate text-sm font-medium">
                    {pairingStatus ? statusLabel(connection!, pairingStatus) : "Checking"}
                  </div>
                </div>
                <Badge variant={isConnected ? "success" : "secondary"}>
                  {isConnected ? "Ready" : "Pairing"}
                </Badge>
              </div>
              {pairingStatus?.message ? (
                <div className="mt-2 text-sm leading-5 text-muted-foreground">
                  {pairingStatus.message}
                </div>
              ) : null}
              {!isConnected ? (
                <div className="mt-2 text-sm leading-5 text-muted-foreground">
                  WhatsApp QR codes expire quickly. If WhatsApp says it could not link the
                  device, generate a new QR and scan it immediately from Linked Devices.
                </div>
              ) : null}
              {pairingStatus?.bridgeBaseUrl ? (
                <div className="mt-3 grid gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
                  <div className="flex items-center justify-between gap-3">
                    <span>Bridge</span>
                    <span className="truncate text-foreground">
                      {displayHost(pairingStatus.bridgeBaseUrl)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span>Session</span>
                    <span className="truncate text-foreground">{pairingStatus.bridgeUserId}</span>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!connection || busy}
                onClick={() => connection && onRefresh(connection)}
                type="button"
              >
                {busy ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <QrCode className="size-4" />
                )}
                {qrPayload ? "Generate new QR" : "Show QR"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ChatProvidersClient({
  connections,
  organizationId,
  workspaceId,
}: ChatProvidersClientProps) {
  const router = useRouter();
  const [connectionOverrides, setConnectionOverrides] = useState<
    Record<string, ChatProviderConnectionRead>
  >({});
  const [deletedConnectionIds, setDeletedConnectionIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [pairingOpen, setPairingOpen] = useState(false);
  const [pairingConnection, setPairingConnection] = useState<ChatProviderConnectionRead | null>(
    null
  );
  const [pairingStatuses, setPairingStatuses] = useState<
    Record<string, ChatProviderPairingStatusResponse>
  >({});
  const [busyConnectionId, setBusyConnectionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chatProvidersBasePath = `/org/${organizationId}/workspace/${workspaceId}/chat-providers`;
  const activePairingStatus = pairingConnection
    ? pairingStatuses[pairingConnection.id]
    : undefined;

  const deletedConnectionIdSet = useMemo(
    () => new Set(deletedConnectionIds),
    [deletedConnectionIds]
  );

  const localConnections = useMemo(() => {
    const baseIds = new Set(connections.map((connection) => connection.id));
    const merged = connections
      .filter((connection) => !deletedConnectionIdSet.has(connection.id))
      .map((connection) => connectionOverrides[connection.id] ?? connection);
    const extra = Object.values(connectionOverrides).filter(
      (connection) => !baseIds.has(connection.id) && !deletedConnectionIdSet.has(connection.id)
    );
    return [...extra, ...merged];
  }, [connectionOverrides, connections, deletedConnectionIdSet]);

  const replaceConnection = useCallback((connection: ChatProviderConnectionRead) => {
    setConnectionOverrides((current) => ({ ...current, [connection.id]: connection }));
    setDeletedConnectionIds((current) => current.filter((id) => id !== connection.id));
    setPairingConnection((current) => (current?.id === connection.id ? connection : current));
  }, []);

  const counts = useMemo(
    () => providerCounts(localConnections, pairingStatuses),
    [localConnections, pairingStatuses]
  );

  const filteredConnections = useMemo(() => {
    const query = search.trim().toLowerCase();
    return localConnections
      .filter((connection) => {
        const config = record(connection.config);
        const bridgeBaseUrl = stringConfig(config, "bridge_base_url", "bridgeBaseUrl");
        const bridgeUserId = stringConfig(config, "bridge_user_id", "bridgeUserId");
        const option = providerOption(connection.provider);
        const matchesQuery =
          !query ||
          connection.name.toLowerCase().includes(query) ||
          connection.externalId.toLowerCase().includes(query) ||
          option.shortLabel.toLowerCase().includes(query) ||
          bridgeBaseUrl.toLowerCase().includes(query) ||
          bridgeUserId.toLowerCase().includes(query);
        return matchesQuery;
      })
      .sort((first, second) => {
        const firstNeeds = connectionNeedsSetup(first, pairingStatuses[first.id]);
        const secondNeeds = connectionNeedsSetup(second, pairingStatuses[second.id]);
        if (firstNeeds !== secondNeeds) {
          return firstNeeds ? -1 : 1;
        }
        if (first.isActive !== second.isActive) {
          return first.isActive ? -1 : 1;
        }
        return first.name.localeCompare(second.name);
      });
  }, [localConnections, pairingStatuses, search]);

  useEffect(() => {
    let ignore = false;
    async function loadPairingStatuses() {
      const whatsappConnections = localConnections.filter(
        (connection) => connection.provider === "whatsapp_local"
      );
      if (whatsappConnections.length === 0) {
        return;
      }
      const results = await Promise.all(
        whatsappConnections.map(async (connection) => {
          try {
            const status = await workspaceChatProvidersPairingStatus(
              organizationId,
              workspaceId,
              connection.id,
              { timeoutMs: 15_000 }
            );
            return [connection.id, status] as const;
          } catch {
            return [
              connection.id,
              {
                ok: false,
                provider: connection.provider,
                status: "error" as const,
                message: "Pairing status could not be loaded.",
              },
            ] as const;
          }
        })
      );
      if (!ignore) {
        setPairingStatuses((current) => ({
          ...current,
          ...Object.fromEntries(results),
        }));
      }
    }

    void loadPairingStatuses();
    return () => {
      ignore = true;
    };
  }, [localConnections, organizationId, workspaceId]);

  async function refreshPairingStatus(
    connection: ChatProviderConnectionRead,
    refreshQr = false
  ) {
    setBusyConnectionId(connection.id);
    setError(null);
    try {
      const status = refreshQr
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
      setPairingStatuses((current) => ({
        ...current,
        [connection.id]: mergePairingStatus(current[connection.id], status, {
          preserveQr: !refreshQr,
        }),
      }));
      if (status.status === "error") {
        setError(status.message || "WhatsApp bridge status failed.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Pairing status could not be loaded.");
    } finally {
      setBusyConnectionId(null);
    }
  }

  useEffect(() => {
    if (
      !pairingOpen ||
      !pairingConnection ||
      !activePairingStatus?.qrPayload ||
      activePairingStatus.status === "connected"
    ) {
      return;
    }

    const connection = pairingConnection;
    let ignore = false;
    async function pollPairingStatus() {
      try {
        const status = await workspaceChatProvidersPairingStatus(
          organizationId,
          workspaceId,
          connection.id,
          { timeoutMs: 15_000 }
        );
        if (!ignore) {
          setPairingStatuses((current) => ({
            ...current,
            [connection.id]: mergePairingStatus(current[connection.id], status, {
              preserveQr: true,
            }),
          }));
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
    activePairingStatus?.qrPayload,
    activePairingStatus?.status,
    organizationId,
    pairingConnection,
    pairingOpen,
    workspaceId,
  ]);

  async function toggleConnection(connection: ChatProviderConnectionRead) {
    setBusyConnectionId(connection.id);
    setError(null);
    try {
      const updated = await workspaceChatProvidersUpdate(
        organizationId,
        workspaceId,
        connection.id,
        {
          isActive: !connection.isActive,
        }
      );
      replaceConnection(updated);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Provider connection could not be updated."
      );
    } finally {
      setBusyConnectionId(null);
    }
  }

  async function deleteConnection(connection: ChatProviderConnectionRead) {
    setBusyConnectionId(connection.id);
    setError(null);
    try {
      await workspaceChatProvidersDelete(organizationId, workspaceId, connection.id);
      setConnectionOverrides((current) => {
        const next = { ...current };
        delete next[connection.id];
        return next;
      });
      setDeletedConnectionIds((current) =>
        current.includes(connection.id) ? current : [...current, connection.id]
      );
      setPairingStatuses((current) => {
        const next = { ...current };
        delete next[connection.id];
        return next;
      });
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Provider connection could not be deleted."
      );
    } finally {
      setBusyConnectionId(null);
    }
  }

  function openPairing(connection: ChatProviderConnectionRead, refreshQr = false) {
    setPairingConnection(connection);
    setPairingOpen(true);
    void refreshPairingStatus(connection, refreshQr);
  }

  const summaryItems = [
    { label: "total", value: counts.total },
    { label: "active", value: counts.active },
    { label: "connected", value: counts.connected },
    { label: "needs setup", value: counts.needsSetup },
    { label: "WhatsApp", value: counts.whatsapp },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)] lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold leading-5 text-foreground">Chat providers</div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
            {summaryItems.map((item) => (
              <span
                className="inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-muted/60 px-2"
                key={item.label}
              >
                <span className="font-semibold text-foreground">
                  {item.value.toLocaleString("en-US")}
                </span>
                {item.label}
              </span>
            ))}
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative min-w-0 sm:w-[320px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search providers"
              type="search"
              value={search}
            />
          </div>
          <Button asChild>
            <Link href={`${chatProvidersBasePath}/new`}>
              <Plus className="size-4" />
              Connect provider
            </Link>
          </Button>
        </div>
      </div>

      {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

      {localConnections.length === 0 ? (
        <Card className="flex min-h-72 flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="flex size-11 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
            <Smartphone className="size-5" />
          </div>
          <div>
            <div className="font-medium text-foreground">Connect your first WhatsApp number</div>
            <div className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">
              Pair a personal WhatsApp linked device to this workspace agent.
            </div>
          </div>
          <Button asChild size="sm">
            <Link href={`${chatProvidersBasePath}/new`}>
              <Plus className="size-4" />
              Connect WhatsApp
            </Link>
          </Button>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Bot className="size-3.5" />
            Telegram bot connections are available from the provider picker.
          </div>
        </Card>
      ) : filteredConnections.length === 0 ? (
        <Card className="flex min-h-60 flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="flex size-10 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
            <Search className="size-5" />
          </div>
          <div>
            <div className="font-medium text-foreground">No providers in view</div>
            <div className="mt-1 text-sm text-muted-foreground">No matching provider records.</div>
          </div>
        </Card>
      ) : (
        <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredConnections.map((connection) => {
            const option = providerOption(connection.provider);
            const Icon = option.icon;
            const config = record(connection.config);
            const pairingStatus = pairingStatuses[connection.id];
            const bridgeBaseUrl = stringConfig(config, "bridge_base_url", "bridgeBaseUrl");
            const effectiveBridgeBaseUrl = pairingStatus?.bridgeBaseUrl || bridgeBaseUrl;
            const bridgeUserId =
              stringConfig(config, "bridge_user_id", "bridgeUserId", "account_name", "accountName") ||
              connection.externalId;
            const isBusy = busyConnectionId === connection.id;
            const allowAllSenders = boolConfigDefault(
              config,
              true,
              "allow_all_senders",
              "allowAllSenders"
            );
            const approvalRouteCount = providerApprovalRouteCount(config);
            const unlinkedApprovalRouteCount = providerUnlinkedApprovalRouteCount(config);

            return (
              <Card
                className="flex min-h-[300px] flex-col overflow-hidden transition-colors hover:border-ring/40 hover:bg-muted/20"
                key={connection.id}
              >
                <CardHeader className="border-b-0 pb-0">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <StatusDot tone={statusTone(connection, pairingStatus)} />
                        <h3 className="truncate text-sm font-semibold leading-5 text-foreground">
                          {connection.name}
                        </h3>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge variant={badgeVariant(connection, pairingStatus)}>
                          {statusLabel(connection, pairingStatus)}
                        </Badge>
                        <Badge variant="outline">{option.shortLabel}</Badge>
                      </div>
                    </div>
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                      <Icon className="size-4" />
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="flex flex-1 flex-col p-4 pt-3">
                  <div className="grid gap-3 border-y border-border/80 py-3">
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <MessageCircle className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Session</div>
                        <div className="truncate text-sm font-medium">
                          {pairingStatus?.phoneNumber || bridgeUserId}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <Webhook className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Bridge</div>
                        <div className="truncate text-sm font-medium">
                          {connection.provider === "whatsapp_local"
                            ? displayHost(effectiveBridgeBaseUrl)
                            : "Telegram API"}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <ShieldCheck className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Access</div>
                        <div className="truncate text-sm font-medium">
                          {allowAllSenders ? "All senders" : "Restricted"}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <KeyRound className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Approvals</div>
                        <div className="truncate text-sm font-medium">
                          {unlinkedApprovalRouteCount > 0
                            ? "Needs thread link"
                            : approvalRouteCount > 0
                            ? `${approvalRouteCount} approver${approvalRouteCount === 1 ? "" : "s"}`
                            : "No delivery route"}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-3 text-sm">
                      <RefreshCw className="size-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <div className="truncate text-xs text-muted-foreground">Updated</div>
                        <div className="truncate text-sm font-medium">
                          {displayDate(connection.updatedAt)}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
                    {connection.provider === "whatsapp_local" ? (
                      <Button
                        disabled={isBusy}
                        onClick={() => openPairing(connection, !pairingStatus?.qrPayload)}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        {isBusy ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <QrCode className="size-4" />
                        )}
                        Open QR
                      </Button>
                    ) : null}
                    <Button asChild size="sm" variant="outline">
                      <Link href={`${chatProvidersBasePath}/${connection.id}/edit`}>
                        <Settings2 className="size-4" />
                        Edit
                      </Link>
                    </Button>
                    <Button
                      aria-label={
                        connection.isActive
                          ? `Pause ${connection.name}`
                          : `Resume ${connection.name}`
                      }
                      disabled={isBusy}
                      onClick={() => toggleConnection(connection)}
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      {isBusy ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : connection.isActive ? (
                        <Pause className="size-4" />
                      ) : (
                        <Play className="size-4" />
                      )}
                    </Button>
                    <Button
                      aria-label={`Delete ${connection.name}`}
                      disabled={isBusy}
                      onClick={() => deleteConnection(connection)}
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <PairingDialog
        busy={Boolean(pairingConnection && busyConnectionId === pairingConnection.id)}
        connection={pairingConnection}
        onOpenChange={(open) => {
          setPairingOpen(open);
          if (!open) {
            setPairingConnection(null);
          }
        }}
        onRefresh={(connection) => refreshPairingStatus(connection, true)}
        open={pairingOpen}
        pairingStatus={pairingConnection ? pairingStatuses[pairingConnection.id] : undefined}
      />
    </div>
  );
}
