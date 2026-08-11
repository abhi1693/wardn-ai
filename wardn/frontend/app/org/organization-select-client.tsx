"use client";

import { ArrowRight, Building2, CheckCircle2, Loader2, MailPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/atoms/card";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import type {
  InvitationAcceptanceRead,
  OrganizationRead,
  PendingInvitationRead,
} from "@/lib/api/generated/model";
import { invitationsPendingAccept } from "@/lib/api/generated/invitations/invitations";
import { clearSelectionCookie, setSelectionCookie } from "@/lib/selection-cookies";
import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

type OrganizationSelectClientProps = {
  organizations: OrganizationRead[];
  pendingInvitations: PendingInvitationRead[];
};

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "";
}

function invitationDestination(acceptance: InvitationAcceptanceRead) {
  if (acceptance.workspaceId) {
    return `/org/${encodeURIComponent(acceptance.organizationId)}/workspace/${encodeURIComponent(
      acceptance.workspaceId
    )}/dashboard`;
  }
  return `/org/${encodeURIComponent(acceptance.organizationId)}/dashboard`;
}

export function OrganizationSelectClient({
  organizations,
  pendingInvitations,
}: OrganizationSelectClientProps) {
  const router = useRouter();
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  function selectOrganization(organizationId: string) {
    setSelectionCookie(selectedOrganizationCookie, organizationId);
    clearSelectionCookie(selectedWorkspaceCookie);
    router.push(`/org/${encodeURIComponent(organizationId)}/dashboard`);
    router.refresh();
  }

  async function acceptInvitation(invitationId: string) {
    setAcceptingId(invitationId);
    setError("");
    try {
      const acceptance = await invitationsPendingAccept(invitationId);
      router.push(invitationDestination(acceptance));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invitation could not be accepted.");
      setAcceptingId(null);
    }
  }

  return (
    <div className="grid gap-5">
      {pendingInvitations.length > 0 ? (
        <section className="grid gap-3" aria-labelledby="pending-invitations-title">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold leading-6" id="pending-invitations-title">
                Pending invitations
              </h2>
              <p className="text-sm text-muted-foreground">Join an organization you were invited to.</p>
            </div>
            <Badge variant="outline">{pendingInvitations.length}</Badge>
          </div>
          {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {pendingInvitations.map((invitation) => (
              <Card key={invitation.id}>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="truncate">
                        {invitation.workspaceName ?? invitation.organizationName}
                      </CardTitle>
                      <div className="mt-1 truncate text-sm text-muted-foreground">
                        {invitation.scopeType === "workspace"
                          ? invitation.organizationName
                          : "Organization invitation"}
                      </div>
                    </div>
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted text-muted-foreground">
                      <MailPlus className="size-4" />
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-4">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{roleLabel(invitation.role)}</Badge>
                    <Badge variant="success">
                      <CheckCircle2 className="size-3" />
                      Pending
                    </Badge>
                  </div>
                  <Button
                    className="justify-between"
                    disabled={acceptingId !== null}
                    onClick={() => acceptInvitation(invitation.id)}
                    type="button"
                  >
                    {acceptingId === invitation.id ? "Joining" : "Accept invitation"}
                    {acceptingId === invitation.id ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <ArrowRight className="size-4" />
                    )}
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      ) : null}

      {organizations.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {organizations.map((organization) => (
            <Card key={organization.id}>
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="truncate">{organization.name}</CardTitle>
                    <div className="mt-1 truncate text-sm text-muted-foreground">
                      {organization.slug}
                    </div>
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
      ) : null}
    </div>
  );
}
