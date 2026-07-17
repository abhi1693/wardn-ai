"use client";

import {
  KeyRound,
  Loader2,
  Pencil,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { AsyncFeedback } from "@/components/ui/async-feedback";
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
import type {
  OrganizationRead,
  UserAPITokenRead,
} from "@/lib/api/generated/model";
import { authDeleteApiToken } from "@/lib/api/generated/auth/auth";

type AgentTokensClientProps = {
  initialTokens: UserAPITokenRead[];
  organization: OrganizationRead;
};

function formatDate(value: string | null) {
  if (!value) {
    return "Never";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function scopeLabel(token: UserAPITokenRead, organization: OrganizationRead) {
  if (token.workspaceIds.length > 0) {
    return `${token.workspaceIds.length} workspace${token.workspaceIds.length === 1 ? "" : "s"}`;
  }
  if (token.organizationIds.includes(organization.id)) {
    return organization.name;
  }
  return "Organization scope";
}

export function AgentTokensClient({
  initialTokens,
  organization,
}: AgentTokensClientProps) {
  const [tokens, setTokens] = useState<UserAPITokenRead[]>(initialTokens);
  const [deletingTokenId, setDeletingTokenId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function deleteToken(token: UserAPITokenRead) {
    if (!window.confirm(`Delete ${token.name}?`)) {
      return;
    }

    setDeletingTokenId(token.id);
    setError(null);
    try {
      await authDeleteApiToken(token.id);
      setTokens((current) => current.filter((entry) => entry.id !== token.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Token could not be deleted.");
    } finally {
      setDeletingTokenId(null);
    }
  }

  return (
    <>
      <div>
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>Agent Tokens</CardTitle>
                <CardDescription>
                  Manage bearer tokens for the common MCP gateway.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {error ? (
              <AsyncFeedback variant="error">{error}</AsyncFeedback>
            ) : null}

            {tokens.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Scope</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead>Last used</TableHead>
                    <TableHead className="w-28 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tokens.map((token) => (
                    <TableRow key={token.id}>
                      <TableCell>
                        <div className="min-w-48">
                          <div className="font-medium">{token.name}</div>
                          <div className="mt-1 max-w-72 truncate text-xs text-[var(--on-surface-variant)]">
                            {token.description || token.tokenPrefix}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm">{scopeLabel(token, organization)}</span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={token.isActive ? "success" : "secondary"}>
                          {token.isActive ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell>{formatDate(token.expiresAt)}</TableCell>
                      <TableCell>{formatDate(token.lastUsedAt)}</TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-2">
                          <Button
                            asChild
                            aria-label={`Edit ${token.name}`}
                            size="icon"
                            variant="outline"
                          >
                            <Link href={`/org/${organization.id}/tokens/${token.id}/edit`}>
                              <Pencil className="size-4" />
                            </Link>
                          </Button>
                          <Button
                            aria-label={`Delete ${token.name}`}
                            disabled={deletingTokenId === token.id}
                            onClick={() => deleteToken(token)}
                            size="icon"
                            type="button"
                            variant="outline"
                          >
                            {deletingTokenId === token.id ? (
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
                  <KeyRound className="size-5" />
                </div>
                <h3 className="text-base font-semibold">No agent tokens</h3>
                <p className="mt-1 text-sm text-[var(--on-surface-variant)]">
                  Create a scoped token to connect an MCP client to the common gateway.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

    </>
  );
}
