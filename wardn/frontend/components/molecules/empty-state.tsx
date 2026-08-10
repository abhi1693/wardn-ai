import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  action?: ReactNode;
  className?: string;
  description: ReactNode;
  icon: LucideIcon;
  title: string;
};

export function EmptyState({ action, className, description, icon: Icon, title }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-border bg-muted/20 px-5 py-10 text-center",
        className
      )}
    >
      <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-md border border-border bg-card text-muted-foreground shadow-[var(--shadow-card)]">
        <Icon className="size-5" />
      </div>
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      <div className="mx-auto mt-1 max-w-lg text-sm leading-5 text-muted-foreground">
        {description}
      </div>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
