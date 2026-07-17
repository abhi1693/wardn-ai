"use client";

import { Check, Copy, KeyRound, Loader2 } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  OrganizationRead,
  UserAPITokenCreate,
  UserAPITokenCreated,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { authCreateApiToken } from "@/lib/api/generated/auth/auth";

import { type ScopeMode, TokenFields } from "../token-form";

type CreateTokenClientProps = {
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

export function CreateTokenClient({ organization, workspaces }: CreateTokenClientProps) {
  const [name, setName] = useState("Wardn MCP Gateway");
  const [description, setDescription] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [scopeMode, setScopeMode] = useState<ScopeMode>("organization");
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<Set<string>>(new Set());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdToken, setCreatedToken] = useState<UserAPITokenCreated | null>(null);
  const [copied, setCopied] = useState(false);

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

  async function copyCreatedToken() {
    if (!createdToken?.token) {
      return;
    }
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(createdToken.token);
    } else {
      const field = document.createElement("textarea");
      field.value = createdToken.token;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.top = "-1000px";
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      document.body.removeChild(field);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_600);
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
      const data = await authCreateApiToken(payload);
      setCreatedToken(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Token could not be created.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (createdToken) {
    return (
      <div className="max-w-4xl space-y-6">
        <div aria-live="polite" className="sr-only" role="status">
          Token created. Copy it now because it will not be shown again.
        </div>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2 text-emerald-700">
              <Check className="size-5" />
              <CardTitle>Token created</CardTitle>
            </div>
            <CardDescription>
              Copy this token now. It is held only in this page&apos;s memory and is not shown again.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="created-token">Token</Label>
              <div className="mt-2 flex gap-2">
                <Input
                  autoComplete="off"
                  className="font-mono text-xs"
                  id="created-token"
                  readOnly
                  spellCheck={false}
                  type="text"
                  value={createdToken.token}
                />
                <Button
                  aria-label="Copy token"
                  onClick={copyCreatedToken}
                  size="icon"
                  type="button"
                  variant="outline"
                >
                  {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                </Button>
                {copied ? (
                  <span aria-live="polite" className="sr-only" role="status">
                    Token copied to clipboard.
                  </span>
                ) : null}
              </div>
            </div>
            <div className="flex justify-end">
              <Button asChild>
                <Link href={`/org/${organization.id}/tokens`}>Done</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
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
              <AsyncFeedback variant="error">{error}</AsyncFeedback>
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
