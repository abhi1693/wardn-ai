import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

type AsyncFeedbackVariant = "error" | "info" | "progress" | "success";

const variantClasses: Record<AsyncFeedbackVariant, string> = {
  error: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  info: "border-border bg-card text-foreground",
  progress: "border-border bg-muted/40 text-muted-foreground",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
};

type AsyncFeedbackProps = Omit<HTMLAttributes<HTMLDivElement>, "role"> & {
  announceAs?: "alert" | "status";
  children: ReactNode;
  variant?: AsyncFeedbackVariant;
};

export function AsyncFeedback({
  announceAs,
  children,
  className,
  variant = "info",
  ...props
}: AsyncFeedbackProps) {
  const isError = variant === "error";
  const role = announceAs ?? (isError ? "alert" : "status");
  return (
    <div
      aria-atomic="true"
      aria-live={role === "alert" ? "assertive" : "polite"}
      className={cn("rounded-md border px-3 py-2 text-sm", variantClasses[variant], className)}
      role={role}
      {...props}
    >
      {children}
    </div>
  );
}
