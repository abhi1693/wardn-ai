import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { StatusDot } from "@/components/atoms/status-dot";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type HealthRowTone = "danger" | "info" | "neutral" | "success" | "warning";

type HealthRowProps = {
  badge?: ReactNode;
  className?: string;
  detail: ReactNode;
  href?: string;
  icon?: LucideIcon;
  label: ReactNode;
  tone?: HealthRowTone;
};

export function HealthRow({
  badge,
  className,
  detail,
  href,
  icon: Icon,
  label,
  tone = "neutral",
}: HealthRowProps) {
  const content = (
    <>
      <div className="flex min-w-0 items-center gap-3">
        {Icon ? (
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
            <Icon className="size-4" />
          </div>
        ) : (
          <StatusDot tone={tone} />
        )}
        <div className="min-w-0">
          <div className="truncate text-sm font-medium leading-5 text-foreground">{label}</div>
          <div className="truncate text-xs leading-4 text-muted-foreground">{detail}</div>
        </div>
      </div>
      {badge ? <Badge variant={tone === "success" ? "success" : "outline"}>{badge}</Badge> : null}
    </>
  );

  const classNames = cn(
    "flex min-h-14 items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0",
    href && "transition-colors hover:bg-muted/50",
    className
  );

  if (href) {
    return (
      <Link className={classNames} href={href}>
        {content}
      </Link>
    );
  }

  return <div className={classNames}>{content}</div>;
}
