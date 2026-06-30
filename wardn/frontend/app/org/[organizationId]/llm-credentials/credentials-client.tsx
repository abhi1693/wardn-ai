"use client";

import { KeyRound, Loader2, Pencil, PlugZap, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
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
import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";

import { errorMessage } from "../tokens/token-form";
import type { LlmCredentialRead } from "./types";

type CredentialsClientProps = {
  credentials: LlmCredentialRead[];
  organization: OrganizationRead;
  workspaces: WorkspaceRead[];
};

function workspaceName(workspaces: WorkspaceRead[], workspaceId?: string | null) {
  if (!workspaceId) {
    return null;
  }
  return workspaces.find((workspace) => workspace.id === workspaceId)?.name ?? workspaceId;
}

function providerLabel(credential: LlmCredentialRead) {
  if (credential.provider === "openai_chatgpt" || credential.authMethod === "oauth") {
    return "OpenAI ChatGPT";
  }
  if (credential.provider === "openai") {
    return "OpenAI";
  }
  return credential.provider;
}

function scopeLabel(credential: LlmCredentialRead, workspaces: WorkspaceRead[]) {
  if (credential.visibility === "workspace") {
    return workspaceName(workspaces, credential.workspaceId) ?? "Workspace";
  }
  if (credential.visibility === "user") {
    return "User";
  }
  return "Organization";
}

export function CredentialsClient({
  credentials: initialCredentials,
  organization,
  workspaces,
}: CredentialsClientProps) {
  const [credentials, setCredentials] = useState(initialCredentials);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function deleteCredential(credential: LlmCredentialRead) {
    if (!window.confirm(`Delete ${credential.name}?`)) {
      return;
    }

    setDeletingCredentialId(credential.id);
    setError(null);
    try {
      const response = await fetch(
        `/api/organizations/${organization.id}/llm/provider-credentials/${credential.id}`,
        { method: "DELETE" }
      );
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(errorMessage(data, "Credential could not be deleted."));
      }
      setCredentials((current) => current.filter((entry) => entry.id !== credential.id));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Credential could not be deleted."
      );
    } finally {
      setDeletingCredentialId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM Credentials</CardTitle>
        <CardDescription>
          Provider credentials available to Wardn agents.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {credentials.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-28 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {credentials.map((credential) => (
                <TableRow key={credential.id}>
                  <TableCell>
                    <div className="min-w-48">
                      <div className="font-medium">{credential.name}</div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={credential.authMethod === "oauth" ? "secondary" : "outline"}>
                      {providerLabel(credential)}
                    </Badge>
                  </TableCell>
                  <TableCell>{scopeLabel(credential, workspaces)}</TableCell>
                  <TableCell>
                    <Badge variant={credential.isActive ? "success" : "secondary"}>
                      {credential.isActive ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        asChild
                        aria-label={`Edit ${credential.name}`}
                        size="icon"
                        variant="outline"
                      >
                        <Link
                          href={`/org/${organization.id}/llm-credentials/${credential.id}/edit`}
                        >
                          <Pencil className="size-4" />
                        </Link>
                      </Button>
                      <Button
                        aria-label={`Delete ${credential.name}`}
                        disabled={deletingCredentialId === credential.id}
                        onClick={() => deleteCredential(credential)}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        {deletingCredentialId === credential.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
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
              <PlugZap className="size-5" />
            </div>
            <h3 className="text-base font-semibold">No LLM credentials</h3>
            <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
              Create an API key or OAuth credential before assigning agents to a model.
            </p>
            <Button asChild className="mt-4" size="sm">
              <Link href={`/org/${organization.id}/llm-credentials/new`}>
                <KeyRound className="size-4" />
                New credential
              </Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
