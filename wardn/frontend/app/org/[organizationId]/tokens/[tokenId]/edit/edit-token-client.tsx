"use client";

import { Check, KeyRound, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

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
import type {
  OrganizationRead,
  UserAPITokenRead,
  UserAPITokenUpdate,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { authUpdateApiToken } from "@/lib/api/generated/auth/auth";
import { formatUserDateTimeInputValue, parseUserDateTimeInputValue } from "@/lib/date-time";
import { useFormSafety } from "@/hooks/use-form-safety";

import { type ScopeMode, TokenFields } from "../../token-form";

type EditTokenClientProps = {
  organization: OrganizationRead;
  token: UserAPITokenRead;
  workspaces: WorkspaceRead[];
};

function scopeModeForToken(token: UserAPITokenRead): ScopeMode {
  return token.workspaceIds.length > 0 ? "workspaces" : "organization";
}

export function EditTokenClient({ organization, token, workspaces }: EditTokenClientProps) {
  const router = useRouter();
  const [name, setName] = useState(token.name);
  const [description, setDescription] = useState(token.description);
  const [expiresAt, setExpiresAt] = useState(formatUserDateTimeInputValue(token.expiresAt));
  const [scopeMode, setScopeMode] = useState<ScopeMode>(scopeModeForToken(token));
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<Set<string>>(
    () => new Set(token.workspaceIds)
  );
  const [isActive, setIsActive] = useState(token.isActive);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.status === "active"),
    [workspaces]
  );

  const canSave =
    name.trim().length > 0 &&
    !isSubmitting &&
    (scopeMode !== "workspaces" || selectedWorkspaceIds.size > 0);
  const { isDirty } = useFormSafety({
    currentValue: { description, expiresAt, isActive, name, scopeMode, selectedWorkspaceIds },
    formId: "edit-token-form",
    initialValue: {
      description: token.description,
      expiresAt: formatUserDateTimeInputValue(token.expiresAt),
      isActive: token.isActive,
      name: token.name,
      scopeMode: scopeModeForToken(token),
      selectedWorkspaceIds: new Set(token.workspaceIds),
    },
    isSaving: isSubmitting,
  });

  function toggleWorkspace(workspaceId: string) {
    setSelectedWorkspaceIds((current) => {
      const next = new Set(current);
      if (next.has(workspaceId)) {
        next.delete(workspaceId);
      } else {
        next.add(workspaceId);
      }
      return next;
    });
  }

  async function updateToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) {
      focusFirstInvalidFormControl(
        "edit-token-form",
        name.trim() ? "token-workspaces" : "token-name"
      );
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const payload: UserAPITokenUpdate = {
      name: name.trim(),
      description: description.trim(),
      expiresAt: parseUserDateTimeInputValue(expiresAt),
      isActive,
      organizationIds: scopeMode === "organization" ? [organization.id] : [],
      workspaceIds: scopeMode === "workspaces" ? Array.from(selectedWorkspaceIds).sort() : [],
    };

    try {
      await authUpdateApiToken(token.id, payload);
      router.push(`/org/${organization.id}/tokens`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Token could not be updated.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle>Edit Gateway Token</CardTitle>
              <CardDescription>
                Update metadata, status, expiration, and gateway scope.
              </CardDescription>
            </div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <KeyRound className="size-5" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" id="edit-token-form" onSubmit={updateToken}>
            <TokenFields
              activeWorkspaces={activeWorkspaces}
              description={description}
              expiresAt={expiresAt}
              name={name}
              onDescriptionChange={setDescription}
              onExpiresAtChange={setExpiresAt}
              onNameChange={setName}
              onScopeModeChange={setScopeMode}
              onWorkspaceToggle={toggleWorkspace}
              scopeMode={scopeMode}
              selectedWorkspaceIds={selectedWorkspaceIds}
            />

            <label className="flex min-h-10 items-center gap-3 rounded-md border border-[var(--outline-variant)] px-3 text-sm">
              <input
                checked={isActive}
                className="size-4 accent-primary"
                onChange={(event) => setIsActive(event.target.checked)}
                type="checkbox"
              />
              Active
            </label>

            {error ? (
              <AsyncFeedback variant="error">{error}</AsyncFeedback>
            ) : null}

            <StickyFormActions className="-mx-6 -mb-6 px-6" position="bottom">
              <Button asChild type="button" variant="outline">
                <Link href={`/org/${organization.id}/tokens`}>Cancel</Link>
              </Button>
              <Button disabled={isSubmitting || !isDirty} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <Check />}
                Save changes
              </Button>
            </StickyFormActions>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
