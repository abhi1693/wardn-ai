"use client";

import {
  ArrowLeft,
  BellRing,
  CalendarClock,
  CalendarDays,
  CalendarRange,
  CheckCircle2,
  Clock3,
  Eye,
  MessageSquare,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Route,
  Save,
  Send,
  ShieldCheck,
  TimerReset,
  Trash2,
  Webhook,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

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
  ChatProviderConnectionRead,
  WorkspaceScheduledTaskCreate,
  WorkspaceScheduledTaskDeliveryRead,
  WorkspaceScheduledTaskMonitoringConfig,
  WorkspaceScheduledTaskOutputRoute,
  WorkspaceScheduledTaskRead,
  WorkspaceScheduledTaskRunRead,
  WorkspaceScheduledTaskScheduleCreate,
  WorkspaceScheduledTaskScheduleUpdate,
  WorkspaceScheduledTaskUpdate,
} from "@/lib/api/generated/model";
import {
  workspaceScheduledTasksCreate,
  workspaceScheduledTasksDelete,
  workspaceScheduledTasksPreview,
  workspaceScheduledTasksRetryDelivery,
  workspaceScheduledTasksRunNow,
  workspaceScheduledTasksTestRoute,
  workspaceScheduledTasksUpdate,
} from "@/lib/api/generated/workspace-scheduled-tasks/workspace-scheduled-tasks";
import { cn } from "@/lib/utils";

type ScheduleType =
  | "manual"
  | "interval"
  | "daily"
  | "weekly"
  | "weekdays"
  | "monthly"
  | "cron"
  | "multiple";
type ScheduleEntryType = "interval" | "daily" | "weekly" | "weekdays" | "monthly" | "cron";
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

type RouteTestStatus = "idle" | "testing" | "sent" | "failed";

type RouteTestState = {
  error?: string;
  status: RouteTestStatus;
};

type FormState = {
  name: string;
  instructions: string;
  schedules: ScheduleDraft[];
  selectedRoutes: string[];
  notificationRoutes: string[];
  approvalRoutes: string[];
  notificationRules: {
    onDeliveryFailure: boolean;
    onFailure: boolean;
    onMeaningfulUpdate: boolean;
    onNoOutput: boolean;
    onWaitingApproval: boolean;
  };
  monitoringConfig: {
    baselineOnFirstRun: boolean;
    deliverOnChangeOnly: boolean;
    enabled: boolean;
    notifyOnChange: boolean;
    stopAfterChangeCount: string;
    stopAfterFirstChange: boolean;
    stopAfterRunCount: string;
    stopAfterUnchangedCount: string;
  };
  resetMonitoringState: boolean;
  conversationPolicy: ConversationPolicy;
  isActive: boolean;
  maxAttempts: string;
};

type ScheduleDraft = {
  cronExpression: string;
  endsAt: string;
  everyMinutes: string;
  id?: string;
  isActive: boolean;
  key: string;
  monthDays: string[];
  name: string;
  scheduleType: ScheduleEntryType;
  startsAt: string;
  timeInput: string;
  times: string[];
  timezone: string;
  weekdays: string[];
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

const schedulePresets: { label: string; type: ScheduleEntryType; icon: typeof Clock3 }[] = [
  { label: "Daily", type: "daily", icon: Clock3 },
  { label: "Weekdays", type: "weekdays", icon: CalendarDays },
  { label: "Weekly", type: "weekly", icon: CalendarClock },
  { label: "Monthly", type: "monthly", icon: CalendarRange },
  { label: "Interval", type: "interval", icon: TimerReset },
  { label: "Cron", type: "cron", icon: Clock3 },
];

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

function configNumberList(config: unknown, pluralKey: string, singularKey: string, fallback: number[]) {
  const source = record(config);
  const rawValue = source[pluralKey] ?? source[singularKey];
  const values = Array.isArray(rawValue) ? rawValue : rawValue === undefined ? fallback : [rawValue];
  const normalized = values
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value))
    .map((value) => String(value));
  return normalized.length ? Array.from(new Set(normalized)) : fallback.map(String);
}

function configTimes(config: unknown, fallback = ["09:00"]) {
  const source = record(config);
  const rawValue = source.times ?? source.time;
  const values = Array.isArray(rawValue) ? rawValue : typeof rawValue === "string" ? [rawValue] : fallback;
  const normalized = values
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter(Boolean);
  return normalized.length ? Array.from(new Set(normalized)).sort() : fallback;
}

