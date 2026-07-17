"use client";

import { CheckCircle2, Loader2, Pencil, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
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
import type { SecretStoreRead } from "@/lib/api/generated/model";
import { secretStoresValidate } from "@/lib/api/generated/secrets/secrets";

import {
  secretBackendValidationMessage,
  secretBackendValidationOk,
} from "./secret-backend-validation";
import {
  deleteSecretBackendPath,
  editSecretBackendPath,
  type SecretBackendScope,
} from "./secret-backends-paths";

type SecretBackendsClientProps = SecretBackendScope & {
  scopeLabel: "Organization";
  stores: SecretStoreRead[];
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringSetting(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function storeUrl(store: SecretStoreRead) {
  return stringSetting(record(store.config).baseUrl, "OpenBao");
}

function authMethod(store: SecretStoreRead) {
  const method = stringSetting(record(store.authConfig).method, "kubernetes");
  return method === "approle" ? "AppRole" : "Kubernetes";
}

export function SecretBackendsClient({
  organizationId,
  scopeLabel,
  stores: initialStores,
}: SecretBackendsClientProps) {
  const [validatingStoreId, setValidatingStoreId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const scope = { organizationId };

  async function validateStore(store: SecretStoreRead) {
    setValidatingStoreId(store.id);
    setError(null);
    setNotice(null);

    try {
      const data = await secretStoresValidate(organizationId, store.id);
      if (!secretBackendValidationOk(data)) {
        throw new Error(
          secretBackendValidationMessage(data, "Secret backend validation failed.")
        );
      }
      setNotice(secretBackendValidationMessage(data, "Secret backend is valid."));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Secret backend validation failed."
      );
    } finally {
      setValidatingStoreId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{scopeLabel} Secret Backends</CardTitle>
        <CardDescription>
          Manage external OpenBao connections used by Wardn secret handles.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <AsyncFeedback variant="error">{error}</AsyncFeedback>
        ) : null}
        {notice ? (
          <AsyncFeedback className="flex items-center gap-2" variant="success">
            <CheckCircle2 className="size-4" />
            {notice}
          </AsyncFeedback>
        ) : null}

        {initialStores.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>URL</TableHead>
                <TableHead>Auth</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-40 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {initialStores.map((store) => (
                <TableRow key={store.id}>
                  <TableCell>
                    <div className="min-w-48">
                      <div className="font-medium">{store.name}</div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="block max-w-72 truncate text-sm">{storeUrl(store)}</span>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{authMethod(store)}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={store.isActive ? "success" : "secondary"}>
                      {store.isActive ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        aria-label={`Validate ${store.name}`}
                        disabled={validatingStoreId === store.id}
                        onClick={() => validateStore(store)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        {validatingStoreId === store.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <ShieldCheck className="size-4" />
                        )}
                      </Button>
                      <Button
                        asChild
                        aria-label={`Edit ${store.name}`}
                        size="icon"
                        variant="outline"
                      >
                        <Link href={editSecretBackendPath(scope, store.id)}>
                          <Pencil className="size-4" />
                        </Link>
                      </Button>
                      <Button
                        asChild
                        aria-label={`Delete ${store.name}`}
                        size="icon"
                        variant="outline"
                      >
                        <Link href={deleteSecretBackendPath(scope, store.id)}>
                          <Trash2 className="size-4" />
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--outline-variant)] p-8 text-center">
            <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <ShieldCheck className="size-5" />
            </div>
            <h3 className="text-base font-semibold">No secret backends</h3>
            <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
              Connect OpenBao before creating secret handles or ChatGPT connector credentials.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
