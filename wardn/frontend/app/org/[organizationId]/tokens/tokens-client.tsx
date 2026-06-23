"use client";

import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  Pencil,
  Trash2,
} from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  UserAPITokenCreated,
  UserAPITokenRead,
} from "@/lib/api/generated/model";
import { createdTokenStorageKey, errorMessage } from "./token-form";

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

function readCreatedToken(organizationId: string) {
  if (typeof window === "undefined") {
    return null;
  }
  const key = createdTokenStorageKey(organizationId);
  const stored = sessionStorage.getItem(key);
  if (!stored) {
    return null;
  }
  sessionStorage.removeItem(key);
  try {
    const parsed = JSON.parse(stored) as UserAPITokenCreated;
    return parsed.token && parsed.record?.id ? parsed : null;
  } catch {
    return null;
  }
}

export function AgentTokensClient({
  initialTokens,
  organization,
}: AgentTokensClientProps) {
  const [createdToken, setCreatedToken] = useState<UserAPITokenCreated | null>(() =>
    readCreatedToken(organization.id)
  );
  const [tokens, setTokens] = useState<UserAPITokenRead[]>(() => {
    if (
      createdToken &&
      !initialTokens.some((token) => token.id === createdToken.record.id)
    ) {
      return [createdToken.record, ...initialTokens];
    }
    return initialTokens;
  });
  const [deletingTokenId, setDeletingTokenId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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
    window.setTimeout(() => setCopied(false), 1600);
  }

  async function deleteToken(token: UserAPITokenRead) {
    if (!window.confirm(`Delete ${token.name}?`)) {
      return;
    }

    setDeletingTokenId(token.id);
    setError(null);
    try {
      const response = await fetch(`/api/auth/api-tokens/${token.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(errorMessage(data, "Token could not be deleted."));
      }
      setTokens((current) => current.filter((entry) => entry.id !== token.id));
      if (createdToken?.record.id === token.id) {
        setCreatedToken(null);
      }
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
            {createdToken ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-800">
                  <Check className="size-4" />
                  Token created
                </div>
                <Label htmlFor="created-token">Token</Label>
                <div className="mt-2 flex gap-2">
                  <Input
                    className="font-mono text-xs"
                    id="created-token"
                    readOnly
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
                </div>
                <p className="mt-3 text-xs leading-5 text-emerald-800">
                  Store this value now. It is not shown again.
                </p>
              </div>
            ) : null}

            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
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
                            {token.description || token.token_prefix}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm">{scopeLabel(token, organization)}</span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={token.is_active ? "success" : "secondary"}>
                          {token.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell>{formatDate(token.expires_at)}</TableCell>
                      <TableCell>{formatDate(token.last_used_at)}</TableCell>
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
