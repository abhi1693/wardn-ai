"use client";

import { Check, KeyRound, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  OrganizationRead,
  UserAPITokenRead,
  UserAPITokenUpdate,
  WorkspaceRead,
} from "@/lib/api/generated/model";

import { errorMessage, type ScopeMode, TokenFields } from "../../token-form";

type EditTokenClientProps = {
  organization: OrganizationRead;
  token: UserAPITokenRead;
  workspaces: WorkspaceRead[];
};

function datetimeLocalValue(value: string | null) {
  if (!value) {
    return "";
  }
  return new Date(value).toISOString().slice(0, 16);
}

function scopeModeForToken(token: UserAPITokenRead): ScopeMode {
  return token.workspaceIds.length > 0 ? "workspaces" : "organization";
}

export function EditTokenClient({ organization, token, workspaces }: EditTokenClientProps) {
  const router = useRouter();
  const [name, setName] = useState(token.name);
  const [description, setDescription] = useState(token.description);
  const [expiresAt, setExpiresAt] = useState(datetimeLocalValue(token.expires_at));
  const [scopeMode, setScopeMode] = useState<ScopeMode>(scopeModeForToken(token));
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<Set<string>>(
    () => new Set(token.workspaceIds)
  );
  const [isActive, setIsActive] = useState(token.is_active);
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
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const payload: UserAPITokenUpdate = {
      name: name.trim(),
      description: description.trim(),
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      is_active: isActive,
      organizationIds: scopeMode === "organization" ? [organization.id] : [],
      workspaceIds: scopeMode === "workspaces" ? Array.from(selectedWorkspaceIds).sort() : [],
    };

    try {
      const response = await fetch(`/api/auth/api-tokens/${token.id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await response.json()) as UserAPITokenRead | { detail?: string };
      if (!response.ok) {
        throw new Error(errorMessage(data, "Token could not be updated."));
      }
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
          <form className="space-y-6" onSubmit={updateToken}>
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
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href={`/org/${organization.id}/tokens`}>Cancel</Link>
              </Button>
              <Button disabled={!canSave} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <Check />}
                Save changes
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
