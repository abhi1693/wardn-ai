"use client";

import {
  ArrowLeft,
  ArrowRight,
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
  workspaceScheduledTasksCancelRun,
  workspaceScheduledTasksCreate,
  workspaceScheduledTasksDelete,
  workspaceScheduledTasksPreview,
  workspaceScheduledTasksRetryDelivery,
  workspaceScheduledTasksRunNow,
  workspaceScheduledTasksTestRoute,
  workspaceScheduledTasksUpdate,
} from "@/lib/api/generated/workspace-scheduled-tasks/workspace-scheduled-tasks";
import { formatUserDateTimeInputValue, parseUserDateTimeInputValue } from "@/lib/date-time";
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

const timezoneOptions = [
  "Asia/Kolkata",
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const editorSections = [
  { id: "instructions", label: "Instructions" },
  { id: "schedule", label: "Schedule" },
  { id: "outputs", label: "Outputs" },
  { id: "notifications", label: "Notifications" },
  { id: "monitoring", label: "Monitoring" },
  { id: "review", label: "Review" },
] as const;

type EditorSectionId = (typeof editorSections)[number]["id"];

const notificationRuleOptions: {
  key: keyof FormState["notificationRules"];
  label: string;
}[] = [
  { key: "onFailure", label: "Failure" },
  { key: "onWaitingApproval", label: "Waiting approval" },
  { key: "onNoOutput", label: "No output" },
  { key: "onDeliveryFailure", label: "Delivery failure" },
  { key: "onMeaningfulUpdate", label: "Meaningful update" },
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
  return formatUserDateTimeInputValue(value);
}

function datetimeLocalToIso(value: string) {
  return parseUserDateTimeInputValue(value);
}

function scheduleKey() {
  return `schedule-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function newScheduleDraft(
  type: ScheduleEntryType,
  timezone: string,
  key = scheduleKey()
): ScheduleDraft {
  return {
    cronExpression: type === "cron" ? "0 9 * * 1-5" : "",
    endsAt: "",
    everyMinutes: "60",
    isActive: true,
    key,
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
      schedules: [newScheduleDraft("daily", timezone, "draft-schedule-1")],
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

function canCancelRun(run: WorkspaceScheduledTaskRunRead) {
  return Boolean(run.canCancel);
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

function scheduleDisplayName(schedule: ScheduleDraft, index: number) {
  return schedule.name.trim() || `Execution ${index + 1}`;
}

function weekdayShortLabel(value: string) {
  return weekdays.find((weekday) => weekday.value === value)?.label.slice(0, 3) ?? value;
}

function monthDayLabel(value: string) {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed.toString() : value;
}

function scheduleDraftSummary(schedule: ScheduleDraft) {
  if (!schedule.isActive) {
    return "Paused";
  }
  if (schedule.scheduleType === "interval") {
    return `Runs every ${schedule.everyMinutes || "60"} minutes`;
  }
  if (schedule.scheduleType === "cron") {
    return `Runs from cron expression ${schedule.cronExpression || "not set"}`;
  }
  const times = schedule.times.length ? schedule.times.join(", ") : "no run time";
  if (schedule.scheduleType === "weekdays") {
    return `Runs Monday through Friday at ${times}`;
  }
  if (schedule.scheduleType === "weekly") {
    const days = schedule.weekdays.length
      ? schedule.weekdays.map(weekdayShortLabel).join(", ")
      : "no weekdays";
    return `Runs ${days} at ${times}`;
  }
  if (schedule.scheduleType === "monthly") {
    const days = schedule.monthDays.length
      ? schedule.monthDays.map(monthDayLabel).join(", ")
      : "no month days";
    return `Runs monthly on day ${days} at ${times}`;
  }
  return `Runs every day at ${times}`;
}

function choiceButtonClass(active: boolean) {
  return cn(
    "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
    active
      ? "border-teal-600 bg-teal-50 text-teal-900 shadow-[inset_0_0_0_1px_rgb(13_148_136/0.12)]"
      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
  );
}

function frequencyButtonClass(active: boolean) {
  return cn(
    "inline-flex h-7 items-center justify-center rounded px-2.5 text-xs font-medium transition-colors",
    active
      ? "bg-white text-teal-950 shadow-sm ring-1 ring-slate-200"
      : "text-slate-500 hover:bg-white/70 hover:text-slate-900"
  );
}

function sectionPanelClass(extra?: string) {
  return cn("rounded-md border border-slate-200 bg-white", extra);
}

function sectionHeaderClass(extra?: string) {
  return cn("border-b border-slate-200 px-4 py-3", extra);
}

function fieldTextAreaClass(extra?: string) {
  return cn(
    "w-full resize-y rounded-md border border-input bg-white px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/15 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60",
    extra
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

function scheduledTaskRunHref(organizationId: string, workspaceId: string, runId: string) {
  return `/org/${encodeURIComponent(organizationId)}/workspace/${encodeURIComponent(
    workspaceId
  )}/scheduled-tasks/runs/${encodeURIComponent(runId)}`;
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
  const [activeSection, setActiveSection] = useState<EditorSectionId>("instructions");
  const [activeScheduleKey, setActiveScheduleKey] = useState<string | null>(
    () => form.schedules[0]?.key ?? null
  );
  const [isAddingSchedule, setIsAddingSchedule] = useState(false);
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
    const nextSchedule = newScheduleDraft(type, timezone);
    setForm({ ...form, schedules: [...form.schedules, nextSchedule] });
    setActiveScheduleKey(nextSchedule.key);
    setIsAddingSchedule(false);
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
    const schedules = form.schedules.filter((schedule) => schedule.key !== key);
    setForm({ ...form, schedules });
    if (activeScheduleKey === key) {
      setActiveScheduleKey(schedules[0]?.key ?? null);
    }
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

  const maxAttemptsInput = Number(form.maxAttempts || 0);
  const canSave = Boolean(
    form.name.trim() &&
      form.instructions.trim() &&
      form.selectedRoutes.length > 0 &&
      Number.isInteger(maxAttemptsInput) &&
      maxAttemptsInput >= 1 &&
      maxAttemptsInput <= 10 &&
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

  const invalidScheduleCount = form.schedules.filter(
    (schedule) => !scheduleDraftIsValid(schedule)
  ).length;
  const activeNotificationCount = Object.values(form.notificationRules).filter(Boolean).length;
  const failedRouteTests = Object.entries(routeTests).filter(
    ([key, state]) => form.selectedRoutes.includes(key) && state.status === "failed"
  );
  const selectedOutputLabels = form.selectedRoutes.map((key) =>
    routeLabelForKey(key, providerOptions)
  );
  const selectedNotificationLabels = form.notificationRoutes.map((key) =>
    routeLabelForKey(key, providerOptions)
  );
  const selectedApprovalLabels = form.approvalRoutes.map((key) =>
    routeLabelForKey(key, providerOptions)
  );
  const maxAttemptsValue = maxAttemptsInput;
  const canPreview = form.schedules.length > 0 && invalidScheduleCount === 0;
  const validationIssues = [
    !form.name.trim() ? "Task name is required." : null,
    !form.instructions.trim() ? "Instructions are required." : null,
    invalidScheduleCount > 0
      ? `${invalidScheduleCount} schedule${invalidScheduleCount === 1 ? "" : "s"} need attention.`
      : null,
    form.selectedRoutes.length === 0 ? "Select at least one output destination." : null,
    failedRouteTests.length > 0
      ? `${failedRouteTests.length} selected destination test${
          failedRouteTests.length === 1 ? "" : "s"
        } failed.`
      : null,
    !Number.isInteger(maxAttemptsValue) || maxAttemptsValue < 1 || maxAttemptsValue > 10
      ? "Attempts must be between 1 and 10."
      : null,
  ].filter((issue): issue is string => Boolean(issue));
  const sectionSummaries = {
    instructions: form.instructions.trim()
      ? `${form.name.trim() || "Unnamed"} · ${metricValue(form.instructions.trim().length)} chars`
      : `${form.name.trim() || "Unnamed"} · instructions required`,
    monitoring: form.monitoringConfig.enabled ? "Watch mode on" : "Standard run",
    notifications: `${activeNotificationCount} rules`,
    outputs: selectedOutputLabels.length
      ? `${selectedOutputLabels.length} destination${selectedOutputLabels.length === 1 ? "" : "s"}`
      : "No destination",
    review: validationIssues.length
      ? `${validationIssues.length} issue${validationIssues.length === 1 ? "" : "s"}`
      : "Ready",
    schedule:
      form.schedules.length > 0
        ? `${form.schedules.length} execution${form.schedules.length === 1 ? "" : "s"}`
        : "Manual",
  };
  const activeSchedule =
    form.schedules.find((schedule) => schedule.key === activeScheduleKey) ??
    form.schedules[0] ??
    null;
  const activeScheduleIndex = activeSchedule
    ? form.schedules.findIndex((schedule) => schedule.key === activeSchedule.key)
    : -1;
  const focusedMainWidth = cn(
    activeSection === "schedule"
      ? "max-w-7xl"
      : "max-w-6xl"
  );
  const activeSectionIndex = editorSections.findIndex((section) => section.id === activeSection);
  const nextSection = editorSections[activeSectionIndex + 1]?.id ?? "review";
  const isReviewSection = activeSection === "review";

  return (
    <form
      className="text-slate-950"
      id="scheduled-task-form"
      onSubmit={submitTask}
    >
      <div className="sticky top-0 z-20 -mx-2 border-b border-slate-200 bg-white/95 px-2 py-2 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <Button
              asChild
              className="size-8 border-transparent"
              size="icon"
              title="Back to scheduled tasks"
              variant="ghost"
            >
              <Link href={scheduledTasksHref}>
                <ArrowLeft className="size-4" />
              </Link>
            </Button>
            <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-600">
              <span
                className={cn(
                  "size-2 rounded-full",
                  form.isActive ? "bg-emerald-500" : "bg-slate-300"
                )}
              />
              {validationIssues.length ? (
                <Badge className="border-amber-200 bg-amber-50 text-amber-800" variant="outline">
                  {validationIssues.length} issue{validationIssues.length === 1 ? "" : "s"}
                </Badge>
              ) : (
                <Badge className="border-teal-200 bg-teal-50 text-teal-800" variant="outline">
                  Ready
                </Badge>
              )}
              <span className="hidden truncate md:inline">
                {sectionSummaries.schedule} · {sectionSummaries.outputs}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild size="sm" type="button" variant="ghost">
              <Link href={scheduledTasksHref}>Cancel</Link>
            </Button>
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
              Run test
            </Button>
            <Button
              className="bg-teal-700 text-white hover:bg-teal-800"
              disabled={isReviewSection ? !canSave || isSaving : isSaving}
              onClick={
                isReviewSection
                  ? undefined
                  : () => {
                      setActiveSection(nextSection);
                    }
              }
              size="sm"
              type={isReviewSection ? "submit" : "button"}
            >
              {isSaving ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : isReviewSection ? (
                <Save className="size-4" />
              ) : (
                <ArrowRight className="size-4" />
              )}
              {isReviewSection ? (editingTask ? "Save" : "Create") : "Next"}
            </Button>
          </div>
        </div>
        <nav className="mt-2 flex h-8 gap-5 overflow-x-auto border-t border-slate-200 pt-2 text-xs">
          {editorSections.map((section) => {
            const active = activeSection === section.id;
            return (
              <button
                className={cn(
                  "flex shrink-0 items-center border-b-2 px-0.5 pb-1 transition-colors",
                  active
                    ? "border-teal-600 text-slate-950"
                    : "border-transparent text-slate-500 hover:text-slate-900"
                )}
                aria-current={active ? "step" : undefined}
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                type="button"
              >
                <span className="font-medium">{section.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {feedback ? (
        <AsyncFeedback variant={feedback.variant}>{feedback.text}</AsyncFeedback>
      ) : null}

      <div className="pt-4">
        <main className={cn("min-w-0 space-y-4", focusedMainWidth)}>
          <section
            className={sectionPanelClass(activeSection === "instructions" ? undefined : "hidden")}
            id="task-instructions"
          >
            <div className={sectionHeaderClass("flex flex-wrap items-center justify-between gap-2")}>
              <div>
                <h2 className="text-sm font-semibold text-slate-950">Instructions</h2>
                <div className="mt-0.5 text-xs text-slate-500">
                  Task identity, run behavior, and assistant prompt.
                </div>
              </div>
              <button
                className={cn(
                  "inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-sm font-medium",
                  form.isActive
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-slate-100 text-slate-600"
                )}
                id="scheduled-task-active"
                onClick={() => setForm({ ...form, isActive: !form.isActive })}
                type="button"
              >
                {form.isActive ? <CheckCircle2 className="size-4" /> : <Pause className="size-4" />}
                {form.isActive ? "Active" : "Paused"}
              </button>
            </div>
            <div className="grid gap-5 p-4">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
                <div className="space-y-2">
                  <Label htmlFor="scheduled-task-name">Task name</Label>
                  <Input
                    className="bg-white"
                    id="scheduled-task-name"
                    maxLength={120}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                    placeholder="Daily SEO report"
                    required
                    value={form.name}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label htmlFor="scheduled-task-max-attempts">Attempts</Label>
                    <Input
                      className="bg-white"
                      id="scheduled-task-max-attempts"
                      max={10}
                      min={1}
                      onChange={(event) => setForm({ ...form, maxAttempts: event.target.value })}
                      type="number"
                      value={form.maxAttempts}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="scheduled-task-conversation-policy">Chat history</Label>
                    <Select
                      onValueChange={(value) =>
                        setForm({ ...form, conversationPolicy: value as ConversationPolicy })
                      }
                      value={form.conversationPolicy}
                    >
                      <SelectTrigger className="bg-white" id="scheduled-task-conversation-policy">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="reuse">Reuse</SelectItem>
                        <SelectItem value="new_each_run">New each run</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="scheduled-task-instructions">Prompt</Label>
                <textarea
                  className={fieldTextAreaClass("min-h-[360px] font-sans leading-6")}
                  id="scheduled-task-instructions"
                  maxLength={20000}
                  onChange={(event) => setForm({ ...form, instructions: event.target.value })}
                  required
                  value={form.instructions}
                />
              </div>
            </div>
          </section>

          <section
            className={sectionPanelClass(activeSection === "schedule" ? undefined : "hidden")}
            id="task-schedule"
          >
            <div className={sectionHeaderClass("flex items-start justify-between gap-3")}>
              <div>
                <h2 className="text-sm font-semibold text-slate-950">Schedule Configuration</h2>
                <div className="mt-0.5 text-xs text-slate-500">{sectionSummaries.schedule}</div>
              </div>
              <Badge className="border-slate-200 bg-white text-slate-600" variant="outline">
                {form.schedules.length === 0 ? "Manual" : `${form.schedules.length} active`}
              </Badge>
            </div>
            <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="grid min-w-0 gap-4">
              {form.schedules.length > 1 ? (
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {form.schedules.map((schedule, index) => {
                    const active = activeSchedule?.key === schedule.key;
                    return (
                      <button
                        className={cn(
                          "grid min-w-48 shrink-0 gap-0.5 rounded-md border px-3 py-2 text-left text-xs transition-colors",
                          active
                            ? "border-teal-300 bg-teal-50 text-teal-950"
                            : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                        )}
                        key={schedule.key}
                        onClick={() => setActiveScheduleKey(schedule.key)}
                        type="button"
                      >
                        <span className="truncate font-medium">
                          {scheduleDisplayName(schedule, index)}
                        </span>
                        <span className="truncate text-slate-500">
                          {scheduleDraftSummary(schedule)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {form.schedules.length === 0 ? (
                <div className="flex min-h-24 items-center gap-3 rounded-md border border-dashed border-slate-300 bg-slate-50 px-4 text-sm text-slate-600">
                  <Play className="size-4" />
                  <span>Manual run only</span>
                </div>
              ) : null}

              {activeSchedule ? (
                <div
                  className="overflow-hidden rounded-md border border-slate-200 bg-white"
                  key={activeSchedule.key}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3 bg-slate-50 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <Label
                        className="text-[11px] font-semibold uppercase text-slate-500"
                        htmlFor={`schedule-name-${activeSchedule.key}`}
                      >
                        Schedule condition
                      </Label>
                      <Input
                        className="mt-1 h-8 max-w-sm border-slate-200 bg-white text-sm font-medium"
                        id={`schedule-name-${activeSchedule.key}`}
                        maxLength={120}
                        onChange={(event) =>
                          updateSchedule(activeSchedule.key, { name: event.target.value })
                        }
                        placeholder={`Execution ${activeScheduleIndex + 1}`}
                        value={activeSchedule.name}
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        className={cn(
                          "inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-xs font-medium",
                          activeSchedule.isActive
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : "border-slate-200 bg-white text-slate-500"
                        )}
                        onClick={() =>
                          updateSchedule(activeSchedule.key, { isActive: !activeSchedule.isActive })
                        }
                        type="button"
                      >
                        {activeSchedule.isActive ? "On" : "Off"}
                      </button>
                      <Button
                        className="border-transparent text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                        onClick={() => removeSchedule(activeSchedule.key)}
                        size="icon"
                        title="Remove schedule"
                        type="button"
                        variant="ghost"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="grid gap-4 border-t border-slate-200 p-4">
                    <div className="grid gap-2">
                      <Label>Frequency</Label>
                      <div className="inline-flex w-fit max-w-full flex-wrap gap-1 rounded-md bg-slate-100 p-1">
                        {schedulePresets.map((preset) => (
                          <button
                            className={frequencyButtonClass(
                              activeSchedule.scheduleType === preset.type
                            )}
                            key={preset.type}
                            onClick={() => {
                              const defaults = newScheduleDraft(
                                preset.type,
                                activeSchedule.timezone
                              );
                              updateSchedule(activeSchedule.key, {
                                cronExpression: defaults.cronExpression,
                                everyMinutes: defaults.everyMinutes,
                                monthDays: defaults.monthDays,
                                scheduleType: preset.type,
                                times: defaults.times,
                                weekdays: defaults.weekdays,
                              });
                            }}
                            type="button"
                          >
                            {preset.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 rounded-md border border-teal-100 bg-teal-50 px-3 py-2 text-sm text-teal-900">
                      <CalendarClock className="size-4 shrink-0" />
                      <span className="min-w-0 truncate">{scheduleDraftSummary(activeSchedule)}</span>
                    </div>

                    {activeSchedule.scheduleType === "interval" ? (
                      <div className="space-y-2">
                        <Label htmlFor={`schedule-interval-${activeSchedule.key}`}>
                          Every minutes
                        </Label>
                        <Input
                          className="max-w-48 bg-white"
                          id={`schedule-interval-${activeSchedule.key}`}
                          max={10080}
                          min={1}
                          onChange={(event) =>
                            updateSchedule(activeSchedule.key, {
                              everyMinutes: event.target.value,
                            })
                          }
                          type="number"
                          value={activeSchedule.everyMinutes}
                        />
                      </div>
                    ) : null}

                    {activeSchedule.scheduleType === "cron" ? (
                      <div className="space-y-2">
                        <Label htmlFor={`schedule-cron-${activeSchedule.key}`}>
                          Cron expression
                        </Label>
                        <Input
                          className="font-mono bg-white"
                          id={`schedule-cron-${activeSchedule.key}`}
                          onChange={(event) =>
                            updateSchedule(activeSchedule.key, {
                              cronExpression: event.target.value,
                            })
                          }
                          placeholder="0 9 * * 1-5"
                          value={activeSchedule.cronExpression}
                        />
                      </div>
                    ) : null}

                    {activeSchedule.scheduleType !== "interval" &&
                    activeSchedule.scheduleType !== "cron" ? (
                      <div className="grid gap-2">
                        <Label>Run times</Label>
                        <div className="flex flex-wrap items-center gap-2">
                          {activeSchedule.times.map((timeValue) => (
                            <button
                              className="inline-flex h-8 items-center gap-2 rounded-md border border-teal-200 bg-teal-50 px-2.5 text-xs font-medium text-teal-900"
                              key={timeValue}
                              onClick={() => removeRunTime(activeSchedule, timeValue)}
                              type="button"
                            >
                              {timeValue}
                              <X className="size-3" />
                            </button>
                          ))}
                          <Input
                            className="h-8 w-28 bg-white text-xs"
                            onChange={(event) =>
                              updateSchedule(activeSchedule.key, { timeInput: event.target.value })
                            }
                            type="time"
                            value={activeSchedule.timeInput}
                          />
                          <Button
                            onClick={() => addRunTime(activeSchedule)}
                            size="sm"
                            type="button"
                            variant="outline"
                          >
                            <Plus className="size-4" />
                            Add
                          </Button>
                        </div>
                      </div>
                    ) : null}

                    {activeSchedule.scheduleType === "weekly" ? (
                      <div className="grid gap-2">
                        <Label>Weekdays</Label>
                        <div className="flex flex-wrap gap-1.5">
                          {weekdays.map((weekday) => (
                            <button
                              className={choiceButtonClass(
                                activeSchedule.weekdays.includes(weekday.value)
                              )}
                              key={weekday.value}
                              onClick={() =>
                                toggleValue(activeSchedule, "weekdays", weekday.value)
                              }
                              type="button"
                            >
                              {weekday.label.slice(0, 3)}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {activeSchedule.scheduleType === "weekdays" ? (
                      <div className="grid gap-2">
                        <Label>Weekdays</Label>
                        <div className="flex flex-wrap gap-1.5">
                          {["Mon", "Tue", "Wed", "Thu", "Fri"].map((weekday) => (
                            <span
                              className="inline-flex h-8 items-center rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-medium text-slate-600"
                              key={weekday}
                            >
                              {weekday}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {activeSchedule.scheduleType === "monthly" ? (
                      <div className="grid gap-2">
                        <Label>Month days</Label>
                        <div className="grid grid-cols-7 gap-1 sm:grid-cols-10">
                          {Array.from({ length: 31 }, (_, day) => String(day + 1)).map((day) => (
                            <button
                              className={choiceButtonClass(activeSchedule.monthDays.includes(day))}
                              key={day}
                              onClick={() => toggleValue(activeSchedule, "monthDays", day)}
                              type="button"
                            >
                              {day}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="grid gap-4 md:grid-cols-[minmax(220px,280px)_1fr]">
                      <div className="space-y-2">
                        <Label htmlFor={`schedule-timezone-${activeSchedule.key}`}>Timezone</Label>
                        <Select
                          onValueChange={(value) =>
                            updateSchedule(activeSchedule.key, { timezone: value })
                          }
                          value={activeSchedule.timezone}
                        >
                          <SelectTrigger
                            className="bg-white"
                            id={`schedule-timezone-${activeSchedule.key}`}
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {timezoneOptions.includes(activeSchedule.timezone) ? null : (
                              <SelectItem value={activeSchedule.timezone}>
                                {activeSchedule.timezone}
                              </SelectItem>
                            )}
                            {timezoneOptions.map((timezone) => (
                              <SelectItem key={timezone} value={timezone}>
                                {timezone}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-2">
                          <Label htmlFor={`schedule-start-${activeSchedule.key}`}>Start</Label>
                          <Input
                            className="bg-white"
                            id={`schedule-start-${activeSchedule.key}`}
                            onChange={(event) =>
                              updateSchedule(activeSchedule.key, { startsAt: event.target.value })
                            }
                            type="datetime-local"
                            value={activeSchedule.startsAt}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor={`schedule-end-${activeSchedule.key}`}>End</Label>
                          <Input
                            className="bg-white"
                            id={`schedule-end-${activeSchedule.key}`}
                            onChange={(event) =>
                              updateSchedule(activeSchedule.key, { endsAt: event.target.value })
                            }
                            type="datetime-local"
                            value={activeSchedule.endsAt}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}

              <details
                className="group rounded-md border border-dashed border-slate-300 bg-white"
                onToggle={(event) => setIsAddingSchedule(event.currentTarget.open)}
                open={isAddingSchedule}
              >
                <summary className="flex cursor-pointer list-none items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 group-open:border-b group-open:border-slate-200">
                  <Plus className="size-4" />
                  Add schedule condition
                </summary>
                <div className="flex flex-wrap justify-center gap-2 p-3">
                  <Button
                    onClick={() => {
                      setForm({ ...form, schedules: [] });
                      setActiveScheduleKey(null);
                      setIsAddingSchedule(false);
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Play className="size-4" />
                    Manual
                  </Button>
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
              </details>
              </div>
              <div className="grid gap-4 self-start">
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs font-semibold uppercase text-slate-500">
                      Next 5 runs
                    </div>
                    <Button
                      className="h-8 bg-white"
                      disabled={isPreviewing || !canPreview}
                      onClick={previewSchedules}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {isPreviewing ? (
                        <RefreshCw className="size-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="size-3.5" />
                      )}
                      Preview
                    </Button>
                  </div>
                  {previewRuns.length > 0 ? (
                    <div className="mt-3 grid gap-1 text-sm">
                      {previewRuns.map((run) => (
                        <div
                          className="rounded-md bg-white px-2 py-1.5 text-slate-700"
                          key={run}
                        >
                          {formatDate(run)}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3 rounded-md border border-dashed border-slate-300 bg-white px-3 py-3 text-sm text-slate-500">
                      No upcoming runs.
                    </div>
                  )}
                </div>

                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Delivery</div>
                  <div className="mt-3 grid gap-3 text-sm">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <div className="text-xs text-slate-500">Attempts</div>
                        <div className="mt-1 font-medium text-slate-900">{form.maxAttempts}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500">Chat history</div>
                        <div className="mt-1 font-medium text-slate-900">
                          {form.conversationPolicy === "reuse" ? "Reuse" : "New each run"}
                        </div>
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Outputs</div>
                      {selectedOutputLabels.length > 0 ? (
                        <div className="mt-1 grid gap-1">
                          {selectedOutputLabels.map((label) => (
                            <div
                              className="min-w-0 truncate rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600"
                              key={label}
                              title={label}
                            >
                              {label}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-1 text-sm text-slate-500">None selected</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section
            className={sectionPanelClass(activeSection === "outputs" ? undefined : "hidden")}
            id="task-outputs"
          >
            <div className={sectionHeaderClass("flex flex-wrap items-center justify-between gap-2")}>
              <div>
                <h2 className="text-sm font-semibold text-slate-950">Outputs</h2>
                <div className="mt-0.5 text-xs text-slate-500">{sectionSummaries.outputs}</div>
              </div>
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
                Test selected
              </Button>
            </div>
            <div className="grid gap-2 p-4">
              <div className="flex min-h-12 items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
                <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                  <input
                    checked={form.selectedRoutes.includes("chat")}
                    className="size-4 accent-teal-700"
                    onChange={() => toggleRoute("chat")}
                    type="checkbox"
                  />
                  <MessageSquare className="size-4 text-slate-500" />
                  <span className="font-medium text-slate-800">Built-in chat</span>
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
                  className="flex min-h-14 items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                  key={option.key}
                >
                  <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                    <input
                      checked={form.selectedRoutes.includes(option.key)}
                      className="size-4 accent-teal-700"
                      onChange={() => toggleRoute(option.key)}
                      type="checkbox"
                    />
                    <Webhook className="size-4 text-slate-500" />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-slate-800">
                        {option.label}
                      </span>
                      <span className="block truncate text-xs text-slate-500">{option.source}</span>
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
                <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-sm text-slate-600">
                  Connect a provider and receive a message before selecting an external route.
                </div>
              ) : null}
              {failedRouteTests.length > 0 ? (
                <div className="grid gap-1 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {failedRouteTests.map(([key, state]) => (
                    <div className="min-w-0 truncate" key={key}>
                      {routeLabelForKey(key, providerOptions)}: {state.error || "Test failed."}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </section>

          <section
            className={sectionPanelClass(
              activeSection === "notifications" ? undefined : "hidden"
            )}
            id="task-notifications"
          >
            <div className={sectionHeaderClass()}>
              <h2 className="text-sm font-semibold text-slate-950">Notifications</h2>
              <div className="mt-0.5 text-xs text-slate-500">
                {activeNotificationCount} enabled rule{activeNotificationCount === 1 ? "" : "s"}
              </div>
            </div>
            <div className="grid gap-4 p-4">
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                {notificationRuleOptions.map((option) => (
                  <button
                    className={cn(
                      "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm transition-colors",
                      form.notificationRules[option.key]
                        ? "border-teal-200 bg-teal-50 text-teal-900"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    )}
                    key={option.key}
                    onClick={() => toggleNotificationRule(option.key)}
                    type="button"
                  >
                    <span>{option.label}</span>
                    {form.notificationRules[option.key] ? (
                      <CheckCircle2 className="size-4" />
                    ) : null}
                  </button>
                ))}
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-md border border-slate-200 bg-white">
                  <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
                    <div className="text-sm font-medium text-slate-900">Notification route</div>
                    <Badge variant="secondary">{form.notificationRoutes.length}</Badge>
                  </div>
                  <div className="grid gap-2 p-3">
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-white px-3 text-sm">
                      <input
                        checked={form.notificationRoutes.includes("chat")}
                        className="size-4 accent-teal-700"
                        onChange={() => toggleNotificationRoute("chat")}
                        type="checkbox"
                      />
                      <MessageSquare className="size-4 text-slate-500" />
                      <span>Built-in chat</span>
                    </label>
                    {providerOptions.map((option) => (
                      <label
                        className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-white px-3 text-sm"
                        key={option.key}
                      >
                        <input
                          checked={form.notificationRoutes.includes(option.key)}
                          className="size-4 accent-teal-700"
                          onChange={() => toggleNotificationRoute(option.key)}
                          type="checkbox"
                        />
                        <Webhook className="size-4 text-slate-500" />
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{option.label}</span>
                          <span className="block truncate text-xs text-slate-500">
                            {option.source}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-md border border-slate-200 bg-white">
                  <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
                    <div className="text-sm font-medium text-slate-900">Approval route</div>
                    <Badge variant="secondary">{form.approvalRoutes.length}</Badge>
                  </div>
                  <div className="grid gap-2 p-3">
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-white px-3 text-sm">
                      <input
                        checked={form.approvalRoutes.includes("chat")}
                        className="size-4 accent-teal-700"
                        onChange={() => toggleApprovalRoute("chat")}
                        type="checkbox"
                      />
                      <MessageSquare className="size-4 text-slate-500" />
                      <span>Built-in chat</span>
                    </label>
                    {providerOptions.map((option) => (
                      <label
                        className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-white px-3 text-sm"
                        key={option.key}
                      >
                        <input
                          checked={form.approvalRoutes.includes(option.key)}
                          className="size-4 accent-teal-700"
                          onChange={() => toggleApprovalRoute(option.key)}
                          type="checkbox"
                        />
                        <ShieldCheck className="size-4 text-slate-500" />
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{option.label}</span>
                          <span className="block truncate text-xs text-slate-500">
                            {option.source}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">
                  How notifications work
                </div>
                <div className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2 xl:grid-cols-3">
                  <div>
                    <div className="font-medium text-slate-900">Failure</div>
                    <p className="mt-1">
                      Sends a notification when the assistant run fails before producing a usable
                      result.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Waiting approval</div>
                    <p className="mt-1">
                      Sends approval requests to the approval route when a tool call needs a human
                      decision.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">No output</div>
                    <p className="mt-1">
                      Sends a notification when the run completes but has nothing meaningful to
                      deliver.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Delivery failure</div>
                    <p className="mt-1">
                      Sends a notification when the assistant succeeds but one or more selected
                      destinations fail.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Meaningful update</div>
                    <p className="mt-1">
                      Sends a notification only when monitoring finds a meaningful change from the
                      saved baseline.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Routes</div>
                    <p className="mt-1">
                      Notification routes receive status updates. Approval routes receive pending
                      approval prompts.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section
            className={sectionPanelClass(activeSection === "monitoring" ? undefined : "hidden")}
            id="task-monitoring"
          >
            <div className={sectionHeaderClass("flex flex-wrap items-center justify-between gap-2")}>
              <div>
                <h2 className="text-sm font-semibold text-slate-950">Monitoring</h2>
                <div className="mt-0.5 text-xs text-slate-500">
                  {sectionSummaries.monitoring}
                </div>
              </div>
              <Badge variant={form.monitoringConfig.enabled ? "success" : "secondary"}>
                {form.monitoringConfig.enabled ? "On" : "Off"}
              </Badge>
            </div>
            <div className="grid gap-4 p-4">
              <div className="grid gap-2 md:grid-cols-4">
                {[
                  {
                    active: form.monitoringConfig.enabled,
                    disabled: false,
                    icon: CheckCircle2,
                    label: "Watch mode",
                    onClick: () =>
                      updateMonitoringConfig({ enabled: !form.monitoringConfig.enabled }),
                  },
                  {
                    active: form.monitoringConfig.notifyOnChange,
                    disabled: !form.monitoringConfig.enabled,
                    icon: BellRing,
                    label: "Notify on change",
                    onClick: () =>
                      updateMonitoringConfig({
                        notifyOnChange: !form.monitoringConfig.notifyOnChange,
                      }),
                  },
                  {
                    active: form.monitoringConfig.deliverOnChangeOnly,
                    disabled: !form.monitoringConfig.enabled,
                    icon: Route,
                    label: "Deliver on change",
                    onClick: () =>
                      updateMonitoringConfig({
                        deliverOnChangeOnly: !form.monitoringConfig.deliverOnChangeOnly,
                      }),
                  },
                  {
                    active: form.monitoringConfig.baselineOnFirstRun,
                    disabled: !form.monitoringConfig.enabled,
                    icon: CheckCircle2,
                    label: "Baseline first run",
                    onClick: () =>
                      updateMonitoringConfig({
                        baselineOnFirstRun: !form.monitoringConfig.baselineOnFirstRun,
                      }),
                  },
                ].map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      className={cn(
                        "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm transition-colors disabled:cursor-not-allowed",
                        item.disabled
                          ? "border-slate-200 bg-slate-50 text-slate-400"
                          : item.active
                            ? "border-teal-200 bg-teal-50 text-teal-900"
                            : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      )}
                      disabled={item.disabled}
                      key={item.label}
                      onClick={item.onClick}
                      type="button"
                    >
                      <span>{item.label}</span>
                      <Icon className="size-4" />
                    </button>
                  );
                })}
              </div>

              {form.monitoringConfig.enabled ? (
                <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
                  <div className="grid gap-3 rounded-md border border-slate-200 bg-white p-3 md:grid-cols-4">
                    <button
                      className={cn(
                        "flex min-h-10 items-center justify-between gap-2 rounded-md border px-3 text-left text-sm",
                        form.monitoringConfig.stopAfterFirstChange
                          ? "border-teal-200 bg-teal-50 text-teal-900"
                          : "border-slate-200 bg-white text-slate-600"
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
                        className="bg-white"
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
                        className="bg-white"
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
                        className="bg-white"
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
                    <div className="grid gap-3 rounded-md border border-slate-200 bg-white p-3">
                      <div className="grid grid-cols-2 gap-3 text-sm">
                        <div>
                          <div className="text-xs text-slate-500">State</div>
                          <div className="mt-1 font-medium">{taskMonitoringLabel(editingTask)}</div>
                        </div>
                        <div>
                          <div className="text-xs text-slate-500">Changes</div>
                          <div className="mt-1 font-medium">
                            {metricValue(monitoringChangeCount(editingTask))}
                          </div>
                        </div>
                      </div>
                      <label className="flex min-h-10 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-white px-3 text-sm">
                        <input
                          checked={form.resetMonitoringState}
                          className="size-4 accent-teal-700"
                          onChange={() =>
                            setForm({
                              ...form,
                              resetMonitoringState: !form.resetMonitoringState,
                            })
                          }
                          type="checkbox"
                        />
                        <RefreshCw className="size-4 text-slate-500" />
                        <span>Reset baseline</span>
                      </label>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">
                  How monitoring works
                </div>
                <div className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2 xl:grid-cols-3">
                  <div>
                    <div className="font-medium text-slate-900">Watch mode</div>
                    <p className="mt-1">
                      Compares each run against the saved baseline and records whether something
                      meaningful changed.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Notify on change</div>
                    <p className="mt-1">
                      Uses the notification route when a change is detected. No-change runs stay
                      quiet.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Deliver on change</div>
                    <p className="mt-1">
                      Sends output destinations only when the result changed, instead of delivering
                      every run.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Baseline first run</div>
                    <p className="mt-1">
                      Treats the first run as the starting snapshot, then compares later runs
                      against it.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Stop conditions</div>
                    <p className="mt-1">
                      Pauses the task after a selected number of changes, total runs, unchanged
                      runs, or the first change.
                    </p>
                  </div>
                  <div>
                    <div className="font-medium text-slate-900">Reset baseline</div>
                    <p className="mt-1">
                      Clears the stored comparison state so the next run can establish a fresh
                      baseline.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>
          <section
            className={sectionPanelClass(activeSection === "review" ? undefined : "hidden")}
            id="task-review"
          >
            <div className={sectionHeaderClass("flex flex-wrap items-center justify-between gap-2")}>
              <div>
                <h2 className="text-sm font-semibold text-slate-950">Review</h2>
                <div className="mt-0.5 text-xs text-slate-500">{sectionSummaries.review}</div>
              </div>
              <Button
                className="h-8 bg-white"
                disabled={isPreviewing || !canPreview}
                onClick={previewSchedules}
                size="sm"
                type="button"
                variant="outline"
              >
                {isPreviewing ? (
                  <RefreshCw className="size-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="size-3.5" />
                )}
                Preview runs
              </Button>
            </div>
            <div className="grid gap-4 p-4 lg:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="grid gap-4">
                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Summary</div>
                  <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                    <div>
                      <div className="text-xs text-slate-500">Schedules</div>
                      <div className="mt-1 font-medium text-slate-900">
                        {sectionSummaries.schedule}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Attempts</div>
                      <div className="mt-1 font-medium text-slate-900">{form.maxAttempts}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Chat history</div>
                      <div className="mt-1 font-medium text-slate-900">
                        {form.conversationPolicy === "reuse" ? "Reuse" : "New each run"}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Monitoring</div>
                      <div className="mt-1 font-medium text-slate-900">
                        {form.monitoringConfig.enabled ? "On" : "Off"}
                      </div>
                    </div>
                  </div>
                </div>

                {validationIssues.length > 0 ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
                    <div className="text-xs font-semibold uppercase text-amber-800">
                      Validation
                    </div>
                    <div className="mt-3 grid gap-2">
                      {validationIssues.map((issue) => (
                        <div
                          className="rounded-md border border-amber-200 bg-white px-3 py-2 text-sm text-amber-900"
                          key={issue}
                        >
                          {issue}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Routing</div>
                  <div className="mt-3 grid gap-3 text-xs text-slate-600 sm:grid-cols-2">
                    <div>
                      <div className="mb-1 text-slate-500">Notifications</div>
                      <div className="grid gap-1">
                        {selectedNotificationLabels.length ? (
                          selectedNotificationLabels.map((label) => (
                            <div
                              className="min-w-0 truncate rounded-md bg-slate-50 px-2 py-1"
                              key={label}
                              title={label}
                            >
                              {label}
                            </div>
                          ))
                        ) : (
                          <span>None</span>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="mb-1 text-slate-500">Approvals</div>
                      <div className="grid gap-1">
                        {selectedApprovalLabels.length ? (
                          selectedApprovalLabels.map((label) => (
                            <div
                              className="min-w-0 truncate rounded-md bg-slate-50 px-2 py-1"
                              key={label}
                              title={label}
                            >
                              {label}
                            </div>
                          ))
                        ) : (
                          <span>None</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 self-start">
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Next 5 runs</div>
                  {previewRuns.length > 0 ? (
                    <div className="mt-3 grid gap-1 text-sm">
                      {previewRuns.map((run) => (
                        <div
                          className="rounded-md bg-white px-2 py-1.5 text-slate-700"
                          key={run}
                        >
                          {formatDate(run)}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3 rounded-md border border-dashed border-slate-300 bg-white px-3 py-3 text-sm text-slate-500">
                      No upcoming runs.
                    </div>
                  )}
                </div>

                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Outputs</div>
                  {selectedOutputLabels.length > 0 ? (
                    <div className="mt-3 grid gap-1.5">
                      {selectedOutputLabels.map((label) => (
                        <div
                          className="min-w-0 truncate rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600"
                          key={label}
                          title={label}
                        >
                          {label}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3 text-sm text-slate-500">None selected</div>
                  )}
                </div>
              </div>
            </div>
          </section>
        </main>

      </div>
    </form>
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
  const [busyRunId, setBusyRunId] = useState<string | null>(null);
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
          row.id === updatedRun.taskId
            ? {
                ...row,
                lastError: updatedRun.error,
                lastRunAt: updatedRun.scheduledFor,
                lastStatus: updatedRun.status,
                lastTaskRunId: updatedRun.id,
              }
            : row
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

  async function cancelRun(run: WorkspaceScheduledTaskRunRead) {
    const task = taskRows.find((row) => row.id === run.taskId);
    if (!window.confirm(`Cancel ${task?.name ?? "this scheduled run"}?`)) {
      return;
    }
    setBusyRunId(run.id);
    setFeedback(null);
    try {
      const updatedRun = await workspaceScheduledTasksCancelRun(
        organizationId,
        workspaceId,
        run.taskId,
        run.id
      );
      setRunRows((current) =>
        current.map((row) => (row.id === updatedRun.id ? updatedRun : row))
      );
      setTaskRows((current) =>
        current.map((row) =>
          row.lastTaskRunId === updatedRun.id ? { ...row, lastStatus: updatedRun.status } : row
        )
      );
      setFeedback({ variant: "success", text: "Scheduled run canceled." });
      router.refresh();
    } catch (error) {
      setFeedback({
        variant: "error",
        text: error instanceof Error ? error.message : "Could not cancel scheduled run.",
      });
    } finally {
      setBusyRunId(null);
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
              const runDetailHref = scheduledTaskRunHref(organizationId, workspaceId, run.id);
              const runRowClassName = cn(
                "relative grid gap-3 rounded-md border border-border px-3 py-2 text-sm md:grid-cols-[minmax(0,1fr)_150px_150px_130px_230px]",
                "transition-colors hover:border-teal-300 hover:bg-teal-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
              );
              const rowContent = (
                <>
                  <Link
                    aria-label={`Open scheduled task run ${run.id}`}
                    className="absolute inset-0 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                    href={runDetailHref}
                  />
                  <div className="pointer-events-none relative z-10 min-w-0">
                    <div className="truncate font-medium">{task?.name ?? "Scheduled task"}</div>
                    <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                      {run.id}
                    </div>
                  </div>
                  <div className="pointer-events-none relative z-10">
                    <div className="text-xs text-muted-foreground">Scheduled</div>
                    <div className="mt-0.5">{formatDate(run.scheduledFor)}</div>
                  </div>
                  <div className="pointer-events-none relative z-10">
                    <div className="text-xs text-muted-foreground">Output</div>
                    <div className="mt-0.5">{runOutputLabel(run)}</div>
                  </div>
                  <div className="pointer-events-none relative z-10">
                    <div className="text-xs text-muted-foreground">Notifications</div>
                    <div className="mt-0.5">
                      {String(run.notifications?.length ?? 0)} routed
                    </div>
                  </div>
                  <div className="pointer-events-none relative z-10 flex flex-wrap items-center justify-start gap-2 md:justify-end">
                    <Badge variant={statusVariant(run.status)}>{statusLabel(run.status)}</Badge>
                    <span
                      aria-hidden="true"
                      className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground"
                    >
                      <Clock3 className="size-4" />
                    </span>
                    {canCancelRun(run) ? (
                      <Button
                        className="pointer-events-auto"
                        disabled={busyRunId === run.id}
                        onClick={() => cancelRun(run)}
                        size="sm"
                        title="Cancel scheduled run"
                        variant="outline"
                      >
                        {busyRunId === run.id ? (
                          <RefreshCw className="size-4 animate-spin" />
                        ) : (
                          <X className="size-4" />
                        )}
                        Cancel run
                      </Button>
                    ) : null}
                  </div>
                </>
              );
              return (
                <div className="space-y-2" key={run.id}>
                  <div className={runRowClassName}>
                    {rowContent}
                  </div>
                  {retryableDeliveries.length > 0 ? (
                    <div className="grid gap-2">
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
