import { cn } from "@/lib/utils";

type StatusDotTone = "danger" | "info" | "neutral" | "success" | "warning";

const toneClassNames: Record<StatusDotTone, string> = {
  danger: "bg-red-500 shadow-[0_0_0_3px_rgb(239_68_68/0.12)]",
  info: "bg-sky-500 shadow-[0_0_0_3px_rgb(14_165_233/0.12)]",
  neutral: "bg-muted-foreground shadow-[0_0_0_3px_var(--border)]",
  success: "bg-emerald-500 shadow-[0_0_0_3px_rgb(16_185_129/0.12)]",
  warning: "bg-amber-500 shadow-[0_0_0_3px_rgb(245_158_11/0.14)]",
};

type StatusDotProps = {
  className?: string;
  tone?: StatusDotTone;
};

export function StatusDot({ className, tone = "neutral" }: StatusDotProps) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block size-2 shrink-0 rounded-full", toneClassNames[tone], className)}
    />
  );
}
