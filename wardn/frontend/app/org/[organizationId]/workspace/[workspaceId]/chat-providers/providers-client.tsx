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
import { useCallback, useEffect, useMemo, useState } from "react";

import { StatusDot } from "@/components/atoms/status-dot";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { Badge } from "@/components/atoms/badge";
import { QRCode } from "@/components/atoms/qr-code";
import { Button } from "@/components/atoms/button";
import { Card, CardContent, CardHeader } from "@/components/atoms/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/atoms/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { SearchField } from "@/components/molecules/search-field";
import { useUrlState } from "@/hooks/use-url-state";
import { useVisibilityPolling } from "@/hooks/use-visibility-polling";
import type {
  ChatProviderConnectionRead,
  ChatProviderPairingStatusResponse,
} from "@/lib/api/generated/model";
import {
  workspaceChatProvidersDelete,
  workspaceChatProvidersPairingStatus,
  workspaceChatProvidersResetPairingQr,
  workspaceChatProvidersUpdate,
} from "@/lib/api/generated/workspace-chat-providers/workspace-chat-providers";
import { formatUserDateTime } from "@/lib/date-time";
import { cn } from "@/lib/utils";

type ProviderType = "whatsapp_local" | "telegram" | "slack";

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
  {
    value: "slack",
    label: "Slack app",
    shortLabel: "Slack",
    icon: MessageCircle,
  },
];

const needsSetupStatuses = new Set(["not_configured", "needs_pairing", "error"]);

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

function providerOption(provider: string) {
  return providerOptions.find((option) => option.value === provider) ?? providerOptions[0];
}

function runtimeSessionLabel(provider: string) {
  if (provider === "slack") {
    return "Team";
  }
  if (provider === "telegram") {
    return "Bot";
  }
  return "Session";
}

function runtimeBridgeLabel(provider: string, bridgeUrl: string, appId = "") {
  if (provider === "whatsapp_local") {
    return displayHost(bridgeUrl);
  }
  if (provider === "slack") {
    return appId ? `Slack Socket Mode (${appId})` : "Slack Socket Mode";
  }
  if (provider === "telegram") {
    return "Telegram API";
  }
  return "Provider API";
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
              <QRCode
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
  const [connectionOverrides, setConnectionOverrides] = useState<
    Record<string, ChatProviderConnectionRead>
  >({});
  const [deletedConnectionIds, setDeletedConnectionIds] = useState<string[]>([]);
  const [search, setSearch] = useUrlState("providers-query");
  const [providerFilter, setProviderFilter] = useUrlState("providers-type", "all");
  const [statusFilter, setStatusFilter] = useUrlState("providers-status", "all");
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
        const matchesProvider = providerFilter === "all" || connection.provider === providerFilter;
        const needsSetup = connectionNeedsSetup(connection, pairingStatuses[connection.id]);
        const matchesStatus =
          statusFilter === "all" ||
          (statusFilter === "setup" && needsSetup) ||
          (statusFilter === "active" && connection.isActive && !needsSetup) ||
          (statusFilter === "paused" && !connection.isActive);
        return matchesQuery && matchesProvider && matchesStatus;
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
  }, [localConnections, pairingStatuses, providerFilter, search, statusFilter]);

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

  useVisibilityPolling({
    enabled: Boolean(
      pairingOpen &&
        pairingConnection &&
        activePairingStatus?.qrPayload &&
        activePairingStatus.status !== "connected"
    ),
    intervalMs: 3_000,
    maxIntervalMs: 24_000,
    poll: async (signal) => {
      if (!pairingConnection) {
        return;
      }
      const status = await workspaceChatProvidersPairingStatus(
        organizationId,
        workspaceId,
        pairingConnection.id,
        { signal, timeoutMs: 15_000 }
      );
      setPairingStatuses((current) => ({
        ...current,
        [pairingConnection.id]: mergePairingStatus(
          current[pairingConnection.id],
          status,
          { preserveQr: true }
        ),
      }));
    },
  });

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
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
          <SearchField
            aria-label="Search providers"
            className="min-w-0 sm:w-[260px]"
            label={null}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search providers"
            value={search}
          />
          <Select onValueChange={setProviderFilter} value={providerFilter}>
            <SelectTrigger aria-label="Filter providers by type" className="w-[150px]">
              <SelectValue placeholder="All providers" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All providers</SelectItem>
              {providerOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.shortLabel}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select onValueChange={setStatusFilter} value={statusFilter}>
            <SelectTrigger aria-label="Filter providers by status" className="w-[140px]">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="setup">Needs setup</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
            </SelectContent>
          </Select>
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
            const slackAppId = stringConfig(config, "app_id", "appId");
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
                        <div className="truncate text-xs text-muted-foreground">
                          {runtimeSessionLabel(connection.provider)}
                        </div>
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
                          {runtimeBridgeLabel(
                            connection.provider,
                            effectiveBridgeBaseUrl,
                            slackAppId
                          )}
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
                    <ConfirmActionDialog
                      actionLabel="Delete provider"
                      description="Incoming messages and scheduled deliveries through this connection will stop immediately."
                      onConfirm={() => deleteConnection(connection)}
                      title={`Delete ${connection.name}?`}
                      variant="destructive"
                    >
                      <Button
                        aria-label={`Delete ${connection.name}`}
                        disabled={isBusy}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </ConfirmActionDialog>
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
