import { Package, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

export function runtimeDisplayName(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "remote" || normalized === "streamable-http" || normalized === "sse") {
    return "Remote API";
  }
  if (normalized === "uvx") {
    return "UVX";
  }
  if (normalized === "npm") {
    return "NPM";
  }
  if (normalized === "pypi") {
    return "PyPI";
  }
  if (normalized === "oci") {
    return "OCI";
  }
  return value || "Package";
}

export function runtimeBadgeClass(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized.includes("http") || normalized.includes("sse")) {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }
  if (normalized === "uvx" || normalized.includes("pypi")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (normalized === "npm") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (normalized === "oci") {
    return "border-violet-200 bg-violet-50 text-violet-700";
  }
  if (normalized.includes("remote")) {
    return "border-cyan-200 bg-cyan-50 text-cyan-700";
  }
  return "border-slate-200 bg-slate-100 text-slate-700";
}

export function serverIconUrlFromIcons(icons: unknown[] | undefined) {
  const icon = icons?.find((candidate) => {
    const src = (candidate as Record<string, unknown>).src;
    return typeof src === "string" && src.trim();
  }) as Record<string, unknown> | undefined;

  return typeof icon?.src === "string" ? icon.src : "";
}

type FeedbackMessagesProps = {
  error?: string;
  notice?: string;
};

export function FeedbackMessages({ error, notice }: FeedbackMessagesProps) {
  return (
    <>
      {error ? (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}
    </>
  );
}

type McpTableCardProps = {
  children: ReactNode;
  className?: string;
};

export function McpTableCard({ children, className }: McpTableCardProps) {
  return (
    <Card
      className={cn(
        "overflow-hidden rounded-xl border-[var(--outline-variant)] bg-white shadow-[var(--shadow-card)]",
        className
      )}
    >
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

type RuntimeBadgeProps = {
  detail?: string;
  icon?: LucideIcon;
  label: string;
};

export function RuntimeBadge({ detail, icon: Icon, label }: RuntimeBadgeProps) {
  return (
    <Badge
      className={`gap-1.5 rounded px-2 py-1 text-xs font-medium ${runtimeBadgeClass(label)}`}
      title={detail || label}
      variant="outline"
    >
      {Icon ? <Icon className="size-3.5" /> : null}
      {label}
    </Badge>
  );
}

type ServerIdentityCellProps = {
  href: string;
  iconUrl?: string;
  name: string;
  title: string;
};

export function ServerIdentityCell({ href, iconUrl, name, title }: ServerIdentityCellProps) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground">
        {iconUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt=""
            className="size-full object-contain"
            referrerPolicy="no-referrer"
            src={iconUrl}
          />
        ) : (
          <Package className="size-4" />
        )}
      </div>
      <div className="min-w-0">
        <Link
          className="font-semibold text-primary underline-offset-4 hover:underline"
          href={href}
        >
          {title}
        </Link>
        <div className="mt-0.5 break-all text-[11px] text-[var(--on-surface-variant)]">
          {name}
        </div>
      </div>
    </div>
  );
}
