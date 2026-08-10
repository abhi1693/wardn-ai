import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import { cn } from "@/lib/utils";

type DashboardPanelProps = {
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  description?: ReactNode;
  title: ReactNode;
};

export function DashboardPanel({
  action,
  children,
  className,
  description,
  title,
}: DashboardPanelProps) {
  return (
    <Card className={cn("min-w-0 overflow-hidden shadow-none", className)}>
      <CardHeader className="flex min-h-16 grid-cols-none flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          {description ? (
            <div className="mt-1 text-sm leading-5 text-muted-foreground">{description}</div>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
