"use client";

import { ArrowRight, Building2 } from "lucide-react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OrganizationRead } from "@/lib/api/generated/model";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OrganizationSelectClientProps = {
  organizations: OrganizationRead[];
};

function setSelectionCookie(name: string, value: string, maxAge = 31536000) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax`;
}

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "";
}

export function OrganizationSelectClient({ organizations }: OrganizationSelectClientProps) {
  const router = useRouter();

  function selectOrganization(organizationId: string) {
    setSelectionCookie(selectedOrganizationCookie, organizationId);
    setSelectionCookie(selectedWorkspaceCookie, "", 0);
    router.push(`/org/${encodeURIComponent(organizationId)}/dashboard`);
    router.refresh();
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {organizations.map((organization) => (
        <Card key={organization.id}>
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <CardTitle className="truncate">{organization.name}</CardTitle>
                <div className="mt-1 truncate text-sm text-muted-foreground">{organization.slug}</div>
              </div>
              <div className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted text-muted-foreground">
                <Building2 className="size-4" />
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="flex items-center gap-2">
              <Badge variant={organization.status === "active" ? "success" : "outline"}>
                {organization.status}
              </Badge>
              <Badge variant="outline">{roleLabel(organization.currentUserRole)}</Badge>
            </div>
            <Button
              className="justify-between"
              onClick={() => selectOrganization(organization.id)}
              type="button"
            >
              Select organization
              <ArrowRight className="size-4" />
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
