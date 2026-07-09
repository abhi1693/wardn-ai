"use client";

import { ArrowLeft, Loader2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { displayUsdPerMillion, modelPriceLabel } from "./price-display";
import type { LLMModelPriceRead } from "./types";

type DeleteModelPriceClientProps = {
  organizationId: string;
  price: LLMModelPriceRead;
};

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

export function DeleteModelPriceClient({
  organizationId,
  price,
}: DeleteModelPriceClientProps) {
  const router = useRouter();
  const listPath = `/org/${organizationId}/llm-pricing`;
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function deletePrice() {
    setDeleting(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/organizations/${organizationId}/observability/llm/model-prices/${price.id}`,
        { method: "DELETE" }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(errorMessage(payload, "Model price could not be deleted."));
      }
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Model price could not be deleted.");
      setDeleting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Delete Model Price</CardTitle>
        <CardDescription>Delete pricing for {modelPriceLabel(price)}.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-0 overflow-hidden rounded-md border bg-card sm:grid-cols-2">
          <div className="border-b p-3 sm:border-b-0 sm:border-r">
            <div className="text-xs font-medium text-muted-foreground">Input</div>
            <div className="mt-1 font-mono text-sm">
              {displayUsdPerMillion(price.inputUsdPer1mTokens)}
            </div>
          </div>
          <div className="p-3">
            <div className="text-xs font-medium text-muted-foreground">Output</div>
            <div className="mt-1 font-mono text-sm">
              {displayUsdPerMillion(price.outputUsdPer1mTokens)}
            </div>
          </div>
        </div>

        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          This action cannot be undone.
        </div>

        {error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button asChild variant="outline">
            <Link href={listPath}>
              <ArrowLeft className="size-4" />
              Back
            </Link>
          </Button>
          <Button disabled={deleting} onClick={deletePrice} type="button" variant="destructive">
            {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 />}
            {deleting ? "Deleting" : "Delete price"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
