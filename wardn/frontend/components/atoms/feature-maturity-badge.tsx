import type { ComponentProps } from "react";

import { Badge } from "@/components/atoms/badge";
import {
  featureMaturityLabel,
  type PreGaFeatureMaturity,
} from "@/lib/feature-maturity";
import { cn } from "@/lib/utils";

const maturityDescription: Record<PreGaFeatureMaturity, string> = {
  alpha: "Alpha feature: early access and subject to significant change.",
  beta: "Beta feature: usable but still being refined.",
};

const maturityStyles: Record<PreGaFeatureMaturity, string> = {
  alpha:
    "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
  beta:
    "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-200",
};

type FeatureMaturityBadgeProps = Omit<ComponentProps<typeof Badge>, "children"> & {
  maturity: PreGaFeatureMaturity;
};

export function FeatureMaturityBadge({
  className,
  maturity,
  title,
  ...props
}: FeatureMaturityBadgeProps) {
  const label = featureMaturityLabel(maturity);

  return (
    <Badge
      aria-label={`Feature maturity: ${label}`}
      className={cn("shrink-0 uppercase tracking-wide", maturityStyles[maturity], className)}
      title={title ?? maturityDescription[maturity]}
      variant="outline"
      {...props}
    >
      {label}
    </Badge>
  );
}
