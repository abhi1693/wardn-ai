import { Plus, Settings } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { OpenWorkspaceButton } from "@/app/components/open-workspace-button";
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
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationWorkspacesPageProps = {
  params: Promise<{ organizationId: string }>;
};

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "";
}

export default async function OrganizationWorkspacesPage({
  params,
}: OrganizationWorkspacesPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, workspaces] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
  ]);

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="dashboard"
      actions={
        <>
          <Button asChild size="sm" variant="outline">
            <Link href="/org">Change organization</Link>
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
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Workspaces</CardTitle>
            <Badge variant={organization.status === "active" ? "success" : "outline"}>
              {organization.status}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="w-44" />
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
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button asChild size="icon" variant="outline">
                        <Link
                          aria-label={`Settings for ${workspace.name}`}
                          href={`/organizations/${organization.id}/workspaces/${workspace.id}/settings`}
                        >
                          <Settings className="size-4" />
                        </Link>
                      </Button>
                      <OpenWorkspaceButton
                        organizationId={workspace.organizationId}
                        workspaceId={workspace.id}
                      />
                    </div>
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
