export type DateTimeInput = string | null | undefined;

export const userDateTimeOptions: Intl.DateTimeFormatOptions = {
  dateStyle: "medium",
  timeStyle: "short",
};

export const userDateTimeWithSecondsOptions: Intl.DateTimeFormatOptions = {
  dateStyle: "medium",
  timeStyle: "medium",
};

export const userShortDateTimeOptions: Intl.DateTimeFormatOptions = {
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  month: "short",
};

export const userShortDateOptions: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
};

export const userDateOptions: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
};

function twoDigit(value: number) {
  return String(value).padStart(2, "0");
}

function parseInstant(value: DateTimeInput) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatWithOptions(
  date: Date,
  options: Intl.DateTimeFormatOptions,
  locale?: string | string[],
) {
  return new Intl.DateTimeFormat(locale, options).format(date);
}

export function formatUserDateTime(
  value: DateTimeInput,
  fallback = "Not set",
  options: Intl.DateTimeFormatOptions = userDateTimeOptions,
  locale?: string | string[],
) {
  const date = parseInstant(value);
  return date ? formatWithOptions(date, options, locale) : fallback;
}

export function formatUserShortDateTime(value: DateTimeInput, fallback = "Unknown") {
  return formatUserDateTime(value, fallback, userShortDateTimeOptions, "en-US");
}

export function formatUserShortDate(value: DateTimeInput, fallback = "Unknown") {
  return formatUserDateTime(value, fallback, userShortDateOptions, "en-US");
}

export function formatUserDate(value: DateTimeInput, fallback = "Unknown") {
  return formatUserDateTime(value, fallback, userDateOptions, "en-US");
}

export function formatUserDateTimeInputValue(value: DateTimeInput) {
  const date = parseInstant(value);
  if (!date) {
    return "";
  }
  return `${date.getFullYear()}-${twoDigit(date.getMonth() + 1)}-${twoDigit(
    date.getDate()
  )}T${twoDigit(date.getHours())}:${twoDigit(date.getMinutes())}`;
}

export function parseUserDateTimeInputValue(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const date = new Date(trimmed);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function parseLocalDate(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return parseInstant(value);
  }
  const [, year, month, day] = match;
  return new Date(Number(year), Number(month) - 1, Number(day));
}

export function formatUserDateBucket(
  value: string,
  options: Intl.DateTimeFormatOptions = userShortDateOptions,
  locale?: string | string[],
) {
  const date = parseLocalDate(value);
  return date ? formatWithOptions(date, options, locale) : "Unknown";
}
