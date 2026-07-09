"use client";

import { ArrowLeft, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SecretStoreRead } from "@/lib/api/generated/model";

import type { MCPCatalogSource } from "./catalog-source-types";

const wardnHubCatalogProvider = {
  label: "Wardn Hub",
  provider: "wardn_hub",
  name: "Wardn Hub",
  baseUrl: "https://hub.wardnai.dev",
};

type CatalogSourceFormProps = {
  initialSource?: MCPCatalogSource;
  mode: "create" | "edit";
  organizationId: string;
  secretStores: SecretStoreRead[];
};

async function responseErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

export function CatalogSourceForm({
  initialSource,
  mode,
  organizationId,
  secretStores,
}: CatalogSourceFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initialSource?.name ?? wardnHubCatalogProvider.name);
  const [baseUrl, setBaseUrl] = useState(initialSource?.baseUrl ?? wardnHubCatalogProvider.baseUrl);
  const [syncMode, setSyncMode] = useState(initialSource?.syncMode ?? "latest_only");
  const [apiTokenSecretStoreId, setApiTokenSecretStoreId] = useState(secretStores[0]?.id ?? "");
  const [apiToken, setApiToken] = useState("");
  const [isEnabled, setIsEnabled] = useState(initialSource?.isEnabled ?? true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const catalogPath = `/org/${encodeURIComponent(organizationId)}/catalog`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError("");
    const needsToken = !initialSource?.hasAuthToken;
    if ((needsToken || apiToken.trim()) && !apiTokenSecretStoreId) {
      setError("Select a secret backend for the API token.");
      setIsSaving(false);
      return;
    }
    if (needsToken && !apiToken.trim()) {
      setError("Wardn Hub requires an API token.");
      setIsSaving(false);
      return;
    }

    const payload = {
      name,
      provider: wardnHubCatalogProvider.provider,
      baseUrl,
      syncMode,
      isEnabled,
      ...(apiToken.trim()
        ? {
            apiToken: apiToken.trim(),
            apiTokenSecretStoreId,
          }
        : needsToken
          ? { apiTokenSecretStoreId }
          : {}),
    };
    const path =
      mode === "edit" && initialSource
        ? `/api/organizations/${organizationId}/mcp/catalog/sources/${initialSource.id}`
        : `/api/organizations/${organizationId}/mcp/catalog/sources`;

    try {
      const response = await fetch(path, {
        method: mode === "edit" ? "PATCH" : "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Catalog source could not be saved."));
      }
      router.push(catalogPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Catalog source could not be saved.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card className="max-w-3xl">
      <CardHeader>
        <CardTitle>{mode === "edit" ? "Edit catalog source" : "New catalog source"}</CardTitle>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        <form className="space-y-5" onSubmit={submit}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="catalog-name">Name</Label>
              <Input
                id="catalog-name"
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="catalog-provider">Provider</Label>
              <div
                className="flex h-10 items-center rounded-md border border-input bg-muted px-3 text-sm text-muted-foreground"
                id="catalog-provider"
              >
                {wardnHubCatalogProvider.label}
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="catalog-url">Hub URL</Label>
            <Input
              id="catalog-url"
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={wardnHubCatalogProvider.baseUrl}
              required
              type="url"
              value={baseUrl}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="catalog-secret-store">Secret backend</Label>
              <Select
                disabled={secretStores.length === 0}
                onValueChange={setApiTokenSecretStoreId}
                value={apiTokenSecretStoreId}
              >
                <SelectTrigger id="catalog-secret-store">
                  <SelectValue placeholder="Select backend" />
                </SelectTrigger>
                <SelectContent>
                  {secretStores.map((store) => (
                    <SelectItem key={store.id} value={store.id}>
                      {store.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="catalog-api-token">API token</Label>
              <Input
                autoComplete="off"
                id="catalog-api-token"
                onChange={(event) => setApiToken(event.target.value)}
                placeholder={initialSource?.hasAuthToken ? "Leave blank to keep current token" : ""}
                required={!initialSource?.hasAuthToken}
                type="password"
                value={apiToken}
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="catalog-sync-mode">Sync mode</Label>
              <Select onValueChange={setSyncMode} value={syncMode}>
                <SelectTrigger id="catalog-sync-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="latest_only">Latest versions</SelectItem>
                  <SelectItem value="all_versions">All versions</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <label className="flex min-h-10 items-center gap-3 self-end rounded-md border px-3 py-2 text-sm">
              <input
                checked={isEnabled}
                className="size-4"
                onChange={(event) => setIsEnabled(event.target.checked)}
                type="checkbox"
              />
              Active
            </label>
          </div>

          <div className="flex justify-end gap-2">
            <Button asChild type="button" variant="outline">
              <Link href={catalogPath}>
                <ArrowLeft className="size-4" />
                Back
              </Link>
            </Button>
            <Button disabled={isSaving} type="submit">
              <Save className="size-4" />
              {mode === "edit" ? "Save" : "Create"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
