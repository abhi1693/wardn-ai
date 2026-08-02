"use client";

import {
  Bot,
  CheckCircle2,
  Copy,
  FlaskConical,
  KeyRound,
  Loader2,
  Plus,
  Power,
  PowerOff,
  Send,
  ShieldCheck,
  Smartphone,
  Trash2,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  ChatProviderTestMessageResponse,
  SecretHandleRead,
  SecretStoreRead,
} from "@/lib/api/generated/model";
import {
  getChatProviderWebhooksTelegramReceiveUrl,
  getChatProviderWebhooksWhatsappLocalReceiveUrl,
} from "@/lib/api/generated/chat-provider-webhooks/chat-provider-webhooks";
import {
  workspaceChatProvidersCreate,
  workspaceChatProvidersDelete,
  workspaceChatProvidersTestMessage,
  workspaceChatProvidersUpdate,
} from "@/lib/api/generated/workspace-chat-providers/workspace-chat-providers";
import { cn } from "@/lib/utils";

type ProviderType = "whatsapp_local" | "telegram";

type ChatProvidersClientProps = {
  connections: ChatProviderConnectionRead[];
  organizationId: string;
  secretHandles: SecretHandleRead[];
  secretStores: SecretStoreRead[];
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

function randomSecret() {
  const cryptoValue = globalThis.crypto?.randomUUID?.();
  if (cryptoValue) {
    return `wardn_${cryptoValue.replaceAll("-", "")}`;
  }
  return `wardn_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function boolConfig(config: unknown, key: string) {
  return record(config)[key] === true;
}

function stringConfig(config: unknown, key: string) {
  const value = record(config)[key];
  return typeof value === "string" ? value : "";
}

function stringList(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function providerOption(provider: string) {
  return providerOptions.find((option) => option.value === provider) ?? providerOptions[0];
}

function secretHandleName(handlesById: Map<string, SecretHandleRead>, handleId: string) {
  return handlesById.get(handleId)?.displayName ?? handleId.slice(0, 8);
}

function providerWebhookPath(connection: ChatProviderConnectionRead) {
  if (connection.provider === "telegram") {
    return getChatProviderWebhooksTelegramReceiveUrl(connection.id);
  }
  return getChatProviderWebhooksWhatsappLocalReceiveUrl(connection.id);
}

function providerSecretLabels(connection: ChatProviderConnectionRead) {
  const secretIds = connection.secretHandleIds ?? {};
  return Object.keys(secretIds).sort();
}

function providerCounts(connections: ChatProviderConnectionRead[]) {
  return {
    active: connections.filter((connection) => connection.isActive).length,
    telegram: connections.filter((connection) => connection.provider === "telegram").length,
    total: connections.length,
    whatsapp: connections.filter((connection) => connection.provider === "whatsapp_local")
      .length,
  };
}

function TestDialog({
  connection,
  onOpenChange,
  organizationId,
  open,
  workspaceId,
}: {
  connection: ChatProviderConnectionRead | null;
  onOpenChange: (open: boolean) => void;
  organizationId: string;
  open: boolean;
  workspaceId: string;
}) {
  const [text, setText] = useState("Summarize this workspace.");
  const [threadId, setThreadId] = useState("wardn-test");
  const [senderId, setSenderId] = useState("wardn-test");
  const [senderName, setSenderName] = useState("Wardn test");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<ChatProviderTestMessageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submitTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!connection || isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setError(null);
    setResult(null);

    try {
      const response = await workspaceChatProvidersTestMessage(
        organizationId,
        workspaceId,
        connection.id,
        {
          externalThreadId: threadId.trim() || "wardn-test",
          externalUserDisplayName: senderName.trim() || "Wardn test",
          externalUserId: senderId.trim() || "wardn-test",
          text: text.trim(),
        },
        { timeoutMs: 120_000 }
      );
      setResult(response);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Provider test message could not be sent."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const conversationHref =
    result?.conversationId && connection
      ? `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
          workspaceId
        )}/chat/${encodeURIComponent(result.conversationId)}`
      : "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Test Provider</DialogTitle>
          <DialogDescription>{connection?.name ?? "Workspace provider"}</DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={submitTest}>
          <div className="space-y-2">
            <Label htmlFor="provider-test-text">Message</Label>
            <textarea
              className="min-h-28 w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/15"
              id="provider-test-text"
              maxLength={4000}
              onChange={(event) => setText(event.target.value)}
              required
              value={text}
            />
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="provider-test-thread">Thread ID</Label>
              <Input
                id="provider-test-thread"
                maxLength={255}
                onChange={(event) => setThreadId(event.target.value)}
                value={threadId}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-test-sender">Sender ID</Label>
              <Input
                id="provider-test-sender"
                maxLength={255}
                onChange={(event) => setSenderId(event.target.value)}
                value={senderId}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-test-name">Sender name</Label>
              <Input
                id="provider-test-name"
                maxLength={255}
                onChange={(event) => setSenderName(event.target.value)}
                value={senderName}
              />
            </div>
          </div>

          {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
          {result ? (
            <div className="space-y-3 rounded-md border border-border bg-muted/30 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <CheckCircle2 className="size-4 text-emerald-600" />
                  {result.processed ? "Processed" : "Ignored"}
                </div>
                {conversationHref ? (
                  <Button asChild size="sm" variant="outline">
                    <Link href={conversationHref}>Open chat</Link>
                  </Button>
                ) : null}
              </div>
              {result.replyText ? (
                <div className="rounded-md border border-border bg-card px-3 py-2 text-sm leading-6">
                  {result.replyText}
                </div>
              ) : null}
              {result.message ? (
                <div className="text-xs text-muted-foreground">{result.message}</div>
              ) : null}
            </div>
          ) : null}

          <DialogFooter>
            <Button
              disabled={isSubmitting || text.trim().length === 0}
              type="submit"
            >
              {isSubmitting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Send className="size-4" />
              )}
              {isSubmitting ? "Testing" : "Run test"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ChatProvidersClient({
  connections,
  organizationId,
  secretHandles,
  secretStores,
  workspaceId,
}: ChatProvidersClientProps) {
  const router = useRouter();
  const counts = useMemo(() => providerCounts(connections), [connections]);
  const handlesById = useMemo(
    () => new Map(secretHandles.map((handle) => [handle.id, handle])),
    [secretHandles]
  );
  const activeSecretStores = secretStores.filter((store) => store.isActive);
  const [provider, setProvider] = useState<ProviderType>("whatsapp_local");
  const [name, setName] = useState("Personal WhatsApp");
  const [externalId, setExternalId] = useState("personal");
  const [displayName, setDisplayName] = useState("");
  const [secretStoreId, setSecretStoreId] = useState(activeSecretStores[0]?.id ?? "");
  const [webhookSecret, setWebhookSecret] = useState(randomSecret);
  const [botToken, setBotToken] = useState("");
  const [accountName, setAccountName] = useState("personal");
  const [outboundWebhookUrl, setOutboundWebhookUrl] = useState("");
  const [allowAllSenders, setAllowAllSenders] = useState(true);
  const [allowedSenderIds, setAllowedSenderIds] = useState("");
  const [allowedChatIds, setAllowedChatIds] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [busyConnectionId, setBusyConnectionId] = useState<string | null>(null);
  const [testConnection, setTestConnection] = useState<ChatProviderConnectionRead | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function applyProviderDefaults(nextProvider: ProviderType) {
    setProvider(nextProvider);
    setName(nextProvider === "telegram" ? "Workspace Telegram" : "Personal WhatsApp");
    setExternalId(nextProvider === "telegram" ? "workspace-bot" : "personal");
    setAccountName(nextProvider === "telegram" ? "" : "personal");
    setDisplayName("");
  }

  async function createProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isCreating) {
      return;
    }
    setIsCreating(true);
    setError(null);
    setNotice(null);

    try {
      const secretValues: Record<string, string> = {
        webhook_secret: webhookSecret.trim(),
      };
      if (provider === "telegram") {
        secretValues.bot_token = botToken.trim();
      } else {
        secretValues.outbound_secret = webhookSecret.trim();
      }

      const config =
        provider === "telegram"
          ? {
              allowAllSenders: allowAllSenders,
              allowedChatIds: stringList(allowedChatIds),
              allowedSenderIds: stringList(allowedSenderIds),
              replyOnUnsupportedMessages: false,
            }
          : {
              accountName: accountName.trim(),
              allowAllSenders: allowAllSenders,
              allowedChatIds: stringList(allowedChatIds),
              allowedSenderIds: stringList(allowedSenderIds),
              outboundWebhookUrl: outboundWebhookUrl.trim(),
              replyOnUnsupportedMessages: false,
            };

      const payload: ChatProviderConnectionCreate = {
        config,
        displayName: displayName.trim(),
        externalId: externalId.trim(),
        name: name.trim(),
        provider,
        secretStoreId,
        secretValues,
      };

      await workspaceChatProvidersCreate(organizationId, workspaceId, payload);
      setNotice("Provider connection created.");
      setWebhookSecret(randomSecret());
      setBotToken("");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider connection could not be saved.");
    } finally {
      setIsCreating(false);
    }
  }

  async function toggleConnection(connection: ChatProviderConnectionRead) {
    setBusyConnectionId(connection.id);
    setError(null);
    setNotice(null);
    try {
      await workspaceChatProvidersUpdate(organizationId, workspaceId, connection.id, {
        isActive: !connection.isActive,
      });
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
    setNotice(null);
    try {
      await workspaceChatProvidersDelete(organizationId, workspaceId, connection.id);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Provider connection could not be deleted."
      );
    } finally {
      setBusyConnectionId(null);
    }
  }

  async function copyWebhook(connection: ChatProviderConnectionRead) {
    try {
      await navigator.clipboard.writeText(providerWebhookPath(connection));
      setNotice("Webhook URL copied.");
    } catch {
      setError("Webhook URL could not be copied.");
    }
  }

  const canCreate =
    name.trim().length > 0 &&
    externalId.trim().length > 0 &&
    secretStoreId.length > 0 &&
    webhookSecret.trim().length > 0 &&
    (provider !== "telegram" || botToken.trim().length > 0);

  return (
    <div className="space-y-6">
      <section className="grid gap-3 md:grid-cols-4">
        {[
          { label: "Providers", value: counts.total, icon: Webhook },
          { label: "Active", value: counts.active, icon: Power },
          { label: "WhatsApp", value: counts.whatsapp, icon: Smartphone },
          { label: "Telegram", value: counts.telegram, icon: Bot },
        ].map((metric) => {
          const Icon = metric.icon;
          return (
            <div
              className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]"
              key={metric.label}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium text-muted-foreground">
                  {metric.label}
                </div>
                <Icon className="size-4 text-muted-foreground" />
              </div>
              <div className="mt-3 text-2xl font-semibold">{metric.value}</div>
            </div>
          );
        })}
      </section>

      {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
      {notice ? (
        <AsyncFeedback className="flex items-center gap-2" variant="success">
          <CheckCircle2 className="size-4" />
          {notice}
        </AsyncFeedback>
      ) : null}

      <div className="grid items-start gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <div>
                <CardTitle>Create Provider</CardTitle>
                <CardDescription>Workspace-scoped chat entrypoint.</CardDescription>
              </div>
              <div className="flex size-10 items-center justify-center rounded-md bg-muted text-primary">
                <Plus className="size-5" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <form className="space-y-5" onSubmit={createProvider}>
              <div className="grid grid-cols-2 gap-2">
                {providerOptions.map((option) => {
                  const Icon = option.icon;
                  return (
                    <button
                      className={cn(
                        "flex min-h-20 flex-col justify-between rounded-md border bg-card p-3 text-left text-sm transition-colors",
                        provider === option.value
                          ? "border-ring ring-2 ring-ring/15"
                          : "border-border hover:border-ring/40"
                      )}
                      key={option.value}
                      onClick={() => applyProviderDefaults(option.value)}
                      type="button"
                    >
                      <Icon className="size-4 text-muted-foreground" />
                      <span className="font-medium">{option.shortLabel}</span>
                    </button>
                  );
                })}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
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
                <div className="space-y-2">
                  <Label htmlFor="chat-provider-external">External ID</Label>
                  <Input
                    id="chat-provider-external"
                    maxLength={255}
                    onChange={(event) => setExternalId(event.target.value)}
                    required
                    value={externalId}
                  />
                </div>
              </div>

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

              {provider === "telegram" ? (
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
                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-account">Account name</Label>
                    <Input
                      id="chat-provider-account"
                      maxLength={100}
                      onChange={(event) => setAccountName(event.target.value)}
                      value={accountName}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-outbound-url">Outbound bridge URL</Label>
                    <Input
                      id="chat-provider-outbound-url"
                      maxLength={2048}
                      onChange={(event) => setOutboundWebhookUrl(event.target.value)}
                      placeholder="http://localhost:8787/send"
                      value={outboundWebhookUrl}
                    />
                  </div>
                </div>
              )}

              <label className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm">
                <input
                  checked={allowAllSenders}
                  className="size-4 accent-primary"
                  onChange={(event) => setAllowAllSenders(event.target.checked)}
                  type="checkbox"
                />
                Allow all senders
              </label>

              {!allowAllSenders ? (
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-senders">Sender IDs</Label>
                    <textarea
                      className="min-h-24 w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/15"
                      id="chat-provider-senders"
                      onChange={(event) => setAllowedSenderIds(event.target.value)}
                      value={allowedSenderIds}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="chat-provider-chats">Chat IDs</Label>
                    <textarea
                      className="min-h-24 w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/15"
                      id="chat-provider-chats"
                      onChange={(event) => setAllowedChatIds(event.target.value)}
                      value={allowedChatIds}
                    />
                  </div>
                </div>
              ) : null}

              <div className="flex justify-end">
                <Button disabled={!canCreate || isCreating} type="submit">
                  {isCreating ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Plus className="size-4" />
                  )}
                  {isCreating ? "Creating" : "Create provider"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <section className="space-y-3">
          {connections.length > 0 ? (
            connections.map((connection) => {
              const option = providerOption(connection.provider);
              const Icon = option.icon;
              const config = record(connection.config);
              const secretLabels = providerSecretLabels(connection);
              return (
                <article
                  className="rounded-md border border-border bg-card p-5 shadow-[var(--shadow-card)]"
                  key={connection.id}
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="flex size-9 items-center justify-center rounded-md bg-muted text-primary">
                          <Icon className="size-4" />
                        </div>
                        <div>
                          <h2 className="truncate text-base font-semibold">
                            {connection.name}
                          </h2>
                          <div className="mt-0.5 text-xs text-muted-foreground">
                            {option.label} / {connection.externalId}
                          </div>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={connection.isActive ? "success" : "secondary"}>
                          {connection.isActive ? "Active" : "Inactive"}
                        </Badge>
                        <Badge variant="outline">
                          {boolConfig(config, "allow_all_senders") ||
                          boolConfig(config, "allowAllSenders")
                            ? "All senders"
                            : "Restricted"}
                        </Badge>
                        {connection.provider === "whatsapp_local" &&
                        stringConfig(config, "outbound_webhook_url") ? (
                          <Badge variant="outline">Outbound bridge</Badge>
                        ) : null}
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <Button
                        aria-label={`Test ${connection.name}`}
                        onClick={() => setTestConnection(connection)}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        <FlaskConical className="size-4" />
                        Test
                      </Button>
                      <Button
                        aria-label={`Copy webhook URL for ${connection.name}`}
                        onClick={() => copyWebhook(connection)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Copy className="size-4" />
                      </Button>
                      <Button
                        aria-label={
                          connection.isActive
                            ? `Deactivate ${connection.name}`
                            : `Activate ${connection.name}`
                        }
                        disabled={busyConnectionId === connection.id}
                        onClick={() => toggleConnection(connection)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        {busyConnectionId === connection.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : connection.isActive ? (
                          <PowerOff className="size-4" />
                        ) : (
                          <Power className="size-4" />
                        )}
                      </Button>
                      <Button
                        aria-label={`Delete ${connection.name}`}
                        disabled={busyConnectionId === connection.id}
                        onClick={() => deleteConnection(connection)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(260px,0.8fr)]">
                    <div className="rounded-md border border-border bg-muted/30 p-3">
                      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                        <Webhook className="size-3.5" />
                        Webhook
                      </div>
                      <code className="block break-all text-xs text-foreground">
                        {providerWebhookPath(connection)}
                      </code>
                    </div>
                    <div className="rounded-md border border-border bg-muted/30 p-3">
                      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                        <ShieldCheck className="size-3.5" />
                        Secrets
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {secretLabels.length > 0 ? (
                          secretLabels.map((label) => {
                            const handleId = connection.secretHandleIds?.[label] ?? "";
                            return (
                              <Badge key={label} variant="outline">
                                {label}: {secretHandleName(handlesById, handleId)}
                              </Badge>
                            );
                          })
                        ) : (
                          <span className="text-xs text-muted-foreground">None</span>
                        )}
                      </div>
                    </div>
                  </div>
                </article>
              );
            })
          ) : (
            <div className="rounded-md border border-dashed border-border bg-card p-10 text-center">
              <div className="mx-auto mb-3 flex size-11 items-center justify-center rounded-md bg-muted text-primary">
                <Webhook className="size-5" />
              </div>
              <h2 className="text-base font-semibold">No providers</h2>
              <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-muted-foreground">
                Create a workspace provider to test chat from another app.
              </p>
            </div>
          )}
        </section>
      </div>

      <TestDialog
        connection={testConnection}
        onOpenChange={(open) => {
          if (!open) {
            setTestConnection(null);
          }
        }}
        open={Boolean(testConnection)}
        organizationId={organizationId}
        workspaceId={workspaceId}
      />
    </div>
  );
}
