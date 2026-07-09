"use client";

import { Pencil, Plus, Save, Trash2, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import type { LLMModelPriceRead } from "./data";

type PriceFormState = {
  provider: string;
  model: string;
  inputUsdPer1mTokens: string;
  outputUsdPer1mTokens: string;
  cacheReadUsdPer1mTokens: string;
  cacheWriteUsdPer1mTokens: string;
};

type ModelPricingClientProps = {
  canManage: boolean;
  initialPrices: LLMModelPriceRead[];
  organizationId: string;
};

const emptyForm: PriceFormState = {
  provider: "",
  model: "",
  inputUsdPer1mTokens: "",
  outputUsdPer1mTokens: "",
  cacheReadUsdPer1mTokens: "",
  cacheWriteUsdPer1mTokens: "",
};

function decimalText(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  return String(value);
}

function displayUsdPerMillion(value: string | number | null | undefined) {
  const numericValue = Number(value ?? 0);
  if (!Number.isFinite(numericValue) || numericValue === 0) {
    return value ? String(value) : "-";
  }
  return `$${numericValue.toLocaleString("en-US", {
    maximumFractionDigits: 10,
  })}`;
}

function formFromPrice(price: LLMModelPriceRead): PriceFormState {
  return {
    provider: price.provider,
    model: price.model,
    inputUsdPer1mTokens: decimalText(price.inputUsdPer1mTokens),
    outputUsdPer1mTokens: decimalText(price.outputUsdPer1mTokens),
    cacheReadUsdPer1mTokens: decimalText(price.cacheReadUsdPer1mTokens),
    cacheWriteUsdPer1mTokens: decimalText(price.cacheWriteUsdPer1mTokens),
  };
}

function payloadFromForm(form: PriceFormState) {
  return {
    provider: form.provider.trim(),
    model: form.model.trim(),
    inputUsdPer1mTokens: form.inputUsdPer1mTokens.trim(),
    outputUsdPer1mTokens: form.outputUsdPer1mTokens.trim(),
    cacheReadUsdPer1mTokens: form.cacheReadUsdPer1mTokens.trim() || null,
    cacheWriteUsdPer1mTokens: form.cacheWriteUsdPer1mTokens.trim() || null,
  };
}

export function ModelPricingClient({
  canManage,
  initialPrices,
  organizationId,
}: ModelPricingClientProps) {
  const [prices, setPrices] = useState(initialPrices);
  const [form, setForm] = useState<PriceFormState>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const sortedPrices = useMemo(
    () =>
      [...prices].sort((left, right) =>
        `${left.provider}/${left.model}`.localeCompare(`${right.provider}/${right.model}`)
      ),
    [prices]
  );

  const isValid =
    form.provider.trim() &&
    form.model.trim() &&
    form.inputUsdPer1mTokens.trim() &&
    form.outputUsdPer1mTokens.trim();

  function resetForm() {
    setEditingId(null);
    setForm(emptyForm);
    setError("");
  }

  async function submitPrice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isValid || isSaving) {
      return;
    }

    setIsSaving(true);
    setError("");
    const path = editingId
      ? `/api/organizations/${encodeURIComponent(
          organizationId
        )}/observability/llm/model-prices/${encodeURIComponent(editingId)}`
      : `/api/organizations/${encodeURIComponent(
          organizationId
        )}/observability/llm/model-prices`;
    const response = await fetch(path, {
      method: editingId ? "PATCH" : "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payloadFromForm(form)),
    });
    setIsSaving(false);

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      setError(payload?.detail ?? "Unable to save model price.");
      return;
    }

    const savedPrice = (await response.json()) as LLMModelPriceRead;
    setPrices((current) => {
      const next = current.filter((price) => price.id !== savedPrice.id);
      return [...next, savedPrice];
    });
    resetForm();
  }

  async function deletePrice(priceId: string) {
    if (deletingId) {
      return;
    }
    setDeletingId(priceId);
    setError("");
    const response = await fetch(
      `/api/organizations/${encodeURIComponent(
        organizationId
      )}/observability/llm/model-prices/${encodeURIComponent(priceId)}`,
      { method: "DELETE" }
    );
    setDeletingId(null);

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      setError(payload?.detail ?? "Unable to delete model price.");
      return;
    }

    setPrices((current) => current.filter((price) => price.id !== priceId));
    if (editingId === priceId) {
      resetForm();
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>{editingId ? "Edit Price" : "New Price"}</CardTitle>
            {editingId ? (
              <Button onClick={resetForm} size="icon" type="button" variant="outline">
                <X className="size-4" />
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          {canManage ? (
            <form className="space-y-4" onSubmit={submitPrice}>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
                <div className="space-y-2">
                  <Label htmlFor="provider">Provider</Label>
                  <Input
                    id="provider"
                    onChange={(event) =>
                      setForm((current) => ({ ...current, provider: event.target.value }))
                    }
                    placeholder="openai"
                    value={form.provider}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="model">Model</Label>
                  <Input
                    id="model"
                    onChange={(event) =>
                      setForm((current) => ({ ...current, model: event.target.value }))
                    }
                    placeholder="gpt-4.1-mini"
                    value={form.model}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="input-price">Input $ / 1M tokens</Label>
                  <Input
                    id="input-price"
                    inputMode="decimal"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        inputUsdPer1mTokens: event.target.value,
                      }))
                    }
                    placeholder="0.40"
                    value={form.inputUsdPer1mTokens}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="output-price">Output $ / 1M tokens</Label>
                  <Input
                    id="output-price"
                    inputMode="decimal"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        outputUsdPer1mTokens: event.target.value,
                      }))
                    }
                    placeholder="1.60"
                    value={form.outputUsdPer1mTokens}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cache-read-price">Cache read $ / 1M</Label>
                  <Input
                    id="cache-read-price"
                    inputMode="decimal"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        cacheReadUsdPer1mTokens: event.target.value,
                      }))
                    }
                    placeholder="Optional"
                    value={form.cacheReadUsdPer1mTokens}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cache-write-price">Cache write $ / 1M</Label>
                  <Input
                    id="cache-write-price"
                    inputMode="decimal"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        cacheWriteUsdPer1mTokens: event.target.value,
                      }))
                    }
                    placeholder="Optional"
                    value={form.cacheWriteUsdPer1mTokens}
                  />
                </div>
              </div>
              {error ? <div className="text-sm text-destructive">{error}</div> : null}
              <Button disabled={!isValid || isSaving} type="submit">
                {editingId ? <Save className="size-4" /> : <Plus className="size-4" />}
                {isSaving ? "Saving" : editingId ? "Save price" : "Add price"}
              </Button>
            </form>
          ) : (
            <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              Organization admin access is required to manage model prices.
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Configured Prices</CardTitle>
            <Badge variant="outline">{prices.length} models</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {sortedPrices.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Provider</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Input</TableHead>
                    <TableHead className="text-right">Output</TableHead>
                    <TableHead className="text-right">Cache read</TableHead>
                    <TableHead className="text-right">Cache write</TableHead>
                    {canManage ? <TableHead className="w-24 text-right">Actions</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedPrices.map((price) => (
                    <TableRow key={price.id}>
                      <TableCell>
                        <Badge variant="secondary">{price.provider}</Badge>
                      </TableCell>
                      <TableCell className="min-w-48 font-medium">{price.model}</TableCell>
                      <TableCell className="text-right font-mono">
                        {displayUsdPerMillion(price.inputUsdPer1mTokens)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {displayUsdPerMillion(price.outputUsdPer1mTokens)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {displayUsdPerMillion(price.cacheReadUsdPer1mTokens)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {displayUsdPerMillion(price.cacheWriteUsdPer1mTokens)}
                      </TableCell>
                      {canManage ? (
                        <TableCell>
                          <div className="flex justify-end gap-2">
                            <Button
                              aria-label="Edit model price"
                              onClick={() => {
                                setEditingId(price.id);
                                setForm(formFromPrice(price));
                                setError("");
                              }}
                              size="icon"
                              type="button"
                              variant="outline"
                            >
                              <Pencil className="size-4" />
                            </Button>
                            <Button
                              aria-label="Delete model price"
                              disabled={deletingId === price.id}
                              onClick={() => void deletePrice(price.id)}
                              size="icon"
                              type="button"
                              variant="outline"
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="flex min-h-40 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
              No model prices configured.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

