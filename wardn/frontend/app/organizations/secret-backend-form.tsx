"use client";

import { ArrowLeft, CheckCircle2, Loader2, Save, ShieldCheck } from "lucide-react";
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

import { secretBackendErrorMessage } from "./secret-backend-errors";
import {
  secretBackendValidationMessage,
  secretBackendValidationOk,
} from "./secret-backend-validation";
import { secretBackendsPath, type SecretBackendScope } from "./secret-backends-paths";

const standardKvMount = "secret";
const backendType = "openbao";

type SecretBackendFormProps = SecretBackendScope & {
  mode: "create" | "edit";
  store?: SecretStoreRead;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringSetting(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function buildInitialForm(store?: SecretStoreRead) {
  const config = record(store?.config);
  const authConfig = record(store?.authConfig);

  return {
    name: store?.name ?? "",
    baseUrl: stringSetting(config.baseUrl),
    authProfile: stringSetting(authConfig.profile),
    isActive: store?.isActive ?? true,
  };
}

export function SecretBackendForm({
  mode,
  organizationId,
  store,
}: SecretBackendFormProps) {
  const router = useRouter();
  const initialForm = buildInitialForm(store);
  const listPath = secretBackendsPath({ organizationId });
  const isEditing = mode === "edit";

  const [name, setName] = useState(initialForm.name);
  const [baseUrl, setBaseUrl] = useState(initialForm.baseUrl);
  const [authProfile, setAuthProfile] = useState(initialForm.authProfile);
  const [isActive, setIsActive] = useState(initialForm.isActive);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const canSave =
    name.trim().length > 0 &&
    baseUrl.trim().length > 0 &&
    authProfile.trim().length > 0 &&
    !saving;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);

    const config: Record<string, unknown> = {
      baseUrl: baseUrl.trim(),
      kvMount: standardKvMount,
    };
    const authConfig = { profile: authProfile.trim() };
    const payload = {
      name: name.trim(),
      provider: "openbao",
      config,
      authConfig,
      ...(isEditing ? { isActive } : {}),
    };

    try {
      const response = await fetch(
        isEditing && store
          ? `/api/organizations/${organizationId}/secrets/stores/${store.id}`
          : `/api/organizations/${organizationId}/secrets/stores`,
        {
          method: isEditing ? "PATCH" : "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(
          secretBackendErrorMessage(data, "Secret backend could not be saved.")
        );
      }

      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Secret backend could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function validateBackend() {
    if (!store || validating) {
      return;
    }

    setValidating(true);
    setError(null);
    setNotice(null);

    try {
      const response = await fetch(
        `/api/organizations/${organizationId}/secrets/stores/${store.id}/validate`,
        { method: "POST" }
      );
      const data = await response.json().catch(() => null);
      if (!response.ok || !secretBackendValidationOk(data)) {
        throw new Error(
          secretBackendValidationMessage(data, "Secret backend validation failed.")
        );
      }
      setNotice("Validation passed.");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Secret backend validation failed."
      );
    } finally {
      setValidating(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle>{isEditing ? "Edit OpenBao Backend" : "Create OpenBao Backend"}</CardTitle>
          </div>
          <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
            <ShieldCheck className="size-5" />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={submit}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Backend type</Label>
              <Select value={backendType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={backendType}>OpenBao</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="secret-backend-name">Name</Label>
              <Input
                id="secret-backend-name"
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                placeholder="Production OpenBao"
                required
                value={name}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="secret-backend-base-url">OpenBao URL</Label>
              <Input
                id="secret-backend-base-url"
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://bao.example.com"
              required
              type="url"
              value={baseUrl}
            />
            </div>
            <div className="space-y-2">
              <Label htmlFor="secret-backend-auth-profile">Authentication profile</Label>
              <Input
                id="secret-backend-auth-profile"
                maxLength={64}
                onChange={(event) => setAuthProfile(event.target.value)}
                pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
                placeholder="production"
                required
                value={authProfile}
              />
              <p className="text-xs leading-5 text-muted-foreground">
                Enter a profile configured by the Wardn operator. Credentials, authentication
                method, destination, and TLS policy are controlled by that profile.
              </p>
            </div>
          </div>

          {isEditing ? (
            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex min-h-10 items-center gap-3 rounded-md border border-[var(--outline-variant)] px-3 text-sm">
                <input
                  checked={isActive}
                  className="size-4 accent-primary"
                  onChange={(event) => setIsActive(event.target.checked)}
                  type="checkbox"
                />
                Active
              </label>
            </div>
          ) : null}

          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : null}
          {notice ? (
            <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              <CheckCircle2 className="size-4" />
              {notice}
            </div>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button asChild type="button" variant="outline">
              <Link href={listPath}>
                <ArrowLeft className="size-4" />
                Back
              </Link>
            </Button>
            {isEditing ? (
              <Button
                disabled={validating}
                onClick={validateBackend}
                type="button"
                variant="outline"
              >
                {validating ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ShieldCheck className="size-4" />
                )}
                {validating ? "Validating" : "Validate"}
              </Button>
            ) : null}
            <Button disabled={!canSave} type="submit">
              {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
              {saving ? "Saving" : isEditing ? "Save backend" : "Create backend"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
