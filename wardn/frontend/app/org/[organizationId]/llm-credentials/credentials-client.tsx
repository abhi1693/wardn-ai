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
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { DataTableColumnHeader } from "@/components/molecules/data-table-column-header";
import { EmptyState } from "@/components/molecules/empty-state";
import {
  DataTable,
  type DataTableColumnDef,
} from "@/components/organisms/data-table";
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

  const columns: DataTableColumnDef<LlmCredentialRead>[] = [
    {
      accessorKey: "name",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
      cell: ({ row }) => <div className="min-w-48 font-medium">{row.original.name}</div>,
    },
    {
      accessorKey: "provider",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Provider" />,
      cell: ({ row }) => (
        <Badge variant={row.original.authMethod === "oauth" ? "secondary" : "outline"}>
          {providerLabel(row.original)}
        </Badge>
      ),
    },
    {
      id: "scope",
      accessorFn: (credential) => scopeLabel(credential, workspaces),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Scope" />,
    },
    {
      accessorKey: "status",
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      cell: ({ row }) => {
        const status = statusPresentation(row.original);
        return <Badge variant={status.variant}>{status.label}</Badge>;
      },
    },
    {
      id: "actions",
      enableHiding: false,
      enableSorting: false,
      header: () => <div className="text-right">Actions</div>,
      cell: ({ row }) => {
        const credential = row.original;
        return (
          <div className="flex justify-end gap-2">
            <Button
              asChild
              aria-label={`Edit ${credential.name}`}
              size="icon"
              variant="outline"
            >
              <Link href={`/org/${organization.id}/llm-credentials/${credential.id}/edit`}>
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
        );
      },
    },
  ];

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
          <DataTable
            columns={columns}
            data={credentials}
            filters={[
              {
                columnId: "provider",
                label: "Provider",
                options: [
                  { label: "OpenAI", value: "openai" },
                  { label: "OpenAI ChatGPT", value: "openai_chatgpt" },
                  { label: "Anthropic", value: "anthropic" },
                ],
              },
              {
                columnId: "status",
                label: "Status",
                options: [
                  { label: "Active", value: "active" },
                  { label: "Inactive", value: "inactive" },
                  { label: "Expired", value: "expired" },
                ],
              },
            ]}
            getRowId={(credential) => credential.id}
            pageSize={15}
            search={{ columnId: "name", placeholder: "Search credentials" }}
            urlSyncKey="credentials"
          />
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
