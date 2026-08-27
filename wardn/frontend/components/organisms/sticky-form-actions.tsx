import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type StickyFormActionsProps = {
  children: ReactNode;
  className?: string;
  context?: ReactNode;
  position?: "bottom" | "top";
};

export function StickyFormActions({
  children,
  className,
  context,
  position = "top",
}: StickyFormActionsProps) {
  return (
    <div
      className={cn(
        "sticky z-20 flex min-h-14 flex-wrap items-center justify-between gap-3 bg-card/95 px-6 py-2 backdrop-blur",
        position === "top" ? "top-14 border-b border-border" : "bottom-0 border-t border-border",
        className
      )}
      data-slot="sticky-form-actions"
    >
      <div className="min-w-0">{context}</div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}
