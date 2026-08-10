"use client";

import { KeyRound, Loader2, Pencil, PlugZap, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { EmptyState } from "@/components/molecules/empty-state";
import type { OrganizationRead, WorkspaceRead } from "@/lib/api/generated/model";
import { llmProviderCredentialsDelete } from "@/lib/api/generated/llm-provider-credentials/llm-provider-credentials";

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
  if (credential.provider === "anthropic") {
    return "Anthropic";
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

function statusPresentation(credential: LlmCredentialRead) {
  if (credential.status === "expired") {
    return { label: "Expired", variant: "destructive" as const };
  }
  if (credential.status === "active") {
    return { label: "Active", variant: "success" as const };
  }
  return { label: "Inactive", variant: "secondary" as const };
}

export function CredentialsClient({
  credentials: initialCredentials,
  organization,
  workspaces,
}: CredentialsClientProps) {
  const [credentials, setCredentials] = useState(initialCredentials);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);

  async function deleteCredential(credential: LlmCredentialRead) {
    setDeletingCredentialId(credential.id);
    try {
      await llmProviderCredentialsDelete(organization.id, credential.id);
      setCredentials((current) => current.filter((entry) => entry.id !== credential.id));
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
              {credentials.map((credential) => {
                const status = statusPresentation(credential);
                return (
                  <TableRow key={credential.id}>
                    <TableCell>
                      <div className="min-w-48">
                        <div className="font-medium">{credential.name}</div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={credential.authMethod === "oauth" ? "secondary" : "outline"}
                      >
                        {providerLabel(credential)}
                      </Badge>
                    </TableCell>
                    <TableCell>{scopeLabel(credential, workspaces)}</TableCell>
                    <TableCell>
                      <Badge variant={status.variant}>{status.label}</Badge>
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
                        <ConfirmActionDialog
                          actionLabel="Delete credential"
                          description={`Agents using ${credential.name} will no longer be able to call this provider.`}
                          onConfirm={() => deleteCredential(credential)}
                          title={`Delete ${credential.name}?`}
                          variant="destructive"
                        >
                          <Button
                            aria-label={`Delete ${credential.name}`}
                            disabled={deletingCredentialId === credential.id}
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
                        </ConfirmActionDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            action={
              <Button asChild size="sm">
                <Link href={`/org/${organization.id}/llm-credentials/new`}>
                  <KeyRound className="size-4" />
                  New credential
                </Link>
              </Button>
            }
            description="Create an API key or OAuth credential before assigning agents to a model."
            icon={PlugZap}
            title="No LLM credentials"
          />
        )}
      </CardContent>
    </Card>
  );
}
