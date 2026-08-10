import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/atoms/card";
import { cn } from "@/lib/utils";

export type MetricStripItem = {
  detail?: ReactNode;
  icon: LucideIcon;
  label: string;
  value: ReactNode;
};

type MetricStripProps = {
  className?: string;
  items: MetricStripItem[];
};

export function MetricStrip({ className, items }: MetricStripProps) {
  return (
    <section className={cn("grid gap-3", className)}>
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <Card className="shadow-none" key={item.label}>
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-muted-foreground">{item.label}</div>
                  <div className="mt-2 text-2xl font-semibold leading-8 text-foreground">
                    {item.value}
                  </div>
                  {item.detail ? (
                    <div className="mt-1 text-xs leading-4 text-muted-foreground">
                      {item.detail}
                    </div>
                  ) : null}
                </div>
                <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  <Icon className="size-4" />
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}
