"use client";

import { Loader2, Save, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/atoms/button";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { focusFirstInvalidFormControl } from "@/components/molecules/form-error-summary";
import { StickyFormActions } from "@/components/organisms/sticky-form-actions";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import { Input } from "@/components/atoms/input";
import { Label } from "@/components/atoms/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import type {
  OrganizationRead,
  ResourceLimitRead,
  ResourceLimitUpsert,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { limitsUpsert } from "@/lib/api/generated/limits/limits";
import { useFormSafety } from "@/hooks/use-form-safety";

import {
  displayLimitKey,
  knownLimitKeys,
  limitValueHelp,
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
  const valueHelp = limitValueHelp(selectedKey);
  const organizationName = organizations[0]?.name ?? "Current organization";
  const parsedValue = Number(value);
  const canSave =
    selectedKey.trim().length > 0 &&
    Number.isInteger(parsedValue) &&
    parsedValue >= 0 &&
    !isSubmitting &&
    scopeId.trim().length > 0;
  const { isDirty } = useFormSafety({
    currentValue: { limitKey, scopeId, scopeType, value },
    formId: "limit-form",
    initialValue: {
      limitKey: initialLimit?.limitKey ?? initialKnownKey.value,
      scopeId: initialLimit?.scopeId ?? organizationId,
      scopeType:
        (initialLimit?.scopeType as LimitScopeType | undefined) ?? initialKnownKey.defaultScope,
      value: String(initialLimit?.value ?? 10),
    },
    isSaving: isSubmitting,
  });

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
      focusFirstInvalidFormControl(
        "limit-form",
        !scopeId.trim() ? "limit-target" : "limit-value"
      );
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await limitsUpsert({
        scopeType: isEdit ? initialLimit.scopeType : scopeType,
        scopeId: isEdit ? initialLimit.scopeId : scopeId.trim(),
        limitKey: selectedKey.trim(),
        value: parsedValue,
      } as ResourceLimitUpsert);
      router.push(listPath);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Limit could not be saved.");
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <Card className="overflow-hidden">
        <CardHeader className="bg-card">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle>{isEdit ? "Edit Limit" : "Create Limit"}</CardTitle>
              <CardDescription>
                {isEdit
                  ? "Update the quota value for this limit."
                  : "Set a quota for this organization or one of its workspaces."}
              </CardDescription>
            </div>
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
              <SlidersHorizontal className="size-4" />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <form id="limit-form" onSubmit={submit}>
            <div className="space-y-5 p-4">
              {isEdit ? (
                <div className="grid gap-0 overflow-hidden rounded-md border bg-card sm:grid-cols-2">
                  <div className="border-b p-3 sm:border-b-0 sm:border-r">
                    <div className="text-xs font-medium text-muted-foreground">Limit</div>
                    <div className="mt-1 text-sm">{displayLimitKey(initialLimit.limitKey)}</div>
                  </div>
                  <div className="p-3">
                    <div className="text-xs font-medium text-muted-foreground">Target</div>
                    <div className="mt-1 truncate text-sm">
                      {scopeLabel(initialLimit, organizations, workspaces)}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
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
                        <SelectTrigger className="mt-2" id="limit-target">
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
                      <div className="mt-2 flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm">
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
                  required
                  value={value}
                />
                {valueHelp ? (
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{valueHelp}</p>
                ) : null}
              </div>

              {error ? (
                <AsyncFeedback variant="error">{error}</AsyncFeedback>
              ) : null}
            </div>

            <StickyFormActions className="px-4" position="bottom">
              <Button asChild type="button" variant="outline">
                <Link href={listPath}>Cancel</Link>
              </Button>
              <Button disabled={isSubmitting || (Boolean(isEdit) && !isDirty)} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <Save />}
                Save limit
              </Button>
            </StickyFormActions>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
