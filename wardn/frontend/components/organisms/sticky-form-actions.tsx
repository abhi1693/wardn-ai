import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type StickyFormActionsProps = {
  children: ReactNode;
  className?: string;
  context?: ReactNode;
};

export function StickyFormActions({ children, className, context }: StickyFormActionsProps) {
  return (
    <div
      className={cn(
        "sticky top-0 z-20 flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-border bg-card/95 px-6 py-2 backdrop-blur",
        className
      )}
      data-slot="sticky-form-actions"
    >
      <div className="min-w-0">{context}</div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}
