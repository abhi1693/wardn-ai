export type FeatureMaturity = "alpha" | "beta" | "ga";
export type PreGaFeatureMaturity = Exclude<FeatureMaturity, "ga">;

const featureMaturity = {
  "workspace-scheduled-tasks": "alpha",
  "workspace-skills": "alpha",
} as const satisfies Record<string, PreGaFeatureMaturity>;

/**
 * Features are generally available unless they are explicitly listed above.
 * Keeping the registry opt-in prevents GA labels from adding noise throughout the UI.
 */
export function getFeatureMaturity(featureKey: string): FeatureMaturity {
  return featureMaturity[featureKey as keyof typeof featureMaturity] ?? "ga";
}

export function getPreGaFeatureMaturity(featureKey: string): PreGaFeatureMaturity | undefined {
  const maturity = getFeatureMaturity(featureKey);
  return maturity === "ga" ? undefined : maturity;
}

export function featureMaturityLabel(maturity: PreGaFeatureMaturity) {
  return maturity === "alpha" ? "Alpha" : "Beta";
}