function datetimeLocalValue(value?: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function datetimeLocalToIso(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const date = new Date(trimmed);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function scheduleKey() {
  return `schedule-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function newScheduleDraft(type: ScheduleEntryType, timezone: string): ScheduleDraft {
  return {
    cronExpression: type === "cron" ? "0 9 * * 1-5" : "",
    endsAt: "",
    everyMinutes: "60",
    isActive: true,
    key: scheduleKey(),
    monthDays: ["1"],
    name: "",
    scheduleType: type,
    startsAt: "",
    timeInput: "09:00",
    times: type === "interval" || type === "cron" ? [] : ["09:00"],
    timezone,
    weekdays: type === "weekdays" ? ["0", "1", "2", "3", "4"] : ["0"],
  };
}

function draftFromSchedule(
  schedule: NonNullable<WorkspaceScheduledTaskRead["schedules"]>[number],
  timezone: string
): ScheduleDraft {
  const scheduleType = schedule.scheduleType as ScheduleEntryType;
  return {
    cronExpression: configString(schedule.scheduleConfig, "expression", "0 9 * * 1-5"),
    endsAt: datetimeLocalValue(schedule.endsAt),
    everyMinutes: configNumber(schedule.scheduleConfig, "everyMinutes", 60),
    id: schedule.id,
    isActive: schedule.isActive,
    key: schedule.id,
    monthDays: configNumberList(schedule.scheduleConfig, "monthDays", "monthDay", [1]),
    name: schedule.name ?? "",
    scheduleType,
    startsAt: datetimeLocalValue(schedule.startsAt),
    timeInput: configTimes(schedule.scheduleConfig)[0] ?? "09:00",
    times:
      scheduleType === "interval" || scheduleType === "cron"
        ? []
        : configTimes(schedule.scheduleConfig),
    timezone: schedule.timezone || timezone,
    weekdays:
      scheduleType === "weekdays"
        ? ["0", "1", "2", "3", "4"]
        : configNumberList(schedule.scheduleConfig, "weekdays", "weekday", [0]),
  };
}

function legacyDraftFromTask(task: WorkspaceScheduledTaskRead, timezone: string): ScheduleDraft[] {
  const scheduleType = task.scheduleType as ScheduleType;
  if (scheduleType === "manual" || scheduleType === "multiple") {
    return [];
  }
  return [
    draftFromSchedule(
      {
        createdAt: task.createdAt,
        id: task.id,
        isActive: true,
        name: "",
        nextRunAt: task.nextRunAt,
        scheduleConfig: task.scheduleConfig,
        scheduleType,
        sortOrder: 0,
        taskId: task.id,
        timezone: task.timezone,
        updatedAt: task.updatedAt,
      },
      timezone
    ),
  ];
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

function routeKeys(routes?: WorkspaceScheduledTaskOutputRoute[] | null) {
  const keys = (routes ?? []).map(outputRouteKey).filter(Boolean);
  return keys.length ? keys : ["chat"];
}

function defaultNotificationRules() {
  return {
    onDeliveryFailure: true,
    onFailure: true,
    onMeaningfulUpdate: false,
    onNoOutput: false,
    onWaitingApproval: true,
  };
}

function defaultMonitoringConfig() {
  return {
    baselineOnFirstRun: true,
    deliverOnChangeOnly: true,
    enabled: false,
    notifyOnChange: true,
    stopAfterChangeCount: "",
    stopAfterFirstChange: false,
    stopAfterRunCount: "",
    stopAfterUnchangedCount: "",
  };
}

function monitoringFormConfig(task: WorkspaceScheduledTaskRead | null) {
  const defaults = defaultMonitoringConfig();
  const config = record(task?.monitoringConfig);
  const stopConditions = record(config.stopConditions);
  return {
    ...defaults,
    baselineOnFirstRun:
      typeof config.baselineOnFirstRun === "boolean"
        ? config.baselineOnFirstRun
        : defaults.baselineOnFirstRun,
    deliverOnChangeOnly:
      typeof config.deliverOnChangeOnly === "boolean"
        ? config.deliverOnChangeOnly
        : defaults.deliverOnChangeOnly,
    enabled: typeof config.enabled === "boolean" ? config.enabled : defaults.enabled,
    notifyOnChange:
      typeof config.notifyOnChange === "boolean"
        ? config.notifyOnChange
        : defaults.notifyOnChange,
    stopAfterChangeCount:
      stopConditions.afterChangeCount === null || stopConditions.afterChangeCount === undefined
        ? ""
        : String(stopConditions.afterChangeCount),
    stopAfterFirstChange:
      typeof stopConditions.afterFirstChange === "boolean"
        ? stopConditions.afterFirstChange
        : defaults.stopAfterFirstChange,
    stopAfterRunCount:
      stopConditions.afterRunCount === null || stopConditions.afterRunCount === undefined
        ? ""
        : String(stopConditions.afterRunCount),
    stopAfterUnchangedCount:
      stopConditions.afterUnchangedCount === null || stopConditions.afterUnchangedCount === undefined
        ? ""
        : String(stopConditions.afterUnchangedCount),
  };
}

function optionalPositiveInteger(value: string) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function monitoringPayload(form: FormState): WorkspaceScheduledTaskMonitoringConfig {
  return {
    baselineOnFirstRun: form.monitoringConfig.baselineOnFirstRun,
    deliverOnChangeOnly: form.monitoringConfig.deliverOnChangeOnly,
    enabled: form.monitoringConfig.enabled,
    notifyOnChange: form.monitoringConfig.notifyOnChange,
    stopConditions: {
      afterChangeCount: optionalPositiveInteger(form.monitoringConfig.stopAfterChangeCount),
      afterFirstChange: form.monitoringConfig.stopAfterFirstChange,
      afterRunCount: optionalPositiveInteger(form.monitoringConfig.stopAfterRunCount),
      afterUnchangedCount: optionalPositiveInteger(
        form.monitoringConfig.stopAfterUnchangedCount
      ),
    },
  };
}

function taskFormState(
  task: WorkspaceScheduledTaskRead | null,
  timezone: string
): FormState {
  const notificationRules = defaultNotificationRules();
  if (!task) {
    return {
      name: "",
      instructions: "",
      schedules: [newScheduleDraft("daily", timezone)],
      selectedRoutes: ["chat"],
      notificationRoutes: ["chat"],
      approvalRoutes: ["chat"],
      notificationRules,
      monitoringConfig: defaultMonitoringConfig(),
      resetMonitoringState: false,
      conversationPolicy: "reuse",
      isActive: true,
      maxAttempts: "3",
    };
  }
  return {
    name: task.name,
    instructions: task.instructions,
    schedules:
      task.schedules && task.schedules.length > 0
        ? task.schedules.map((schedule) => draftFromSchedule(schedule, timezone))
        : legacyDraftFromTask(task, timezone),
    selectedRoutes: routeKeys(task.outputRoutes),
    notificationRoutes: routeKeys(task.notificationRoutes),
    approvalRoutes: routeKeys(task.approvalRoutes),
    notificationRules: {
      ...notificationRules,
      ...(task.notificationRules ?? {}),
    },
    monitoringConfig: monitoringFormConfig(task),
    resetMonitoringState: false,
    conversationPolicy: task.conversationPolicy as ConversationPolicy,
    isActive: task.isActive,
    maxAttempts: String(task.maxAttempts || 3),
  };
}

function scheduleDraftConfig(draft: ScheduleDraft): Record<string, unknown> {
  if (draft.scheduleType === "interval") {
    return { everyMinutes: Number(draft.everyMinutes || 60) };
  }
  if (draft.scheduleType === "weekly") {
    return {
      times: draft.times,
      weekdays: draft.weekdays.map(Number).sort((left, right) => left - right),
    };
  }
  if (draft.scheduleType === "weekdays") {
    return { times: draft.times };
  }
  if (draft.scheduleType === "monthly") {
    return {
      monthDays: draft.monthDays.map(Number).sort((left, right) => left - right),
      times: draft.times,
    };
  }
  if (draft.scheduleType === "cron") {
    return { expression: draft.cronExpression.trim() };
  }
  return { times: draft.times };
}

function schedulePayload(
  draft: ScheduleDraft,
  options: { includeId: boolean }
): WorkspaceScheduledTaskScheduleCreate | WorkspaceScheduledTaskScheduleUpdate {
  const { includeId } = options;
  return {
    ...(includeId && draft.id ? { id: draft.id } : {}),
    endsAt: datetimeLocalToIso(draft.endsAt),
    isActive: draft.isActive,
    name: draft.name.trim(),
    scheduleConfig: scheduleDraftConfig(draft),
    scheduleType: draft.scheduleType,
    startsAt: datetimeLocalToIso(draft.startsAt),
    timezone: normalizeTimezone(draft.timezone),
  };
}

function schedulePayloads(
  form: FormState,
  options: { includeIds: boolean }
): (WorkspaceScheduledTaskScheduleCreate | WorkspaceScheduledTaskScheduleUpdate)[] {
  const { includeIds } = options;
  return form.schedules.map((draft) => schedulePayload(draft, { includeId: includeIds }));
}

function scheduleDraftIsValid(draft: ScheduleDraft) {
  if (!draft.timezone.trim()) {
    return false;
  }
  if (draft.startsAt && draft.endsAt) {
    const startsAt = new Date(draft.startsAt).getTime();
    const endsAt = new Date(draft.endsAt).getTime();
    if (!Number.isFinite(startsAt) || !Number.isFinite(endsAt) || endsAt <= startsAt) {
      return false;
    }
  }
  if (draft.scheduleType === "interval") {
    const minutes = Number(draft.everyMinutes);
    return Number.isInteger(minutes) && minutes >= 1 && minutes <= 10080;
  }
  if (draft.scheduleType === "cron") {
    return draft.cronExpression.trim().split(/\s+/).length === 5;
  }
  if (draft.scheduleType === "weekly" && draft.weekdays.length === 0) {
    return false;
  }
  if (draft.scheduleType === "monthly" && draft.monthDays.length === 0) {
    return false;
  }
  return draft.times.length > 0;
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
  if (task.schedules && task.schedules.length > 1) {
    return `${task.schedules.length} schedules`;
  }
  const schedule = task.schedules?.[0];
  if (schedule) {
    return scheduleEntryLabel(schedule.scheduleType as ScheduleEntryType, schedule.scheduleConfig);
  }
  const config = record(task.scheduleConfig);
  if (task.scheduleType === "manual") {
    return "Manual";
  }
  if (task.scheduleType === "interval") {
    return `Every ${String(config.everyMinutes ?? 60)} min`;
  }
  if (task.scheduleType === "weekly") {
    const weekdayValue = Array.isArray(config.weekdays) ? config.weekdays[0] : config.weekday;
    const weekday = weekdays.find((day) => day.value === String(weekdayValue ?? "0"));
    return `${weekday?.label ?? "Weekly"} at ${configTimes(config)[0] ?? "09:00"}`;
  }
  if (task.scheduleType === "weekdays") {
    return `Weekdays at ${configTimes(config).join(", ")}`;
  }
  if (task.scheduleType === "monthly") {
    return `Monthly at ${configTimes(config).join(", ")}`;
  }
  if (task.scheduleType === "cron") {
    return `Cron ${String(config.expression ?? "")}`;
  }
  return `Daily at ${configTimes(config).join(", ")}`;
}

function scheduleEntryLabel(scheduleType: ScheduleEntryType, config: unknown) {
  const values = record(config);
  if (scheduleType === "interval") {
    return `Every ${String(values.everyMinutes ?? 60)} min`;
  }
  if (scheduleType === "weekly") {
    const selectedWeekdays = configNumberList(config, "weekdays", "weekday", [0])
      .map((value) => weekdays.find((day) => day.value === value)?.label.slice(0, 3) ?? value)
      .join(", ");
    return `${selectedWeekdays} at ${configTimes(config).join(", ")}`;
  }
  if (scheduleType === "weekdays") {
    return `Weekdays at ${configTimes(config).join(", ")}`;
  }
  if (scheduleType === "monthly") {
    const monthDays = configNumberList(config, "monthDays", "monthDay", [1]).join(", ");
    return `Monthly ${monthDays} at ${configTimes(config).join(", ")}`;
  }
  if (scheduleType === "cron") {
    return `Cron ${String(values.expression ?? "")}`;
  }
  return `Daily at ${configTimes(config).join(", ")}`;
}

function statusVariant(status: string) {
  if (status === "succeeded" || status === "sent") {
    return "success" as const;
  }
  if (status === "failed" || status === "delivery_failed") {
    return "destructive" as const;
  }
  if (status === "partially_delivered") {
    return "outline" as const;
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
  if (status === "waiting_confirmation") {
    return "waiting approval";
  }
  if (status === "partially_delivered") {
    return "partially delivered";
  }
  if (status === "delivery_failed") {
    return "delivery failed";
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

function routeLabelForKey(key: string, providerOptions: ProviderRouteOption[]) {
  if (key === "chat") {
    return "Built-in chat";
  }
  const option = providerOptions.find((candidate) => candidate.key === key);
  return option ? `${option.source} · ${option.label}` : "Provider conversation";
}

function deliveryRouteLabel(
  delivery: WorkspaceScheduledTaskDeliveryRead,
  providerOptions: ProviderRouteOption[]
) {
  if (delivery.routeType === "chat") {
    return "Built-in chat";
  }
  const option = providerOptions.find(
    (candidate) =>
      candidate.connectionId === delivery.connectionId &&
      candidate.externalThreadId === delivery.externalThreadId
  );
  if (option) {
    return `${option.source} · ${option.label}`;
  }
  return delivery.displayName?.trim() || providerLabel(delivery.provider ?? "") || "Provider route";
}

function failedRetryableDeliveries(run: WorkspaceScheduledTaskRunRead) {
  return (run.deliveries ?? []).filter(
    (delivery) => delivery.status === "failed" && delivery.canRetry
  );
}

function metricValue(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function enabledNotificationRuleCount(task: WorkspaceScheduledTaskRead) {
  const rules = { ...defaultNotificationRules(), ...(task.notificationRules ?? {}) };
  return Object.values(rules).filter((enabled) => enabled).length;
}

function taskMonitoringEnabled(task: WorkspaceScheduledTaskRead) {
  return Boolean(record(task.monitoringConfig).enabled);
}

function monitoringState(task: WorkspaceScheduledTaskRead) {
  return record(task.monitoringState);
}

function taskMonitoringLabel(task: WorkspaceScheduledTaskRead) {
  if (!taskMonitoringEnabled(task)) {
    return "Standard";
  }
  const status = task.monitoringStatus || String(monitoringState(task).lastStatus ?? "watching");
  return status.replaceAll("_", " ");
}

function monitoringChangeCount(task: WorkspaceScheduledTaskRead) {
  const value = monitoringState(task).changeCount;
  return typeof value === "number" ? value : Number(value || 0);
}

function runMonitoringSummary(run: WorkspaceScheduledTaskRunRead) {
  const summary = record(run.deliverySummary);
  const monitoring = record(summary.monitoring);
  return monitoring.enabled ? monitoring : null;
}

function runOutputLabel(run: WorkspaceScheduledTaskRunRead) {
  const monitoring = runMonitoringSummary(run);
  if (monitoring) {
    const status = String(monitoring.status ?? "watching").replaceAll("_", " ");
    const stopReason = String(monitoring.stopReason ?? "").replaceAll("_", " ");
    return stopReason ? `${status} · ${stopReason}` : status;
  }
  return `${String(record(run.deliverySummary).sent ?? 0)} sent${
    Number(record(run.deliverySummary).failed ?? 0) > 0
      ? `, ${String(record(run.deliverySummary).failed)} failed`
      : ""
  }`;
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

type ScheduledTaskFormClientProps = {
  connections: ChatProviderConnectionRead[];
  organizationId: string;
  task?: WorkspaceScheduledTaskRead | null;
  workspaceId: string;
};

export function ScheduledTaskFormClient({
  connections,
  organizationId,
  task = null,
  workspaceId,
}: ScheduledTaskFormClientProps) {
  const router = useRouter();
  const providerOptions = useMemo(() => providerRouteOptions(connections), [connections]);
  const defaultTimezone = useMemo(() => browserTimezone(), []);
  const editingTask = task;
  const scheduledTasksHref = `/org/${encodeURIComponent(
    organizationId
  )}/workspace/${encodeURIComponent(workspaceId)}/scheduled-tasks`;
  const [form, setForm] = useState<FormState>(() => taskFormState(task, defaultTimezone));
  const [previewRuns, setPreviewRuns] = useState<string[]>(task?.nextRunPreview ?? []);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ variant: "success" | "error"; text: string } | null>(
    null
  );
  const [routeTests, setRouteTests] = useState<Record<string, RouteTestState>>({});
  const isTestingRoutes = Object.values(routeTests).some((test) => test.status === "testing");

  function routeForKey(key: string) {
    if (key !== "chat" && !providerOptions.some((option) => option.key === key)) {
      return null;
    }
    return buildOutputRoutes([key], providerOptions)[0] ?? null;
  }

  function routeTestStatus(key: string) {
    return routeTests[key] ?? { status: "idle" as const };
  }

  function routeTestBadge(key: string) {
    const state = routeTestStatus(key);
    if (state.status === "idle") {
      return null;
    }
    if (state.status === "testing") {
      return <Badge variant="secondary">Testing</Badge>;
    }
    if (state.status === "sent") {
      return <Badge variant="success">Test sent</Badge>;
    }
    return <Badge variant="destructive">Test failed</Badge>;
  }

  async function testRoute(key: string) {
    const route = routeForKey(key);
    if (!route) {
      setRouteTests((current) => ({
        ...current,
        [key]: { error: "Route is not available.", status: "failed" },
      }));
      return;
    }
    setRouteTests((current) => ({
      ...current,
      [key]: { status: "testing" },
    }));
    try {
      const response = await workspaceScheduledTasksTestRoute(organizationId, workspaceId, {
        message: `Wardn scheduled task route test: ${form.name.trim() || "Scheduled task"}`,
        route,
      });
      const status = response.status === "sent" ? "sent" : "failed";
      setRouteTests((current) => ({
        ...current,
        [key]: { error: response.error, status },
      }));
    } catch (error) {
      setRouteTests((current) => ({
        ...current,
        [key]: {
          error: error instanceof Error ? error.message : "Route test failed.",
          status: "failed",
        },
      }));
    }
  }

  async function testSelectedRoutes() {
    setFeedback(null);
    await Promise.all(form.selectedRoutes.map((key) => testRoute(key)));
  }

  function toggleRoute(key: string) {
    const selected = new Set(form.selectedRoutes);
    if (selected.has(key)) {
      selected.delete(key);
    } else {
      selected.add(key);
    }
    setForm({ ...form, selectedRoutes: Array.from(selected) });
  }

  function toggleNotificationRoute(key: string) {
    const selected = new Set(form.notificationRoutes);
    if (selected.has(key)) {
      selected.delete(key);
    } else {
      selected.add(key);
    }
    setForm({ ...form, notificationRoutes: Array.from(selected) });
  }

  function toggleApprovalRoute(key: string) {
    const selected = new Set(form.approvalRoutes);
    if (selected.has(key)) {
      selected.delete(key);
    } else {
      selected.add(key);
    }
    setForm({ ...form, approvalRoutes: Array.from(selected) });
  }

  function toggleNotificationRule(key: keyof FormState["notificationRules"]) {
    setForm({
      ...form,
      notificationRules: {
        ...form.notificationRules,
        [key]: !form.notificationRules[key],
      },
    });
  }

  function updateMonitoringConfig(patch: Partial<FormState["monitoringConfig"]>) {
    setForm({
      ...form,
      monitoringConfig: {
        ...form.monitoringConfig,
        ...patch,
      },
    });
  }

  function addSchedule(type: ScheduleEntryType) {
    const timezone = form.schedules[0]?.timezone || defaultTimezone;
    setForm({ ...form, schedules: [...form.schedules, newScheduleDraft(type, timezone)] });
  }

  function updateSchedule(key: string, patch: Partial<ScheduleDraft>) {
    setForm({
      ...form,
      schedules: form.schedules.map((schedule) =>
        schedule.key === key ? { ...schedule, ...patch } : schedule
      ),
    });
  }

  function removeSchedule(key: string) {
    setForm({ ...form, schedules: form.schedules.filter((schedule) => schedule.key !== key) });
  }

  function addRunTime(schedule: ScheduleDraft) {
    const nextTime = schedule.timeInput.trim() || "09:00";
    if (!nextTime || schedule.times.includes(nextTime)) {
      return;
    }
    updateSchedule(schedule.key, { times: [...schedule.times, nextTime].sort() });
  }

  function removeRunTime(schedule: ScheduleDraft, timeValue: string) {
    updateSchedule(schedule.key, {
      times: schedule.times.filter((candidate) => candidate !== timeValue),
    });
  }

  function toggleValue(schedule: ScheduleDraft, field: "weekdays" | "monthDays", value: string) {
    const selected = new Set(schedule[field]);
    if (selected.has(value)) {
      selected.delete(value);
    } else {
      selected.add(value);
    }
    updateSchedule(schedule.key, {
      [field]: Array.from(selected).sort((left, right) => Number(left) - Number(right)),
    });
  }

  const canSave = Boolean(
    form.name.trim() &&
      form.instructions.trim() &&
      form.schedules.every((schedule) => scheduleDraftIsValid(schedule))
  );

  async function previewSchedules() {
    setIsPreviewing(true);
    setFeedback(null);
    try {
      const response = await workspaceScheduledTasksPreview(organizationId, workspaceId, {
        isActive: form.isActive,
        schedules: schedulePayloads(form, { includeIds: false }) as WorkspaceScheduledTaskScheduleCreate[],
      });
      setPreviewRuns(response.nextRuns ?? []);
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Could not preview scheduled runs.",
      });
    } finally {
      setIsPreviewing(false);
    }
  }

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setFeedback(null);
    const aggregateScheduleType: ScheduleType =
      form.schedules.length === 0
        ? "manual"
        : form.schedules.length === 1
          ? form.schedules[0].scheduleType
          : "multiple";
    const basePayload = {
      approvalRoutes: buildOutputRoutes(form.approvalRoutes, providerOptions),
      conversationPolicy: form.conversationPolicy,
      instructions: form.instructions.trim(),
      isActive: form.isActive,
      maxAttempts: Number(form.maxAttempts || 3),
      name: form.name.trim(),
      monitoringConfig: monitoringPayload(form),
      notificationRoutes: buildOutputRoutes(form.notificationRoutes, providerOptions),
      notificationRules: form.notificationRules,
      outputRoutes: buildOutputRoutes(form.selectedRoutes, providerOptions),
      scheduleConfig: form.schedules[0] ? scheduleDraftConfig(form.schedules[0]) : {},
      scheduleType: aggregateScheduleType,
      timezone: normalizeTimezone(form.schedules[0]?.timezone ?? defaultTimezone),
    };

    try {
      if (editingTask) {
        const updatePayload: WorkspaceScheduledTaskUpdate = {
          ...basePayload,
          resetMonitoringState: form.resetMonitoringState,
          schedules: schedulePayloads(form, { includeIds: true }) as WorkspaceScheduledTaskScheduleUpdate[],
        };
        await workspaceScheduledTasksUpdate(
          organizationId,
          workspaceId,
          editingTask.id,
          updatePayload
        );
        setFeedback({ variant: "success", text: "Scheduled task updated." });
      } else {
        const payload: WorkspaceScheduledTaskCreate = {
          ...basePayload,
          schedules: schedulePayloads(form, { includeIds: false }) as WorkspaceScheduledTaskScheduleCreate[],
        };
        await workspaceScheduledTasksCreate(organizationId, workspaceId, payload);
        setFeedback({ variant: "success", text: "Scheduled task created." });
      }
      router.push(scheduledTasksHref);
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

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <Button asChild variant="outline">
          <Link href={scheduledTasksHref}>
            <ArrowLeft className="size-4" />
            Back
          </Link>
        </Button>
        <Badge variant={form.isActive ? "success" : "secondary"}>
          {form.isActive ? "Active" : "Paused"}
        </Badge>
      </div>

      {feedback ? (
        <AsyncFeedback variant={feedback.variant}>{feedback.text}</AsyncFeedback>
      ) : null}

      <form className="space-y-5" onSubmit={submitTask}>
          <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
            <div className="space-y-2">
              <Label htmlFor="scheduled-task-name">Name</Label>
              <Input
                id="scheduled-task-name"
                maxLength={120}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
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
                onClick={() => setForm({ ...form, isActive: !form.isActive })}
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
              onChange={(event) => setForm({ ...form, instructions: event.target.value })}
              required
              value={form.instructions}
            />
          </div>

          <div className="grid gap-4 rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <CalendarClock className="size-4 text-muted-foreground" />
                Schedules
                <Badge variant="secondary">{form.schedules.length || "Manual"}</Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                {schedulePresets.map((preset) => {
                  const PresetIcon = preset.icon;
                  return (
                    <Button
                      key={preset.type}
                      onClick={() => addSchedule(preset.type)}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      <PresetIcon className="size-4" />
                      {preset.label}
                    </Button>
                  );
                })}
              </div>
            </div>

            {form.schedules.length === 0 ? (
              <div className="flex items-center gap-3 rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
                <Play className="size-4" />
                <span>Manual run only</span>
              </div>
            ) : null}

            {form.schedules.map((schedule, index) => {
              const typePreset = schedulePresets.find((preset) => preset.type === schedule.scheduleType);
              const TypeIcon = typePreset?.icon ?? Clock3;
              return (
                <div className="grid gap-3 rounded-md border border-border bg-card p-3" key={schedule.key}>
                  <div className="grid gap-2 md:grid-cols-[1fr_180px_92px_40px]">
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-name-${schedule.key}`}>Label</Label>
                      <Input
                        id={`schedule-name-${schedule.key}`}
                        maxLength={120}
                        onChange={(event) => updateSchedule(schedule.key, { name: event.target.value })}
                        placeholder={`Schedule ${index + 1}`}
                        value={schedule.name}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-type-${schedule.key}`}>Type</Label>
                      <Select
                        onValueChange={(value) => {
                          const nextType = value as ScheduleEntryType;
                          const defaults = newScheduleDraft(nextType, schedule.timezone);
                          updateSchedule(schedule.key, {
                            cronExpression: defaults.cronExpression,
                            everyMinutes: defaults.everyMinutes,
                            monthDays: defaults.monthDays,
                            scheduleType: nextType,
                            times: defaults.times,
                            weekdays: defaults.weekdays,
                          });
                        }}
                        value={schedule.scheduleType}
                      >
                        <SelectTrigger id={`schedule-type-${schedule.key}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {schedulePresets.map((preset) => (
                            <SelectItem key={preset.type} value={preset.type}>
                              {preset.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>State</Label>
                      <button
                        className={cn(
                          "flex h-9 w-full items-center justify-center gap-2 rounded-md border text-sm",
                          schedule.isActive
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : "border-border bg-muted text-muted-foreground"
                        )}
                        onClick={() => updateSchedule(schedule.key, { isActive: !schedule.isActive })}
                        type="button"
                      >
                        <TypeIcon className="size-4" />
                        {schedule.isActive ? "On" : "Off"}
                      </button>
                    </div>
                    <div className="space-y-2">
                      <Label className="opacity-0">Remove</Label>
                      <Button
                        onClick={() => removeSchedule(schedule.key)}
                        size="icon"
                        title="Remove schedule"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>

                  {schedule.scheduleType === "interval" ? (
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-interval-${schedule.key}`}>Every minutes</Label>
                      <Input
                        id={`schedule-interval-${schedule.key}`}
                        max={10080}
                        min={1}
                        onChange={(event) =>
                          updateSchedule(schedule.key, { everyMinutes: event.target.value })
                        }
                        type="number"
                        value={schedule.everyMinutes}
                      />
                    </div>
                  ) : null}

                  {schedule.scheduleType === "cron" ? (
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-cron-${schedule.key}`}>Cron</Label>
                      <Input
                        id={`schedule-cron-${schedule.key}`}
                        onChange={(event) =>
                          updateSchedule(schedule.key, { cronExpression: event.target.value })
                        }
                        placeholder="0 9 * * 1-5"
                        value={schedule.cronExpression}
                      />
                    </div>
                  ) : null}

                  {schedule.scheduleType !== "interval" && schedule.scheduleType !== "cron" ? (
                    <div className="grid gap-2">
                      <Label>Run times</Label>
                      <div className="flex flex-wrap gap-2">
                        {schedule.times.map((timeValue) => (
                          <button
                            className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-muted px-2 text-xs"
                            key={timeValue}
                            onClick={() => removeRunTime(schedule, timeValue)}
                            type="button"
                          >
                            {timeValue}
                            <X className="size-3" />
                          </button>
                        ))}
                        <div className="flex gap-2">
                          <Input
                            className="w-28"
                            onChange={(event) =>
                              updateSchedule(schedule.key, { timeInput: event.target.value })
                            }
                            type="time"
                            value={schedule.timeInput}
                          />
                          <Button onClick={() => addRunTime(schedule)} size="sm" type="button" variant="outline">
                            <Plus className="size-4" />
                            Add
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {schedule.scheduleType === "weekly" ? (
                    <div className="grid gap-2">
                      <Label>Weekdays</Label>
                      <div className="flex flex-wrap gap-2">
                        {weekdays.map((weekday) => (
                          <button
                            className={cn(
                              "h-8 rounded-md border px-2 text-xs",
                              schedule.weekdays.includes(weekday.value)
                                ? "border-ring bg-sidebar-accent text-foreground"
                                : "border-border bg-card text-muted-foreground"
                            )}
                            key={weekday.value}
                            onClick={() => toggleValue(schedule, "weekdays", weekday.value)}
                            type="button"
                          >
                            {weekday.label.slice(0, 3)}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {schedule.scheduleType === "monthly" ? (
                    <div className="grid gap-2">
                      <Label>Month days</Label>
                      <div className="grid grid-cols-7 gap-1 sm:grid-cols-10">
                        {Array.from({ length: 31 }, (_, day) => String(day + 1)).map((day) => (
                          <button
                            className={cn(
                              "h-8 rounded-md border text-xs",
                              schedule.monthDays.includes(day)
                                ? "border-ring bg-sidebar-accent text-foreground"
                                : "border-border bg-card text-muted-foreground"
                            )}
                            key={day}
                            onClick={() => toggleValue(schedule, "monthDays", day)}
                            type="button"
                          >
                            {day}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-timezone-${schedule.key}`}>Timezone</Label>
                      <Input
                        id={`schedule-timezone-${schedule.key}`}
                        onChange={(event) =>
                          updateSchedule(schedule.key, { timezone: event.target.value })
                        }
                        value={schedule.timezone}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-start-${schedule.key}`}>Start</Label>
                      <Input
                        id={`schedule-start-${schedule.key}`}
                        onChange={(event) =>
                          updateSchedule(schedule.key, { startsAt: event.target.value })
                        }
                        type="datetime-local"
                        value={schedule.startsAt}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`schedule-end-${schedule.key}`}>End</Label>
                      <Input
                        id={`schedule-end-${schedule.key}`}
                        onChange={(event) =>
                          updateSchedule(schedule.key, { endsAt: event.target.value })
                        }
                        type="datetime-local"
                        value={schedule.endsAt}
                      />
                    </div>
                  </div>
                </div>
              );
            })}

            <div className="grid gap-2 rounded-md border border-dashed border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium">Next 5 runs</div>
                <Button
                  disabled={isPreviewing || !canSave}
                  onClick={previewSchedules}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  {isPreviewing ? <RefreshCw className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  Preview
                </Button>
              </div>
              {previewRuns.length > 0 ? (
                <div className="grid gap-1 text-sm">
                  {previewRuns.map((run) => (
                    <div className="rounded-md bg-muted px-2 py-1" key={run}>
                      {formatDate(run)}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">No upcoming runs.</div>
              )}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-[1fr_220px]">
            <div className="rounded-md border border-border">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Route className="size-4 text-muted-foreground" />
                  Output
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">{form.selectedRoutes.length}</Badge>
                  <Button
                    disabled={isTestingRoutes || form.selectedRoutes.length === 0}
                    onClick={testSelectedRoutes}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    {isTestingRoutes ? (
                      <RefreshCw className="size-4 animate-spin" />
                    ) : (
                      <Send className="size-4" />
                    )}
                    Test
                  </Button>
                </div>
              </div>
              <div className="grid gap-2 p-3">
                <div className="flex min-h-11 items-center gap-3 rounded-md border border-border bg-card px-3 py-2 text-sm">
                  <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                    <input
                      checked={form.selectedRoutes.includes("chat")}
                      className="size-4"
                      onChange={() => toggleRoute("chat")}
                      type="checkbox"
                    />
                    <MessageSquare className="size-4 text-muted-foreground" />
                    <span>Built-in chat</span>
                  </label>
                  {form.selectedRoutes.includes("chat") ? routeTestBadge("chat") : null}
                  {form.selectedRoutes.includes("chat") ? (
                    <Button
                      disabled={routeTestStatus("chat").status === "testing"}
                      onClick={() => testRoute("chat")}
                      size="icon"
                      title="Test built-in chat route"
                      type="button"
                      variant="outline"
                    >
                      {routeTestStatus("chat").status === "testing" ? (
                        <RefreshCw className="size-4 animate-spin" />
                      ) : (
                        <Send className="size-4" />
                      )}
                    </Button>
                  ) : null}
                </div>
                {providerOptions.map((option) => (
                  <div
                    className="flex min-h-12 items-center gap-3 rounded-md border border-border bg-card px-3 py-2 text-sm"
                    key={option.key}
                  >
                    <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
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
                    {form.selectedRoutes.includes(option.key) ? routeTestBadge(option.key) : null}
                    {form.selectedRoutes.includes(option.key) ? (
                      <Button
                        disabled={routeTestStatus(option.key).status === "testing"}
                        onClick={() => testRoute(option.key)}
                        size="icon"
                        title={`Test ${routeLabelForKey(option.key, providerOptions)}`}
                        type="button"
                        variant="outline"
                      >
                        {routeTestStatus(option.key).status === "testing" ? (
                          <RefreshCw className="size-4 animate-spin" />
                        ) : (
                          <Send className="size-4" />
                        )}
                      </Button>
                    ) : null}
                  </div>
                ))}
                {providerOptions.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                    Connect a provider and receive a message before selecting an external route.
                  </div>
                ) : null}
                {Object.entries(routeTests).some(
                  ([key, state]) =>
                    form.selectedRoutes.includes(key) && state.status === "failed"
                ) ? (
                  <div className="grid gap-1 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    {Object.entries(routeTests)
                      .filter(
                        ([key, state]) =>
                          form.selectedRoutes.includes(key) && state.status === "failed"
                      )
                      .map(([key, state]) => (
                        <div className="min-w-0 truncate" key={key}>
                          {routeLabelForKey(key, providerOptions)}: {state.error || "Test failed."}
                        </div>
                      ))}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="grid gap-3">
              <div className="space-y-2">
                <Label htmlFor="scheduled-task-conversation-policy">Chat history</Label>
                <Select
                  onValueChange={(value) =>
                    setForm({ ...form, conversationPolicy: value as ConversationPolicy })
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
                  onChange={(event) => setForm({ ...form, maxAttempts: event.target.value })}
                  type="number"
                  value={form.maxAttempts}
                />
              </div>
            </div>
          </div>

          <div className="grid gap-4 rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Eye className="size-4 text-muted-foreground" />
                Monitoring
              </div>
              <Badge variant={form.monitoringConfig.enabled ? "success" : "secondary"}>
                {form.monitoringConfig.enabled ? "On" : "Off"}
              </Badge>
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <button
                className={cn(
                  "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                  form.monitoringConfig.enabled
                    ? "border-ring bg-sidebar-accent text-foreground"
                    : "border-border bg-card text-muted-foreground"
                )}
                onClick={() =>
                  updateMonitoringConfig({ enabled: !form.monitoringConfig.enabled })
                }
                type="button"
              >
                <span>Watch mode</span>
                <CheckCircle2
                  className={cn(
                    "size-4",
                    form.monitoringConfig.enabled ? "opacity-100" : "opacity-0"
                  )}
                />
              </button>
              <button
                className={cn(
                  "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                  form.monitoringConfig.notifyOnChange
                    ? "border-ring bg-sidebar-accent text-foreground"
                    : "border-border bg-card text-muted-foreground"
                )}
                disabled={!form.monitoringConfig.enabled}
                onClick={() =>
                  updateMonitoringConfig({
                    notifyOnChange: !form.monitoringConfig.notifyOnChange,
                  })
                }
                type="button"
              >
                <span>Notify on change</span>
                <BellRing className="size-4" />
              </button>
              <button
                className={cn(
                  "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                  form.monitoringConfig.deliverOnChangeOnly
                    ? "border-ring bg-sidebar-accent text-foreground"
                    : "border-border bg-card text-muted-foreground"
                )}
                disabled={!form.monitoringConfig.enabled}
                onClick={() =>
                  updateMonitoringConfig({
                    deliverOnChangeOnly: !form.monitoringConfig.deliverOnChangeOnly,
                  })
                }
                type="button"
              >
                <span>Deliver on change</span>
                <Route className="size-4" />
              </button>
              <button
                className={cn(
                  "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                  form.monitoringConfig.baselineOnFirstRun
                    ? "border-ring bg-sidebar-accent text-foreground"
                    : "border-border bg-card text-muted-foreground"
                )}
                disabled={!form.monitoringConfig.enabled}
                onClick={() =>
                  updateMonitoringConfig({
                    baselineOnFirstRun: !form.monitoringConfig.baselineOnFirstRun,
                  })
                }
                type="button"
              >
                <span>Baseline first run</span>
                <CheckCircle2 className="size-4" />
              </button>
            </div>

            {form.monitoringConfig.enabled ? (
              <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
                <div className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-4">
                  <button
                    className={cn(
                      "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                      form.monitoringConfig.stopAfterFirstChange
                        ? "border-ring bg-sidebar-accent text-foreground"
                        : "border-border bg-card text-muted-foreground"
                    )}
                    onClick={() =>
                      updateMonitoringConfig({
                        stopAfterFirstChange: !form.monitoringConfig.stopAfterFirstChange,
                      })
                    }
                    type="button"
                  >
                    <span>Stop on change</span>
                    <Pause className="size-4" />
                  </button>
                  <div className="space-y-2">
                    <Label htmlFor="monitoring-stop-change-count">Change count</Label>
                    <Input
                      id="monitoring-stop-change-count"
                      min={1}
                      onChange={(event) =>
                        updateMonitoringConfig({
                          stopAfterChangeCount: event.target.value,
                        })
                      }
                      placeholder="No limit"
                      type="number"
                      value={form.monitoringConfig.stopAfterChangeCount}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="monitoring-stop-run-count">Run count</Label>
                    <Input
                      id="monitoring-stop-run-count"
                      min={1}
                      onChange={(event) =>
                        updateMonitoringConfig({ stopAfterRunCount: event.target.value })
                      }
                      placeholder="No limit"
                      type="number"
                      value={form.monitoringConfig.stopAfterRunCount}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="monitoring-stop-unchanged-count">Unchanged count</Label>
                    <Input
                      id="monitoring-stop-unchanged-count"
                      min={1}
                      onChange={(event) =>
                        updateMonitoringConfig({
                          stopAfterUnchangedCount: event.target.value,
                        })
                      }
                      placeholder="No limit"
                      type="number"
                      value={form.monitoringConfig.stopAfterUnchangedCount}
                    />
                  </div>
                </div>

                {editingTask ? (
                  <div className="grid gap-3 rounded-md border border-border p-3">
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <div className="text-xs text-muted-foreground">State</div>
                        <div className="mt-1 font-medium">
                          {taskMonitoringLabel(editingTask)}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">Changes</div>
                        <div className="mt-1 font-medium">
                          {metricValue(monitoringChangeCount(editingTask))}
                        </div>
                      </div>
                    </div>
                    <label className="flex min-h-10 cursor-pointer items-center gap-3 rounded-md border border-border bg-card px-3 text-sm">
                      <input
                        checked={form.resetMonitoringState}
                        className="size-4"
                        onChange={() =>
                          setForm({
                            ...form,
                            resetMonitoringState: !form.resetMonitoringState,
                          })
                        }
                        type="checkbox"
                      />
                      <RefreshCw className="size-4 text-muted-foreground" />
                      <span>Reset baseline</span>
                    </label>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="grid gap-4 rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <BellRing className="size-4 text-muted-foreground" />
                Notifications
              </div>
              <Badge variant="secondary">
                {
                  Object.values(form.notificationRules).filter((enabled) => enabled)
                    .length
                }
              </Badge>
            </div>

            <div className="grid gap-3 md:grid-cols-5">
              {[
                ["onFailure", "Failure"],
                ["onWaitingApproval", "Waiting approval"],
                ["onNoOutput", "No output"],
                ["onDeliveryFailure", "Delivery failure"],
                ["onMeaningfulUpdate", "Meaningful update"],
              ].map(([key, label]) => (
                <button
                  className={cn(
                    "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                    form.notificationRules[key as keyof FormState["notificationRules"]]
                      ? "border-ring bg-sidebar-accent text-foreground"
                      : "border-border bg-card text-muted-foreground"
                  )}
                  key={key}
                  onClick={() =>
                    toggleNotificationRule(key as keyof FormState["notificationRules"])
                  }
                  type="button"
                >
                  <span>{label}</span>
                  <span
                    className={cn(
                      "flex size-4 items-center justify-center rounded border",
                      form.notificationRules[key as keyof FormState["notificationRules"]]
                        ? "border-ring bg-ring text-primary-foreground"
                        : "border-border bg-background"
                    )}
                  >
                    {form.notificationRules[key as keyof FormState["notificationRules"]] ? (
                      <CheckCircle2 className="size-3" />
                    ) : null}
                  </span>
                </button>
              ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-md border border-border">
                <div className="flex items-center justify-between border-b border-border px-3 py-2">
                  <div className="text-sm font-medium">Notification route</div>
                  <Badge variant="secondary">{form.notificationRoutes.length}</Badge>
                </div>
                <div className="grid gap-2 p-3">
                  <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-border bg-card px-3 text-sm">
                    <input
                      checked={form.notificationRoutes.includes("chat")}
                      className="size-4"
                      onChange={() => toggleNotificationRoute("chat")}
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
                        checked={form.notificationRoutes.includes(option.key)}
                        className="size-4"
                        onChange={() => toggleNotificationRoute(option.key)}
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
                </div>
              </div>

              <div className="rounded-md border border-border">
                <div className="flex items-center justify-between border-b border-border px-3 py-2">
                  <div className="text-sm font-medium">Approval route</div>
                  <Badge variant="secondary">{form.approvalRoutes.length}</Badge>
                </div>
                <div className="grid gap-2 p-3">
                  <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-border bg-card px-3 text-sm">
                    <input
                      checked={form.approvalRoutes.includes("chat")}
                      className="size-4"
                      onChange={() => toggleApprovalRoute("chat")}
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
                        checked={form.approvalRoutes.includes(option.key)}
                        className="size-4"
                        onChange={() => toggleApprovalRoute(option.key)}
                        type="checkbox"
                      />
                      <ShieldCheck className="size-4 text-muted-foreground" />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{option.label}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {option.source}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-5">
            <Button asChild type="button" variant="outline">
              <Link href={scheduledTasksHref}>Cancel</Link>
            </Button>
            <Button disabled={!canSave || isSaving} type="submit">
              {isSaving ? <RefreshCw className="size-4 animate-spin" /> : <Save className="size-4" />}
              {editingTask ? "Save task" : "Create task"}
            </Button>
          </div>
        </form>
    </div>
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
  const [nowMs] = useState(() => Date.now());
  const [taskRows, setTaskRows] = useState(tasks);
  const [runRows, setRunRows] = useState(runs);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [busyDeliveryId, setBusyDeliveryId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ variant: "success" | "error"; text: string } | null>(
    null
  );
  const newTaskHref = `/org/${encodeURIComponent(
    organizationId
  )}/workspace/${encodeURIComponent(workspaceId)}/scheduled-tasks/new`;
  const scheduledTasksHref = newTaskHref.replace(/\/new$/, "");

  const stats = useMemo(() => {
    const day = 24 * 60 * 60 * 1000;
    return {
      active: taskRows.filter((task) => task.isActive).length,
      monitoring: taskRows.filter(taskMonitoringEnabled).length,
      dueSoon: taskRows.filter((task) => {
        if (!task.nextRunAt || !task.isActive) {
          return false;
        }
        const next = new Date(task.nextRunAt).getTime();
        return Number.isFinite(next) && next - nowMs <= day && next >= nowMs - 60_000;
      }).length,
      failed: taskRows.filter((task) =>
        ["failed", "delivery_failed"].includes(task.lastStatus)
      ).length,
      waiting: runRows.filter((run) => run.status === "waiting_confirmation").length,
    };
  }, [nowMs, runRows, taskRows]);

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

  async function retryDelivery(
    run: WorkspaceScheduledTaskRunRead,
    delivery: WorkspaceScheduledTaskDeliveryRead
  ) {
    setBusyDeliveryId(delivery.id);
    setFeedback(null);
    try {
      const updatedRun = await workspaceScheduledTasksRetryDelivery(
        organizationId,
        workspaceId,
        run.taskId,
        run.id,
        delivery.id
      );
      setRunRows((current) =>
        current.map((row) => (row.id === updatedRun.id ? updatedRun : row))
      );
      setTaskRows((current) =>
        current.map((row) =>
          row.lastTaskRunId === updatedRun.id ? { ...row, lastStatus: updatedRun.status } : row
        )
      );
      setFeedback({ variant: "success", text: "Delivery retried." });
      router.refresh();
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Could not retry delivery.",
      });
    } finally {
      setBusyDeliveryId(null);
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
      <section className="grid gap-3 md:grid-cols-5">
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
              <div className="text-sm font-medium text-muted-foreground">Monitoring</div>
              <Eye className="size-4 text-muted-foreground" />
            </div>
            <div className="mt-3 text-2xl font-semibold">{metricValue(stats.monitoring)}</div>
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
        <Button asChild>
          <Link href={newTaskHref}>
            <Plus className="size-4" />
            New task
          </Link>
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
            const notificationCount = enabledNotificationRuleCount(task);
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
                        <Badge variant="secondary">
                          {notificationCount} notifications
                        </Badge>
                        {taskMonitoringEnabled(task) ? (
                          <Badge
                            variant={
                              task.monitoringStatus === "changed" ||
                              task.monitoringStatus === "stopped"
                                ? "outline"
                                : "secondary"
                            }
                          >
                            {taskMonitoringLabel(task)}
                          </Badge>
                        ) : null}
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
                      <Button asChild disabled={busy} size="icon" title="Edit" variant="outline">
                        <Link href={`${scheduledTasksHref}/${encodeURIComponent(task.id)}/edit`}>
                          <Pencil className="size-4" />
                        </Link>
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
                  {taskMonitoringEnabled(task) ? (
                    <div className="grid gap-2">
                      <div className="text-xs text-muted-foreground">Monitoring</div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">
                          {metricValue(monitoringChangeCount(task))} changes
                        </Badge>
                        <Badge variant="secondary">{taskMonitoringLabel(task)}</Badge>
                      </div>
                    </div>
                  ) : null}
	                  {task.schedules && task.schedules.length > 0 ? (
	                    <div className="grid gap-2">
	                      <div className="text-xs text-muted-foreground">Attached schedules</div>
	                      <div className="flex flex-wrap gap-2">
	                        {task.schedules.map((schedule) => (
	                          <Badge
	                            key={schedule.id}
	                            variant={schedule.isActive ? "outline" : "secondary"}
	                          >
	                            {schedule.name ? `${schedule.name}: ` : ""}
	                            {scheduleEntryLabel(
	                              schedule.scheduleType as ScheduleEntryType,
	                              schedule.scheduleConfig
	                            )}
	                          </Badge>
	                        ))}
	                      </div>
	                    </div>
	                  ) : null}
	                  {task.nextRunPreview && task.nextRunPreview.length > 0 ? (
	                    <div className="grid gap-2">
	                      <div className="text-xs text-muted-foreground">Next 5 runs</div>
	                      <div className="grid gap-1 sm:grid-cols-2">
	                        {task.nextRunPreview.slice(0, 5).map((run) => (
	                          <div className="rounded-md bg-muted px-2 py-1 text-xs" key={run}>
	                            {shortDate(run)}
	                          </div>
	                        ))}
	                      </div>
	                    </div>
	                  ) : null}
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
            <Button asChild className="mt-4">
              <Link href={newTaskHref}>
                <Plus className="size-4" />
                New task
              </Link>
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
              const retryableDeliveries = failedRetryableDeliveries(run);
              return (
                <div
                  className="grid gap-3 rounded-md border border-border px-3 py-2 text-sm md:grid-cols-[1fr_150px_150px_130px_120px]"
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
                    <div className="mt-0.5">{runOutputLabel(run)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Notifications</div>
                    <div className="mt-0.5">
                      {String(run.notifications?.length ?? 0)} routed
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
                  {retryableDeliveries.length > 0 ? (
                    <div className="grid gap-2 border-t border-border pt-2 md:col-span-5">
                      {retryableDeliveries.map((delivery) => (
                        <div
                          className="flex items-center justify-between gap-3 rounded-md bg-red-50 px-2 py-2 text-xs text-red-700"
                          key={delivery.id}
                        >
                          <div className="min-w-0">
                            <div className="truncate font-medium">
                              {deliveryRouteLabel(delivery, providerOptions)}
                            </div>
                            <div className="mt-0.5 truncate text-red-600">
                              {delivery.error || "Delivery failed."}
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            {delivery.retryCount ? (
                              <Badge variant="destructive">
                                {delivery.retryCount} retries
                              </Badge>
                            ) : null}
                            <Button
                              disabled={busyDeliveryId === delivery.id}
                              onClick={() => retryDelivery(run, delivery)}
                              size="sm"
                              title="Retry delivery"
                              variant="outline"
                            >
                              {busyDeliveryId === delivery.id ? (
                                <RefreshCw className="size-4 animate-spin" />
                              ) : (
                                <RefreshCw className="size-4" />
                              )}
                              Retry
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
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

    </div>
  );
}
