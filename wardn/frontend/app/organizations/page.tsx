import { Plus, Settings } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { getOrganizations, getWorkspaceContext, getWorkspaces } from "./data";

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "";
}

export default async function OrganizationsPage() {
  const workspaceContext = await getWorkspaceContext();
  const organizations = await getOrganizations();
  const workspaceCounts = new Map(
    await Promise.all(
      organizations.map(async (organization) => [
        organization.id,
        (await getWorkspaces(organization.id)).length,
      ] as const)
    )
  );

  return (
    <AppShell
      active="organizations"
      actions={
        <Button asChild size="sm">
          <Link href="/organizations/new">
            <Plus className="size-4" />
            Add organization
          </Link>
        </Button>
      }
      eyebrow="Administration"
      title="Organizations"
      workspaceContext={workspaceContext}
    >
      <Card>
        <CardHeader>
          <CardTitle>Organizations</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Workspaces</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {organizations.map((organization) => (
                <TableRow key={organization.id}>
                  <TableCell>
                    <Link
                      className="font-medium text-foreground hover:underline"
                      href={`/organizations/${organization.id}`}
                    >
                      {organization.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{organization.slug}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={organization.status === "active" ? "success" : "outline"}>
                      {organization.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{roleLabel(organization.currentUserRole)}</TableCell>
                  <TableCell>{workspaceCounts.get(organization.id) ?? 0}</TableCell>
                  <TableCell className="text-right">
                    <Button asChild size="icon" variant="outline">
                      <Link aria-label={`Settings for ${organization.name}`} href={`/organizations/${organization.id}/settings`}>
                        <Settings className="size-4" />
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {organizations.length === 0 ? (
                <TableRow>
                  <TableCell className="h-28 text-center text-muted-foreground" colSpan={5}>
                    No organizations are available.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </AppShell>
  );
}
