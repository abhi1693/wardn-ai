import type { LLMModelPriceRead } from "./types";

export function displayUsdPerMillion(value: string | number | null | undefined) {
  const numericValue = Number(value ?? 0);
  if (!Number.isFinite(numericValue) || numericValue === 0) {
    return value ? String(value) : "-";
  }
  return `$${numericValue.toLocaleString("en-US", {
    maximumFractionDigits: 10,
  })}`;
}

export function modelPriceLabel(price: LLMModelPriceRead) {
  return `${price.provider} / ${price.model}`;
}

