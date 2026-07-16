"use client";

import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  ResourceLimitRead,
  UserRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";

import { displayLimitKey, formatDate, scopeLabel } from "./limit-display";

type LimitsClientProps = {
  currentUser: UserRead | null;
  initialLimits: ResourceLimitRead[];
  organizationId: string;
  organizations: OrganizationRead[];
  workspaces: WorkspaceRead[];
};

export function LimitsClient({
  currentUser,
  initialLimits,
  organizationId,
  organizations,
  workspaces,
}: LimitsClientProps) {
  const [filter, setFilter] = useState("all");
  const filteredLimits = useMemo(
    () => initialLimits.filter((limit) => filter === "all" || limit.scopeType === filter),
    [filter, initialLimits]
  );

  if (!currentUser?.isSuperuser) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Access required</CardTitle>
          <CardDescription>Only superusers can manage resource limits.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Configured Limits</CardTitle>
            <CardDescription>Workspace limits override organization defaults.</CardDescription>
          </div>
          <Select onValueChange={setFilter} value={filter}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All scopes</SelectItem>
              <SelectItem value="organization">Organization</SelectItem>
              <SelectItem value="workspace">Workspace</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        {filteredLimits.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Limit</TableHead>
                <TableHead className="min-w-56">Scope</TableHead>
                <TableHead className="w-24 text-right">Value</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead className="w-28 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredLimits.map((limit) => (
                <TableRow key={limit.id}>
                  <TableCell>
                    <div className="font-medium">{displayLimitKey(limit.limitKey)}</div>
                    <div className="mt-1 font-mono text-xs text-[var(--on-surface-variant)]">
                      {limit.limitKey}
                    </div>
                  </TableCell>
                  <TableCell className="min-w-56">
                    <div className="min-w-0 truncate text-sm">
                      {scopeLabel(limit, organizations, workspaces)}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono">{limit.value}</TableCell>
                  <TableCell>{formatDate(limit.updatedAt)}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button asChild aria-label="Edit limit" size="icon" variant="outline">
                        <Link href={`/org/${organizationId}/limits/${limit.id}/edit`}>
                          <Pencil className="size-4" />
                        </Link>
                      </Button>
                      <Button asChild aria-label="Delete limit" size="icon" variant="outline">
                        <Link href={`/org/${organizationId}/limits/${limit.id}/delete`}>
                          <Trash2 className="size-4" />
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="flex min-h-40 items-center justify-center rounded-md border border-dashed text-sm text-[var(--on-surface-variant)]">
            No limits configured.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
