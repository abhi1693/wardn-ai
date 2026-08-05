"use client";

import {
  CalendarClock,
  CheckCircle2,
  Clock3,
  MessageSquare,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Route,
  ShieldCheck,
  Trash2,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  ChatProviderConnectionRead,
  WorkspaceScheduledTaskCreate,
  WorkspaceScheduledTaskOutputRoute,
  WorkspaceScheduledTaskRead,
  WorkspaceScheduledTaskRunRead,
  WorkspaceScheduledTaskUpdate,
} from "@/lib/api/generated/model";
import {
  workspaceScheduledTasksCreate,
  workspaceScheduledTasksDelete,
  workspaceScheduledTasksRunNow,
  workspaceScheduledTasksUpdate,
} from "@/lib/api/generated/workspace-scheduled-tasks/workspace-scheduled-tasks";
import { cn } from "@/lib/utils";

type ScheduleType = "manual" | "interval" | "daily" | "weekly";
type ConversationPolicy = "reuse" | "new_each_run";

type ScheduledTasksClientProps = {
  connections: ChatProviderConnectionRead[];
  organizationId: string;
  runs: WorkspaceScheduledTaskRunRead[];
  tasks: WorkspaceScheduledTaskRead[];
  workspaceId: string;
};

type ProviderRouteOption = {
  connectionId: string;
  externalThreadId: string;
  key: string;
  label: string;
  provider: string;
  source: string;
};

type FormState = {
  name: string;
  instructions: string;
  scheduleType: ScheduleType;
  everyMinutes: string;
  time: string;
  weekday: string;
  timezone: string;
  selectedRoutes: string[];
  conversationPolicy: ConversationPolicy;
  isActive: boolean;
  maxAttempts: string;
};

const weekdays = [
  { label: "Monday", value: "0" },
  { label: "Tuesday", value: "1" },
  { label: "Wednesday", value: "2" },
  { label: "Thursday", value: "3" },
  { label: "Friday", value: "4" },
  { label: "Saturday", value: "5" },
  { label: "Sunday", value: "6" },
];

const timezoneAliases: Record<string, string> = {
  "Asia/Calcutta": "Asia/Kolkata",
};

function normalizeTimezone(value: string) {
  const timezone = value.trim() || "UTC";
  return timezoneAliases[timezone] ?? timezone;
}

