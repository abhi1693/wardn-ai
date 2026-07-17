import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

type AsyncFeedbackVariant = "error" | "info" | "progress" | "success";

const variantClasses: Record<AsyncFeedbackVariant, string> = {
  error: "border-red-200 bg-red-50 text-red-700",
  info: "border-border bg-card text-foreground",
  progress: "border-border bg-muted/40 text-muted-foreground",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
};

type AsyncFeedbackProps = Omit<HTMLAttributes<HTMLDivElement>, "role"> & {
  children: ReactNode;
  variant?: AsyncFeedbackVariant;
};

export function AsyncFeedback({
  children,
  className,
  variant = "info",
  ...props
}: AsyncFeedbackProps) {
  const isError = variant === "error";
  return (
    <div
      aria-atomic="true"
      aria-live={isError ? "assertive" : "polite"}
      className={cn("rounded-md border px-3 py-2 text-sm", variantClasses[variant], className)}
      role={isError ? "alert" : "status"}
      {...props}
    >
      {children}
    </div>
  );
}
