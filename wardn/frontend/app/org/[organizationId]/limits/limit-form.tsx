"use client";

import { Loader2, Save, SlidersHorizontal } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  OrganizationRead,
  ResourceLimitRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";

import {
  displayLimitKey,
  knownLimitKeys,
  type LimitScopeType,
  scopeLabel,
} from "./limit-display";

type LimitFormProps = {
  initialLimit?: ResourceLimitRead;
  mode: "create" | "edit";
  organizationId: string;
  organizations: OrganizationRead[];
  workspaces: WorkspaceRead[];
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

export function LimitForm({
  initialLimit,
  mode,
  organizationId,
  organizations,
  workspaces,
}: LimitFormProps) {
  const router = useRouter();
  const isEdit = mode === "edit" && initialLimit;
  const initialKnownKey = knownLimitKeys[0];
  const [scopeType, setScopeType] = useState<LimitScopeType>(
    (initialLimit?.scopeType as LimitScopeType | undefined) ?? initialKnownKey.defaultScope
  );
  const [scopeId, setScopeId] = useState(initialLimit?.scopeId ?? organizationId);
  const [limitKey, setLimitKey] = useState(
    initialLimit ? initialLimit.limitKey : initialKnownKey.value
  );
  const [value, setValue] = useState(String(initialLimit?.value ?? 10));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listPath = `/org/${organizationId}/limits`;
  const selectedKey = initialLimit?.limitKey ?? limitKey;
  const selectedScopeType = isEdit ? (initialLimit.scopeType as LimitScopeType) : scopeType;
  const organizationName = organizations[0]?.name ?? "Current organization";
  const parsedValue = Number(value);
  const canSave =
    selectedKey.trim().length > 0 &&
    Number.isInteger(parsedValue) &&
    parsedValue >= 0 &&
    !isSubmitting &&
    scopeId.trim().length > 0;

  function updateScopeType(nextScopeType: LimitScopeType) {
    setScopeType(nextScopeType);
    if (nextScopeType === "organization") {
      setScopeId(organizationId);
    } else if (nextScopeType === "workspace") {
      setScopeId(workspaces[0]?.id ?? "");
    }
  }

  function updateLimitKey(nextLimitKey: string) {
    setLimitKey(nextLimitKey);
    const nextLimit = knownLimitKeys.find((entry) => entry.value === nextLimitKey);
    if (nextLimit) {
      updateScopeType(nextLimit.defaultScope);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/limits", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          scopeType: isEdit ? initialLimit.scopeType : scopeType,
          scopeId: isEdit ? initialLimit.scopeId : scopeId.trim(),
          limitKey: selectedKey.trim(),
          value: parsedValue,
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(errorMessage(payload, "Limit could not be saved."));
      }
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Limit could not be saved.");
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle>{isEdit ? "Edit Limit" : "Create Limit"}</CardTitle>
              <CardDescription>
                {isEdit
                  ? "Update the quota value for this limit."
                  : "Set a quota for this organization or one of its workspaces."}
              </CardDescription>
            </div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <SlidersHorizontal className="size-5" />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <form onSubmit={submit}>
            <div className="space-y-5 p-5">
            {isEdit ? (
              <div className="grid gap-4 rounded-md border bg-muted/30 p-4 sm:grid-cols-2">
                <div>
                  <div className="text-xs font-medium text-[var(--on-surface-variant)]">
                    Limit
                  </div>
                  <div className="mt-1 text-sm">{displayLimitKey(initialLimit.limitKey)}</div>
                </div>
                <div>
                  <div className="text-xs font-medium text-[var(--on-surface-variant)]">
                    Target
                  </div>
                  <div className="mt-1 truncate text-sm">
                    {scopeLabel(initialLimit, organizations, workspaces)}
                  </div>
                </div>
              </div>
            ) : (
              <div className="grid gap-5 sm:grid-cols-2">
                <div>
                  <Label>Limit key</Label>
                  <Select onValueChange={updateLimitKey} value={limitKey}>
                    <SelectTrigger className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {knownLimitKeys.map((entry) => (
                        <SelectItem key={entry.value} value={entry.value}>
                          {entry.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {selectedScopeType === "workspace" ? (
                  <div>
                    <Label>Target</Label>
                    <Select onValueChange={setScopeId} value={scopeId}>
                      <SelectTrigger className="mt-2">
                        <SelectValue placeholder="Select workspace" />
                      </SelectTrigger>
                      <SelectContent>
                        {workspaces.map((workspace) => (
                          <SelectItem key={workspace.id} value={workspace.id}>
                            {workspace.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : (
                  <div>
                    <Label>Target</Label>
                    <div className="mt-2 flex h-9 items-center rounded-md border border-input bg-muted/30 px-3 text-sm">
                      {organizationName}
                    </div>
                  </div>
                )}
              </div>
            )}

              <div className="max-w-52">
                <Label htmlFor="limit-value">Value</Label>
                <Input
                  className="mt-2"
                  id="limit-value"
                  min={0}
                  onChange={(event) => setValue(event.target.value)}
                  step={1}
                  type="number"
                  value={value}
                />
              </div>

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}
            </div>

            <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
              <Button asChild type="button" variant="outline">
                <Link href={listPath}>Cancel</Link>
              </Button>
              <Button disabled={!canSave} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <Save />}
                Save limit
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
