"use client";

import { BadgeDollarSign, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { LLMModelPriceRead } from "./types";

type ModelPriceFormProps = {
  initialPrice?: LLMModelPriceRead;
  mode: "create" | "edit";
  organizationId: string;
};

function decimalText(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  return String(value);
}

function errorMessage(payload: unknown, fallback: string) {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback;
}

export function ModelPriceForm({
  initialPrice,
  mode,
  organizationId,
}: ModelPriceFormProps) {
  const router = useRouter();
  const isEdit = mode === "edit" && initialPrice;
  const listPath = `/org/${organizationId}/llm-pricing`;
  const [provider, setProvider] = useState(initialPrice?.provider ?? "");
  const [model, setModel] = useState(initialPrice?.model ?? "");
  const [inputPrice, setInputPrice] = useState(
    decimalText(initialPrice?.inputUsdPer1mTokens)
  );
  const [outputPrice, setOutputPrice] = useState(
    decimalText(initialPrice?.outputUsdPer1mTokens)
  );
  const [cacheReadPrice, setCacheReadPrice] = useState(
    decimalText(initialPrice?.cacheReadUsdPer1mTokens)
  );
  const [cacheWritePrice, setCacheWritePrice] = useState(
    decimalText(initialPrice?.cacheWriteUsdPer1mTokens)
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canSave =
    provider.trim().length > 0 &&
    model.trim().length > 0 &&
    inputPrice.trim().length > 0 &&
    outputPrice.trim().length > 0 &&
    !isSubmitting;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const response = await fetch(
        isEdit
          ? `/api/organizations/${organizationId}/observability/llm/model-prices/${initialPrice.id}`
          : `/api/organizations/${organizationId}/observability/llm/model-prices`,
        {
          method: isEdit ? "PATCH" : "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            provider: provider.trim(),
            model: model.trim(),
            inputUsdPer1mTokens: inputPrice.trim(),
            outputUsdPer1mTokens: outputPrice.trim(),
            cacheReadUsdPer1mTokens: cacheReadPrice.trim() || null,
            cacheWriteUsdPer1mTokens: cacheWritePrice.trim() || null,
          }),
        }
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(errorMessage(payload, "Model price could not be saved."));
      }
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Model price could not be saved.");
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <Card className="overflow-hidden">
        <CardHeader className="bg-card">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle>{isEdit ? "Edit Model Price" : "Create Model Price"}</CardTitle>
              <CardDescription>
                Prices are stored as USD per one million tokens and used for cost reports.
              </CardDescription>
            </div>
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
              <BadgeDollarSign className="size-4" />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <form onSubmit={submit}>
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="provider">Provider</Label>
                <Input
                  id="provider"
                  onChange={(event) => setProvider(event.target.value)}
                  placeholder="openai"
                  value={provider}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="model">Model</Label>
                <Input
                  id="model"
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="gpt-4.1-mini"
                  value={model}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="input-price">Input $ / 1M tokens</Label>
                <Input
                  id="input-price"
                  inputMode="decimal"
                  onChange={(event) => setInputPrice(event.target.value)}
                  placeholder="0.40"
                  value={inputPrice}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="output-price">Output $ / 1M tokens</Label>
                <Input
                  id="output-price"
                  inputMode="decimal"
                  onChange={(event) => setOutputPrice(event.target.value)}
                  placeholder="1.60"
                  value={outputPrice}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cache-read-price">Cache read $ / 1M</Label>
                <Input
                  id="cache-read-price"
                  inputMode="decimal"
                  onChange={(event) => setCacheReadPrice(event.target.value)}
                  placeholder="Optional"
                  value={cacheReadPrice}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cache-write-price">Cache write $ / 1M</Label>
                <Input
                  id="cache-write-price"
                  inputMode="decimal"
                  onChange={(event) => setCacheWritePrice(event.target.value)}
                  placeholder="Optional"
                  value={cacheWritePrice}
                />
              </div>
              {error ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 sm:col-span-2">
                  {error}
                </div>
              ) : null}
            </div>

            <div className="flex justify-end gap-2 border-t border-border bg-muted/30 px-4 py-3">
              <Button asChild type="button" variant="outline">
                <Link href={listPath}>Cancel</Link>
              </Button>
              <Button disabled={!canSave} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <Save />}
                Save price
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
