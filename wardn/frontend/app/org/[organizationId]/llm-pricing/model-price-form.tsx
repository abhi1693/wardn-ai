"use client";

import { BadgeDollarSign, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { llmProviderCredentialsListModels } from "@/lib/api/generated/llm-provider-credentials/llm-provider-credentials";
import {
  organizationObservabilityCreateLlmModelPrice,
  organizationObservabilityPrefillLlmModelPrice,
  organizationObservabilityUpdateLlmModelPrice,
} from "@/lib/api/generated/organization-observability/organization-observability";

import type { LlmCredentialRead } from "../llm-credentials/types";
import type { LLMModelPriceRead, ProviderModel } from "./types";

type ModelPriceFormProps = {
  credentials: LlmCredentialRead[];
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

function providerLabel(credential: LlmCredentialRead) {
  if (credential.provider === "openai_chatgpt" || credential.authMethod === "oauth") {
    return "OpenAI ChatGPT";
  }
  if (credential.provider === "openai") {
    return "OpenAI";
  }
  return credential.provider;
}

export function ModelPriceForm({
  credentials,
  initialPrice,
  mode,
  organizationId,
}: ModelPriceFormProps) {
  const router = useRouter();
  const isEdit = mode === "edit" && initialPrice;
  const listPath = `/org/${organizationId}/llm-pricing`;
  const availableCredentials = useMemo(
    () => credentials.filter((credential) => credential.isActive),
    [credentials]
  );
  const initialCredentialId =
    availableCredentials.find((credential) => credential.provider === initialPrice?.provider)?.id ??
    availableCredentials[0]?.id ??
    "";
  const [providerCredentialId, setProviderCredentialId] = useState(initialCredentialId);
  const [model, setModel] = useState(initialCredentialId ? initialPrice?.model ?? "" : "");
  const [modelOptions, setModelOptions] = useState<ProviderModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(Boolean(initialCredentialId));
  const [modelError, setModelError] = useState<string | null>(null);
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
  const [isPrefilling, setIsPrefilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null);

  const effectiveCredential =
    availableCredentials.find((credential) => credential.id === providerCredentialId) ?? null;
  const selectedModelUnavailable =
    Boolean(model) && !isLoadingModels && !modelOptions.some((entry) => entry.id === model);
  const canSave =
    Boolean(effectiveCredential) &&
    model.trim().length > 0 &&
    inputPrice.trim().length > 0 &&
    outputPrice.trim().length > 0 &&
    !isLoadingModels &&
    !modelError &&
    !selectedModelUnavailable &&
    !isSubmitting;

  useEffect(() => {
    if (!providerCredentialId) {
      return;
    }

    const abortController = new AbortController();

    async function loadModels() {
      try {
        const data = await llmProviderCredentialsListModels(
          organizationId,
          providerCredentialId,
          { signal: abortController.signal }
        );
        setModelOptions(
          Array.isArray((data as { models?: unknown }).models)
            ? ((data as { models: ProviderModel[] }).models ?? [])
            : []
        );
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setModelOptions([]);
        setModelError(caught instanceof Error ? caught.message : "Models could not be loaded.");
      } finally {
        if (!abortController.signal.aborted) {
          setIsLoadingModels(false);
        }
      }
    }

    void loadModels();
    return () => abortController.abort();
  }, [organizationId, providerCredentialId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave || !effectiveCredential) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const payload = {
        provider: effectiveCredential.provider,
        model: model.trim(),
        inputUsdPer1mTokens: inputPrice.trim(),
        outputUsdPer1mTokens: outputPrice.trim(),
        cacheReadUsdPer1mTokens: cacheReadPrice.trim() || null,
        cacheWriteUsdPer1mTokens: cacheWritePrice.trim() || null,
      };
      if (isEdit) {
        await organizationObservabilityUpdateLlmModelPrice(
          organizationId,
          initialPrice.id,
          payload
        );
      } else {
        await organizationObservabilityCreateLlmModelPrice(organizationId, payload);
      }
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Model price could not be saved.");
      setIsSubmitting(false);
    }
  }

  async function prefillFromOpenRouter() {
    if (!effectiveCredential || !model.trim() || isPrefilling) {
      return;
    }

    setIsPrefilling(true);
    setError(null);
    setPrefillNotice(null);
    try {
      const payload = await organizationObservabilityPrefillLlmModelPrice(organizationId, {
        provider: effectiveCredential.provider,
        model: model.trim(),
      });
      if (!payload?.found) {
        setPrefillNotice("No OpenRouter pricing match was found for this model.");
        return;
      }
      setInputPrice(decimalText(payload.inputUsdPer1mTokens));
      setOutputPrice(decimalText(payload.outputUsdPer1mTokens));
      setCacheReadPrice(decimalText(payload.cacheReadUsdPer1mTokens));
      setCacheWritePrice(decimalText(payload.cacheWriteUsdPer1mTokens));
      setPrefillNotice(
        payload.sourceModelName
          ? `Pricing filled from OpenRouter: ${payload.sourceModelName}.`
          : "Pricing filled from OpenRouter."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "OpenRouter pricing could not be loaded.");
    } finally {
      setIsPrefilling(false);
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
                <Label htmlFor="provider-credential">LLM credential</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-70"
                  disabled={availableCredentials.length === 0}
                  id="provider-credential"
                  onChange={(event) => {
                    const nextCredentialId = event.target.value;
                    setProviderCredentialId(nextCredentialId);
                    setModel("");
                    setModelOptions([]);
                    setModelError(null);
                    setIsLoadingModels(Boolean(nextCredentialId));
                  }}
                  value={providerCredentialId}
                >
                  {availableCredentials.length === 0 ? (
                    <option value="">No LLM credentials available</option>
                  ) : null}
                  {availableCredentials.map((credential) => (
                    <option key={credential.id} value={credential.id}>
                      {credential.name} ({providerLabel(credential)})
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="model">Model</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-70"
                  disabled={!effectiveCredential || isLoadingModels || Boolean(modelError)}
                  id="model"
                  onChange={(event) => setModel(event.target.value)}
                  required={Boolean(effectiveCredential)}
                  value={model}
                >
                  <option value="">
                    {effectiveCredential
                      ? isLoadingModels
                        ? "Loading models"
                        : "Select model"
                      : "Select an LLM credential first"}
                  </option>
                  {selectedModelUnavailable ? (
                    <option value={model}>{model} (unavailable)</option>
                  ) : null}
                  {modelOptions.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
                    </option>
                  ))}
                </select>
                {modelError ? <AsyncFeedback variant="error">{modelError}</AsyncFeedback> : null}
                {selectedModelUnavailable ? (
                  <AsyncFeedback variant="error">
                    This model is not available from the selected credential.
                  </AsyncFeedback>
                ) : null}
              </div>
              <div className="sm:col-span-2">
                <Button
                  disabled={
                    !effectiveCredential ||
                    !model.trim() ||
                    isLoadingModels ||
                    Boolean(modelError) ||
                    selectedModelUnavailable ||
                    isPrefilling
                  }
                  onClick={prefillFromOpenRouter}
                  type="button"
                  variant="outline"
                >
                  {isPrefilling ? <Loader2 className="size-4 animate-spin" /> : <BadgeDollarSign />}
                  {isPrefilling ? "Loading pricing" : "Prefill from OpenRouter"}
                </Button>
                {prefillNotice ? (
                  <AsyncFeedback className="mt-2" variant="info">
                    {prefillNotice}
                  </AsyncFeedback>
                ) : null}
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
                <AsyncFeedback className="sm:col-span-2" variant="error">{error}</AsyncFeedback>
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