function browserTimezone() {
  try {
    return normalizeTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  } catch {
    return "UTC";
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function configString(config: unknown, key: string, fallback: string) {
  const value = record(config)[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function configNumber(config: unknown, key: string, fallback: number) {
  const value = record(config)[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return String(fallback);
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

function providerLabel(provider: string) {
  if (provider === "whatsapp_local" || provider === "whatsapp") {
    return "WhatsApp";
  }
  if (provider === "telegram") {
    return "Telegram";
  }
  return "Provider";
}

function identityLabel(
  identity: NonNullable<ChatProviderConnectionRead["knownIdentities"]>[number]
) {
  return (
    identity.displayName?.trim() ||
    friendlyIdentityId(identity.externalUserId) ||
    friendlyIdentityId(identity.externalThreadId) ||
    "Conversation"
  );
}

function providerRouteOptions(connections: ChatProviderConnectionRead[]): ProviderRouteOption[] {
  return connections
    .filter((connection) => connection.isActive)
    .flatMap((connection) =>
      (connection.knownIdentities ?? []).map((identity) => ({
        connectionId: connection.id,
        externalThreadId: identity.externalThreadId,
        key: `${connection.id}:${identity.externalThreadId}`,
        label: identityLabel(identity),
        provider: connection.provider,
        source: `${providerLabel(connection.provider)} · ${connection.name}`,
      }))
    );
}

function outputRouteKey(route: WorkspaceScheduledTaskOutputRoute) {
  if (route.routeType === "chat") {
    return "chat";
  }
  return `${route.connectionId ?? ""}:${route.externalThreadId ?? ""}`;
}

function taskFormState(
  task: WorkspaceScheduledTaskRead | null,
  timezone: string
): FormState {
  if (!task) {
    return {
      name: "",
      instructions: "",
      scheduleType: "daily",
      everyMinutes: "60",
      time: "09:00",
      weekday: "0",
      timezone,
      selectedRoutes: ["chat"],
      conversationPolicy: "reuse",
      isActive: true,
      maxAttempts: "3",
    };
  }
  return {
    name: task.name,
    instructions: task.instructions,
    scheduleType: task.scheduleType as ScheduleType,
    everyMinutes: configNumber(task.scheduleConfig, "everyMinutes", 60),
    time: configString(task.scheduleConfig, "time", "09:00"),
    weekday: configNumber(task.scheduleConfig, "weekday", 0),
    timezone: task.timezone || timezone,
    selectedRoutes: (task.outputRoutes ?? []).map(outputRouteKey),
    conversationPolicy: task.conversationPolicy as ConversationPolicy,
    isActive: task.isActive,
    maxAttempts: String(task.maxAttempts || 3),
  };
}

function scheduleConfig(form: FormState): Record<string, unknown> {
  if (form.scheduleType === "manual") {
    return {};
  }
  if (form.scheduleType === "interval") {
    return { everyMinutes: Number(form.everyMinutes || 60) };
  }
  if (form.scheduleType === "weekly") {
    return { time: form.time || "09:00", weekday: Number(form.weekday || 0) };
  }
  return { time: form.time || "09:00" };
}

function formatDate(value?: string | null) {
  if (!value) {
    return "Not scheduled";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function shortDate(value?: string | null) {
  if (!value) {
    return "None";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
  }).format(date);
}

function scheduleLabel(task: WorkspaceScheduledTaskRead) {
  const config = record(task.scheduleConfig);
  if (task.scheduleType === "manual") {
    return "Manual";
  }
  if (task.scheduleType === "interval") {
    return `Every ${String(config.everyMinutes ?? 60)} min`;
  }
  if (task.scheduleType === "weekly") {
    const weekday = weekdays.find((day) => day.value === String(config.weekday ?? "0"));
    return `${weekday?.label ?? "Weekly"} at ${String(config.time ?? "09:00")}`;
  }
  return `Daily at ${String(config.time ?? "09:00")}`;
}

function statusVariant(status: string) {
  if (status === "succeeded" || status === "sent") {
    return "success" as const;
  }
  if (status === "failed") {
    return "destructive" as const;
  }
  if (status === "waiting_confirmation" || status === "running" || status === "queued") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function statusLabel(status: string) {
  if (!status) {
    return "Never run";
  }
  return status.replaceAll("_", " ");
}

function taskOutputLabels(
  task: WorkspaceScheduledTaskRead,
  providerOptions: ProviderRouteOption[]
) {
  return (task.outputRoutes ?? [{ routeType: "chat" }]).map((route) => {
    if (route.routeType === "chat") {
      return "Built-in chat";
    }
    const option = providerOptions.find((candidate) => candidate.key === outputRouteKey(route));
    return option ? `${option.source} · ${option.label}` : "Provider conversation";
  });
}

function buildOutputRoutes(
  selectedRoutes: string[],
  providerOptions: ProviderRouteOption[]
): WorkspaceScheduledTaskOutputRoute[] {
  const routes: WorkspaceScheduledTaskOutputRoute[] = [];
  if (selectedRoutes.includes("chat")) {
    routes.push({ routeType: "chat" });
  }
  for (const key of selectedRoutes) {
    if (key === "chat") {
      continue;
    }
    const option = providerOptions.find((candidate) => candidate.key === key);
    if (!option) {
      continue;
    }
    routes.push({
      connectionId: option.connectionId,
      displayName: option.label,
      externalThreadId: option.externalThreadId,
      routeType: "chat_provider",
    });
  }
  return routes.length ? routes : [{ routeType: "chat" }];
}

function metricValue(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function taskHref(organizationId: string, workspaceId: string, conversationId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/chat/${encodeURIComponent(conversationId)}`;
}

function runHref(organizationId: string, workspaceId: string, runId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/agent-runs/${encodeURIComponent(runId)}`;
}

function TaskDialog({
  editingTask,
  form,
  isSaving,
  onChange,
  onOpenChange,
  onSubmit,
  open,
  providerOptions,
}: {
  editingTask: WorkspaceScheduledTaskRead | null;
  form: FormState;
  isSaving: boolean;
  onChange: (next: FormState) => void;
  onOpenChange: (open: boolean) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  open: boolean;
  providerOptions: ProviderRouteOption[];
}) {
  function toggleRoute(key: string) {
    const selected = new Set(form.selectedRoutes);
    if (selected.has(key)) {
      selected.delete(key);
    } else {
      selected.add(key);
    }
    onChange({ ...form, selectedRoutes: Array.from(selected) });
  }

  const canSave = Boolean(form.name.trim() && form.instructions.trim() && form.timezone.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{editingTask ? "Edit scheduled task" : "New scheduled task"}</DialogTitle>
          <DialogDescription>Workspace agent trigger and delivery route.</DialogDescription>
        </DialogHeader>

        <form className="space-y-5" onSubmit={onSubmit}>
          <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
            <div className="space-y-2">
              <Label htmlFor="scheduled-task-name">Name</Label>
              <Input
                id="scheduled-task-name"
                maxLength={120}
                onChange={(event) => onChange({ ...form, name: event.target.value })}
                required
                value={form.name}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scheduled-task-active">State</Label>
              <button
                className={cn(
                  "flex h-9 w-full items-center justify-between rounded-md border px-3 text-sm",
                  form.isActive
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-border bg-muted text-muted-foreground"
                )}
                id="scheduled-task-active"
                onClick={() => onChange({ ...form, isActive: !form.isActive })}
                type="button"
              >
                <span>{form.isActive ? "Active" : "Paused"}</span>
                {form.isActive ? <CheckCircle2 className="size-4" /> : <Pause className="size-4" />}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="scheduled-task-instructions">Instructions</Label>
            <textarea
              className="min-h-32 w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/15 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60"
              id="scheduled-task-instructions"
              maxLength={20000}
              onChange={(event) => onChange({ ...form, instructions: event.target.value })}
              required
              value={form.instructions}
            />
          </div>

          <div className="grid gap-4 rounded-md border border-border p-3">
            <div className="grid gap-2 sm:grid-cols-4">
              {(["daily", "weekly", "interval", "manual"] as ScheduleType[]).map((type) => (
                <button
                  className={cn(
                    "flex h-10 items-center justify-center rounded-md border text-sm font-medium transition-colors",
                    form.scheduleType === type
                      ? "border-ring bg-sidebar-accent text-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground"
                  )}
                  key={type}
                  onClick={() => onChange({ ...form, scheduleType: type })}
                  type="button"
                >
                  {type.replace("_", " ")}
                </button>
              ))}
            </div>

            {form.scheduleType === "interval" ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-interval">Every minutes</Label>
                  <Input
                    id="scheduled-task-interval"
                    min={1}
                    max={10080}
                    onChange={(event) =>
                      onChange({ ...form, everyMinutes: event.target.value })
                    }
                    type="number"
                    value={form.everyMinutes}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-timezone-interval">Timezone</Label>
                  <Input
                    id="scheduled-task-timezone-interval"
                    onChange={(event) => onChange({ ...form, timezone: event.target.value })}
                    value={form.timezone}
                  />
                </div>
              </div>
            ) : null}

            {form.scheduleType === "daily" ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-time">Time</Label>
                  <Input
                    id="scheduled-task-time"
                    onChange={(event) => onChange({ ...form, time: event.target.value })}
                    type="time"
                    value={form.time}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-timezone-daily">Timezone</Label>
                  <Input
                    id="scheduled-task-timezone-daily"
                    onChange={(event) => onChange({ ...form, timezone: event.target.value })}
                    value={form.timezone}
                  />
                </div>
              </div>
            ) : null}

            {form.scheduleType === "weekly" ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-weekday">Day</Label>
                  <Select
                    onValueChange={(value) => onChange({ ...form, weekday: value })}
                    value={form.weekday}
                  >
                    <SelectTrigger id="scheduled-task-weekday">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {weekdays.map((weekday) => (
                        <SelectItem key={weekday.value} value={weekday.value}>
                          {weekday.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-weekly-time">Time</Label>
                  <Input
                    id="scheduled-task-weekly-time"
                    onChange={(event) => onChange({ ...form, time: event.target.value })}
                    type="time"
                    value={form.time}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-timezone-weekly">Timezone</Label>
                  <Input
                    id="scheduled-task-timezone-weekly"
                    onChange={(event) => onChange({ ...form, timezone: event.target.value })}
                    value={form.timezone}
                  />
                </div>
              </div>
            ) : null}

            {form.scheduleType === "manual" ? (
              <div className="flex items-center gap-3 rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
                <Play className="size-4" />
                <span>Run from the task card when needed.</span>
              </div>
            ) : null}
          </div>

          <div className="grid gap-4 md:grid-cols-[1fr_220px]">
            <div className="rounded-md border border-border">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Route className="size-4 text-muted-foreground" />
                  Output
                </div>
                <Badge variant="secondary">{form.selectedRoutes.length}</Badge>
              </div>
              <div className="grid gap-2 p-3">
                <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-border bg-card px-3 text-sm">
                  <input
                    checked={form.selectedRoutes.includes("chat")}
                    className="size-4"
                    onChange={() => toggleRoute("chat")}
                    type="checkbox"
                  />
                  <MessageSquare className="size-4 text-muted-foreground" />
                  <span>Built-in chat</span>
                </label>
                {providerOptions.map((option) => (
                  <label
                    className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-border bg-card px-3 text-sm"
                    key={option.key}
                  >
                    <input
                      checked={form.selectedRoutes.includes(option.key)}
                      className="size-4"
                      onChange={() => toggleRoute(option.key)}
                      type="checkbox"
                    />
                    <Webhook className="size-4 text-muted-foreground" />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{option.label}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {option.source}
                      </span>
                    </span>
                  </label>
                ))}
                {providerOptions.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                    Connect a provider and receive a message before selecting an external route.
                  </div>
                ) : null}
              </div>
            </div>

            <div className="grid gap-3">
              <div className="space-y-2">
                <Label htmlFor="scheduled-task-conversation-policy">Chat history</Label>
                <Select
                  onValueChange={(value) =>
                    onChange({ ...form, conversationPolicy: value as ConversationPolicy })
                  }
                  value={form.conversationPolicy}
                >
                  <SelectTrigger id="scheduled-task-conversation-policy">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="reuse">Reuse task chat</SelectItem>
                    <SelectItem value="new_each_run">New chat each run</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="scheduled-task-max-attempts">Attempts</Label>
                <Input
                  id="scheduled-task-max-attempts"
                  max={10}
                  min={1}
                  onChange={(event) => onChange({ ...form, maxAttempts: event.target.value })}
                  type="number"
                  value={form.maxAttempts}
                />
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button onClick={() => onOpenChange(false)} type="button" variant="outline">
              Cancel
            </Button>
            <Button disabled={!canSave || isSaving} type="submit">
              {isSaving ? <RefreshCw className="size-4 animate-spin" /> : <Plus className="size-4" />}
              {editingTask ? "Save task" : "Create task"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ScheduledTasksClient({
  connections,
  organizationId,
  runs,
  tasks,
  workspaceId,
}: ScheduledTasksClientProps) {
  const router = useRouter();
  const providerOptions = useMemo(() => providerRouteOptions(connections), [connections]);
  const timezone = useMemo(() => browserTimezone(), []);
  const [nowMs] = useState(() => Date.now());
  const [taskRows, setTaskRows] = useState(tasks);
  const [runRows, setRunRows] = useState(runs);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<WorkspaceScheduledTaskRead | null>(null);
  const [form, setForm] = useState<FormState>(() => taskFormState(null, timezone));
  const [isSaving, setIsSaving] = useState(false);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ variant: "success" | "error"; text: string } | null>(
    null
  );

  const stats = useMemo(() => {
    const day = 24 * 60 * 60 * 1000;
    return {
      active: taskRows.filter((task) => task.isActive).length,
      dueSoon: taskRows.filter((task) => {
        if (!task.nextRunAt || !task.isActive) {
          return false;
        }
        const next = new Date(task.nextRunAt).getTime();
        return Number.isFinite(next) && next - nowMs <= day && next >= nowMs - 60_000;
      }).length,
      failed: taskRows.filter((task) => task.lastStatus === "failed").length,
      waiting: runRows.filter((run) => run.status === "waiting_confirmation").length,
    };
  }, [nowMs, runRows, taskRows]);

  function openCreateDialog() {
    setEditingTask(null);
    setForm(taskFormState(null, timezone));
    setDialogOpen(true);
  }

  function openEditDialog(task: WorkspaceScheduledTaskRead) {
    setEditingTask(task);
    setForm(taskFormState(task, timezone));
    setDialogOpen(true);
  }

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setFeedback(null);
    const payload = {
      conversationPolicy: form.conversationPolicy,
      instructions: form.instructions.trim(),
      isActive: form.isActive,
      maxAttempts: Number(form.maxAttempts || 3),
      name: form.name.trim(),
      outputRoutes: buildOutputRoutes(form.selectedRoutes, providerOptions),
      scheduleConfig: scheduleConfig(form),
      scheduleType: form.scheduleType,
      timezone: normalizeTimezone(form.timezone),
    } satisfies WorkspaceScheduledTaskCreate;

    try {
      if (editingTask) {
        const updatePayload: WorkspaceScheduledTaskUpdate = payload;
        const updated = await workspaceScheduledTasksUpdate(
          organizationId,
          workspaceId,
          editingTask.id,
          updatePayload
        );
        setTaskRows((current) =>
          current.map((task) => (task.id === updated.id ? updated : task))
        );
        setFeedback({ variant: "success", text: "Scheduled task updated." });
      } else {
        const created = await workspaceScheduledTasksCreate(
          organizationId,
          workspaceId,
          payload
        );
        setTaskRows((current) => [created, ...current]);
        setFeedback({ variant: "success", text: "Scheduled task created." });
      }
      setDialogOpen(false);
      router.refresh();
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Scheduled task request failed.",
      });
    } finally {
      setIsSaving(false);
    }
  }

  async function toggleTask(task: WorkspaceScheduledTaskRead) {
    setBusyTaskId(task.id);
    setFeedback(null);
    try {
      const updated = await workspaceScheduledTasksUpdate(organizationId, workspaceId, task.id, {
        isActive: !task.isActive,
      });
      setTaskRows((current) =>
        current.map((row) => (row.id === updated.id ? updated : row))
      );
      router.refresh();
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Could not update scheduled task.",
      });
    } finally {
      setBusyTaskId(null);
    }
  }

  async function runTaskNow(task: WorkspaceScheduledTaskRead) {
    setBusyTaskId(task.id);
    setFeedback(null);
    try {
      const run = await workspaceScheduledTasksRunNow(organizationId, workspaceId, task.id);
      setRunRows((current) => [run, ...current].slice(0, 12));
      setTaskRows((current) =>
        current.map((row) =>
          row.id === task.id
            ? { ...row, lastRunAt: run.scheduledFor, lastStatus: run.status }
            : row
        )
      );
      setFeedback({ variant: "success", text: "Scheduled task queued." });
      router.refresh();
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Could not queue scheduled task.",
      });
    } finally {
      setBusyTaskId(null);
    }
  }

  async function deleteTask(task: WorkspaceScheduledTaskRead) {
    if (!window.confirm(`Delete ${task.name}?`)) {
      return;
    }
    setBusyTaskId(task.id);
    setFeedback(null);
    try {
      await workspaceScheduledTasksDelete(organizationId, workspaceId, task.id);
      setTaskRows((current) => current.filter((row) => row.id !== task.id));
      router.refresh();
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Could not delete scheduled task.",
      });
    } finally {
      setBusyTaskId(null);
    }
  }

  return (
    <div className="space-y-5">
      <section className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-muted-foreground">Active</div>
              <CalendarClock className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(stats.active)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-muted-foreground">Due in 24h</div>
              <Clock3 className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(stats.dueSoon)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-muted-foreground">Waiting approval</div>
              <ShieldCheck className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(stats.waiting)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-muted-foreground">Failed</div>
              <MoreHorizontal className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(stats.failed)}</div>
          </CardContent>
        </Card>
      </section>

      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Tasks</h2>
          <div className="text-sm text-muted-foreground">
            Workspace assistant schedules and delivery routes.
          </div>
        </div>
        <Button onClick={openCreateDialog}>
          <Plus className="size-4" />
          New task
        </Button>
      </div>

      {feedback ? (
        <AsyncFeedback variant={feedback.variant}>{feedback.text}</AsyncFeedback>
      ) : null}

      {taskRows.length > 0 ? (
        <section className="grid gap-3 xl:grid-cols-2">
          {taskRows.map((task) => {
            const outputs = taskOutputLabels(task, providerOptions);
            const busy = busyTaskId === task.id;
            return (
              <Card key={task.id}>
                <CardHeader className="gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="truncate">{task.name}</CardTitle>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <Badge variant={task.isActive ? "success" : "secondary"}>
                          {task.isActive ? "Active" : "Paused"}
                        </Badge>
                        <Badge variant="outline">{scheduleLabel(task)}</Badge>
                        <Badge variant={statusVariant(task.lastStatus)}>
                          {statusLabel(task.lastStatus)}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Button
                        disabled={busy}
                        onClick={() => runTaskNow(task)}
                        size="icon"
                        title="Run now"
                        variant="outline"
                      >
                        <Play className="size-4" />
                      </Button>
                      <Button
                        disabled={busy}
                        onClick={() => openEditDialog(task)}
                        size="icon"
                        title="Edit"
                        variant="outline"
                      >
                        <Pencil className="size-4" />
                      </Button>
                      <Button
                        disabled={busy}
                        onClick={() => toggleTask(task)}
                        size="icon"
                        title={task.isActive ? "Pause" : "Resume"}
                        variant="outline"
                      >
                        {task.isActive ? <Pause className="size-4" /> : <Play className="size-4" />}
                      </Button>
                      <Button
                        disabled={busy}
                        onClick={() => deleteTask(task)}
                        size="icon"
                        title="Delete"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="line-clamp-2 text-sm leading-6 text-muted-foreground">
                    {task.instructions}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <div className="text-xs text-muted-foreground">Next</div>
                      <div className="mt-1 text-sm font-medium">{shortDate(task.nextRunAt)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Last run</div>
                      <div className="mt-1 text-sm font-medium">{shortDate(task.lastRunAt)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Attempts</div>
                      <div className="mt-1 text-sm font-medium">{task.maxAttempts}</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {outputs.map((output) => (
                      <Badge key={output} variant="secondary">
                        {output}
                      </Badge>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    {task.conversationId ? (
                      <Button asChild size="sm" variant="outline">
                        <Link href={taskHref(organizationId, workspaceId, task.conversationId)}>
                          <MessageSquare className="size-4" />
                          Chat
                        </Link>
                      </Button>
                    ) : null}
                    {task.lastAgentRunId ? (
                      <Button asChild size="sm" variant="outline">
                        <Link href={runHref(organizationId, workspaceId, task.lastAgentRunId)}>
                          <Clock3 className="size-4" />
                          Last run
                        </Link>
                      </Button>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </section>
      ) : (
        <Card>
          <CardContent className="flex min-h-56 flex-col items-center justify-center text-center">
            <div className="flex size-11 items-center justify-center rounded-md border border-border bg-muted">
              <CalendarClock className="size-5 text-muted-foreground" />
            </div>
            <div className="mt-4 text-base font-semibold">No scheduled tasks</div>
            <div className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">
              Create a task that wakes the workspace assistant and sends the result to chat.
            </div>
            <Button className="mt-4" onClick={openCreateDialog}>
              <Plus className="size-4" />
              New task
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {runRows.length > 0 ? (
            runRows.map((run) => {
              const task = taskRows.find((row) => row.id === run.taskId);
              return (
                <div
                  className="grid gap-3 rounded-md border border-border px-3 py-2 text-sm md:grid-cols-[1fr_150px_150px_120px]"
                  key={run.id}
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">{task?.name ?? "Scheduled task"}</div>
                    <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                      {run.id}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Scheduled</div>
                    <div className="mt-0.5">{formatDate(run.scheduledFor)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Output</div>
                    <div className="mt-0.5">
                      {String(record(run.deliverySummary).sent ?? 0)} sent
                      {Number(record(run.deliverySummary).failed ?? 0) > 0
                        ? `, ${String(record(run.deliverySummary).failed)} failed`
                        : ""}
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 md:justify-end">
                    <Badge variant={statusVariant(run.status)}>{statusLabel(run.status)}</Badge>
                    {run.agentRunId ? (
                      <Button asChild size="icon" title="Open run" variant="outline">
                        <Link href={runHref(organizationId, workspaceId, run.agentRunId)}>
                          <Clock3 className="size-4" />
                        </Link>
                      </Button>
                    ) : null}
                  </div>
                </div>
              );
            })
          ) : (
            <div className="flex min-h-28 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
              No scheduled task runs yet.
            </div>
          )}
        </CardContent>
      </Card>

      <TaskDialog
        editingTask={editingTask}
        form={form}
        isSaving={isSaving}
        onChange={setForm}
        onOpenChange={setDialogOpen}
        onSubmit={submitTask}
        open={dialogOpen}
        providerOptions={providerOptions}
      />
    </div>
  );
}
