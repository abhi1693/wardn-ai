"use client";

import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { displayUsdPerMillion } from "./price-display";
import type { LLMModelPriceRead } from "./types";

type ModelPricingClientProps = {
  canManage: boolean;
  initialPrices: LLMModelPriceRead[];
  organizationId: string;
};

export function ModelPricingClient({
  canManage,
  initialPrices,
  organizationId,
}: ModelPricingClientProps) {
  const sortedPrices = useMemo(
    () =>
      [...initialPrices].sort((left, right) =>
        `${left.provider}/${left.model}`.localeCompare(`${right.provider}/${right.model}`)
      ),
    [initialPrices]
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Configured Prices</CardTitle>
          <Badge variant="outline">{initialPrices.length} models</Badge>
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
                          <Button asChild aria-label="Edit model price" size="icon" variant="outline">
                            <Link
                              href={`/org/${organizationId}/llm-pricing/${price.id}/edit`}
                            >
                              <Pencil className="size-4" />
                            </Link>
                          </Button>
                          <Button asChild aria-label="Delete model price" size="icon" variant="outline">
                            <Link
                              href={`/org/${organizationId}/llm-pricing/${price.id}/delete`}
                            >
                              <Trash2 className="size-4" />
                            </Link>
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
  );
}
