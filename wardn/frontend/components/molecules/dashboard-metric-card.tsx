import type { LucideIcon } from "lucide-react";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { Card, CardContent } from "@/components/atoms/card";
import { cn } from "@/lib/utils";

type DashboardMetricTone = "danger" | "info" | "neutral" | "success" | "warning";

const toneClassNames: Record<DashboardMetricTone, string> = {
  danger: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
  info: "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  neutral: "bg-muted text-muted-foreground",
  success: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  warning: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
};

type DashboardMetricCardProps = {
  badge?: ReactNode;
  className?: string;
  detail: ReactNode;
  href?: string;
  icon: LucideIcon;
  label: string;
  tone?: DashboardMetricTone;
  value: ReactNode;
};

export function DashboardMetricCard({
  badge,
  className,
  detail,
  href,
  icon: Icon,
  label,
  tone = "neutral",
  value,
}: DashboardMetricCardProps) {
  return (
    <Card className={cn("overflow-hidden shadow-none", className)}>
      <CardContent className="p-0">
        <div className="flex min-h-36 flex-col justify-between gap-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className={cn("flex size-9 items-center justify-center rounded-md", toneClassNames[tone])}>
              <Icon className="size-4" />
            </div>
            {href ? (
              <Button aria-label={`Open ${label}`} asChild size="icon" variant="ghost">
                <Link href={href}>
                  <ArrowUpRight className="size-4" />
                </Link>
              </Button>
            ) : badge ? (
              <Badge variant="outline">{badge}</Badge>
            ) : null}
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium leading-4 text-muted-foreground">{label}</div>
            <div className="mt-2 truncate text-3xl font-semibold leading-9 text-foreground">
              {value}
            </div>
            <div className="mt-1 min-h-5 text-sm leading-5 text-muted-foreground">{detail}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
