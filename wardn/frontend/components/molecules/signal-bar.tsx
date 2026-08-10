import { cn } from "@/lib/utils";

type SignalBarTone = "danger" | "info" | "neutral" | "success" | "warning";

type SignalBarSegment = {
  label: string;
  tone?: SignalBarTone;
  value: number;
};

const segmentToneClassNames: Record<SignalBarTone, string> = {
  danger: "bg-red-500",
  info: "bg-sky-500",
  neutral: "bg-muted-foreground/40",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
};

type SignalBarProps = {
  className?: string;
  segments: SignalBarSegment[];
};

export function SignalBar({ className, segments }: SignalBarProps) {
  const visibleSegments = segments.filter((segment) => segment.value > 0);
  const total = visibleSegments.reduce((sum, segment) => sum + segment.value, 0);

  if (total === 0) {
    return <div className={cn("h-2 rounded-full bg-muted", className)} />;
  }

  return (
    <div className={cn("flex h-2 overflow-hidden rounded-full bg-muted", className)}>
      {visibleSegments.map((segment) => (
        <span
          aria-label={segment.label}
          className={cn(segmentToneClassNames[segment.tone ?? "neutral"])}
          key={segment.label}
          style={{ width: `${Math.max((segment.value / total) * 100, 3)}%` }}
          title={segment.label}
        />
      ))}
    </div>
  );
}
