import { Plus, Settings } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

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

import { getWorkspaceContext } from "../data";

type OrganizationPageProps = {
  params: Promise<{ organizationId: string }>;
};

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "";
}

export default async function OrganizationPage({ params }: OrganizationPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces;
  if (!organization) {
    notFound();
  }

  const activeWorkspaces = workspaces.filter((workspace) => workspace.status === "active").length;

  return (
    <AppShell
      active="organizations"
      actions={
        <>
          <Button asChild size="sm" variant="outline">
            <Link href={`/organizations/${organization.id}/settings`}>
              <Settings className="size-4" />
              Settings
            </Link>
          </Button>
          <Button asChild size="sm">
            <Link href={`/organizations/${organization.id}/workspaces/new`}>
              <Plus className="size-4" />
              Add workspace
            </Link>
          </Button>
        </>
      }
      eyebrow="Organization"
      title={organization.name}
      workspaceContext={workspaceContext}
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Status</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant={organization.status === "active" ? "success" : "outline"}>
              {organization.status}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Role</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {roleLabel(organization.currentUserRole)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Workspaces</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {activeWorkspaces} / {workspaces.length}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspaces</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspaces.map((workspace) => (
                <TableRow key={workspace.id}>
                  <TableCell>
                    <div className="font-medium">{workspace.name}</div>
                    <div className="text-xs text-muted-foreground">{workspace.slug}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={workspace.status === "active" ? "success" : "outline"}>
                      {workspace.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{roleLabel(workspace.currentUserRole)}</TableCell>
                  <TableCell className="text-right">
                    <Button asChild size="icon" variant="outline">
                      <Link
                        aria-label={`Settings for ${workspace.name}`}
                        href={`/organizations/${organization.id}/workspaces/${workspace.id}/settings`}
                      >
                        <Settings className="size-4" />
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {workspaces.length === 0 ? (
                <TableRow>
                  <TableCell className="h-28 text-center text-muted-foreground" colSpan={4}>
                    No workspaces have been created.
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
