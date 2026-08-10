import {
  formatUserDateTimeInputValue,
  parseUserDateTimeInputValue,
} from "@/lib/date-time";

export type ScheduleEntryType =
  | "interval"
  | "daily"
  | "weekly"
  | "weekdays"
  | "monthly"
  | "cron";

export type ScheduleDraft = {
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

const timezoneAliases: Record<string, string> = {
  "Asia/Calcutta": "Asia/Kolkata",
};

export function normalizeTimezone(value: string) {
  const timezone = value.trim() || "UTC";
  return timezoneAliases[timezone] ?? timezone;
}

export function browserTimezone() {
  try {
    return normalizeTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  } catch {
    return "UTC";
  }
}

export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function configString(config: unknown, key: string, fallback: string) {
  const value = record(config)[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

export function configNumber(config: unknown, key: string, fallback: number) {
  const value = record(config)[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return String(fallback);
}

export function configNumberList(
  config: unknown,
  pluralKey: string,
  singularKey: string,
  fallback: number[]
) {
  const source = record(config);
  const rawValue = source[pluralKey] ?? source[singularKey];
  const values = Array.isArray(rawValue)
    ? rawValue
    : rawValue === undefined
      ? fallback
      : [rawValue];
  const normalized = values
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value))
    .map((value) => String(value));
  return normalized.length ? Array.from(new Set(normalized)) : fallback.map(String);
}

export function configTimes(config: unknown, fallback = ["09:00"]) {
  const source = record(config);
  const rawValue = source.times ?? source.time;
  const values = Array.isArray(rawValue)
    ? rawValue
    : typeof rawValue === "string"
      ? [rawValue]
      : fallback;
  const normalized = values
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter(Boolean);
  return normalized.length ? Array.from(new Set(normalized)).sort() : fallback;
}

export function datetimeLocalValue(value?: string | null) {
  return formatUserDateTimeInputValue(value);
}

export function datetimeLocalToIso(value: string) {
  return parseUserDateTimeInputValue(value);
}

function scheduleKey() {
  return `schedule-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function newScheduleDraft(
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

export function scheduleDraftConfig(draft: ScheduleDraft): Record<string, unknown> {
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

export function scheduleDraftIsValid(draft: ScheduleDraft) {
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
