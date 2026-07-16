"use client";

import { KeyRound, Loader2 } from "lucide-react";
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
  UserAPITokenCreate,
  UserAPITokenCreated,
  WorkspaceRead,
} from "@/lib/api/generated/model";

import {
  createdTokenStorageKey,
  errorMessage,
  type ScopeMode,
  TokenFields,
} from "../token-form";

type CreateTokenClientProps = {
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

export function CreateTokenClient({ organization, workspaces }: CreateTokenClientProps) {
  const router = useRouter();
  const [name, setName] = useState("Wardn MCP Gateway");
  const [description, setDescription] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [scopeMode, setScopeMode] = useState<ScopeMode>("organization");
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<Set<string>>(new Set());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.status === "active"),
    [workspaces]
  );

  const canCreate =
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

  async function createToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canCreate) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const payload: UserAPITokenCreate = {
      name: name.trim(),
      description: description.trim() || undefined,
      expiresAt: expiresAt ? new Date(expiresAt).toISOString() : null,
      organizationIds: scopeMode === "organization" ? [organization.id] : [],
      workspaceIds: scopeMode === "workspaces" ? Array.from(selectedWorkspaceIds).sort() : [],
    };

    try {
      const response = await fetch("/api/auth/api-tokens", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await response.json()) as UserAPITokenCreated | { detail?: string };
      if (!response.ok) {
        throw new Error(errorMessage(data, "Token could not be created."));
      }
      sessionStorage.setItem(
        createdTokenStorageKey(organization.id),
        JSON.stringify(data as UserAPITokenCreated)
      );
      router.push(`/org/${organization.id}/tokens`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Token could not be created.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle>Create Gateway Token</CardTitle>
              <CardDescription>
                Scope access before connecting an MCP client to the common gateway.
              </CardDescription>
            </div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-[var(--surface-container)] text-primary">
              <KeyRound className="size-5" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={createToken}>
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

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href={`/org/${organization.id}/tokens`}>Cancel</Link>
              </Button>
              <Button disabled={!canCreate} type="submit">
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <KeyRound />}
                Create token
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
