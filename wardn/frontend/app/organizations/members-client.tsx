"use client";

import { Check, Copy, Loader2, MailPlus, ShieldCheck, Trash2, Users } from "lucide-react";
import type { FormEvent } from "react";
import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import { Input } from "@/components/atoms/input";
import { Label } from "@/components/atoms/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { EmptyState } from "@/components/molecules/empty-state";
import type { InvitationRead, MemberListResponse, MemberRead } from "@/lib/api/generated/model";
import {
  organizationInvitationsCreate,
  organizationInvitationsRevoke,
  organizationMembersRemove,
  organizationMembersUpdate,
  workspaceInvitationsCreate,
  workspaceInvitationsRevoke,
  workspaceMembersRemove,
  workspaceMembersUpdate,
} from "@/lib/api/generated/memberships/memberships";
import { formatUserDateTime } from "@/lib/date-time";

type MembersClientProps = {
  initialInvitations: InvitationRead[];
  memberList: MemberListResponse;
  organizationId: string;
  scopeName: string;
  scopeType: "organization" | "workspace";
  workspaceId?: string;
};

type Role = "owner" | "admin" | "member";

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "Member";
}

function statusVariant(status: InvitationRead["status"]) {
  if (status === "pending") {
    return "outline" as const;
  }
  if (status === "accepted") {
    return "success" as const;
  }
  return "secondary" as const;
}

export function MembersClient({
  initialInvitations,
  memberList,
  organizationId,
  scopeName,
  scopeType,
  workspaceId,
}: MembersClientProps) {
  const router = useRouter();
  const [members, setMembers] = useState(memberList.members);
  const [invitations, setInvitations] = useState(initialInvitations);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [submitting, setSubmitting] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const inviteLinkInput = useRef<HTMLInputElement>(null);
  const canInvite = memberList.canManage;
  const roleOptions = useMemo<Role[]>(
    () => (memberList.canManageOwners ? ["owner", "admin", "member"] : ["admin", "member"]),
    [memberList.canManageOwners]
  );

  async function createInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || submitting) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setInviteLink(null);
    setCopied(false);
    try {
      const created =
        scopeType === "organization"
          ? await organizationInvitationsCreate(organizationId, { email: email.trim(), role })
          : await workspaceInvitationsCreate(organizationId, workspaceId ?? "", {
              email: email.trim(),
              role,
            });
      setInvitations((current) => [created.invitation, ...current]);
      setInviteLink(`${window.location.origin}/invitations/${encodeURIComponent(created.token)}`);
      setEmail("");
      setRole("member");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invitation could not be created.");
    } finally {
      setSubmitting(false);
    }
  }

  async function copyInvitationLink() {
    if (!inviteLink) {
      return;
    }
    setError(null);
    let didCopy = false;
    if (window.isSecureContext && navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(inviteLink);
        didCopy = true;
      } catch {
        // Fall through to selection-based copying for restrictive browser policies.
      }
    }
    if (!didCopy && inviteLinkInput.current) {
      inviteLinkInput.current.focus();
      inviteLinkInput.current.select();
      didCopy = document.execCommand("copy");
    }
    if (didCopy) {
      setCopied(true);
    } else {
      setError("The link could not be copied automatically. Select and copy it manually.");
    }
  }

  async function updateMember(member: MemberRead, nextRole: Role) {
    if (!member.membershipId) {
      return;
    }
    setUpdatingId(member.membershipId);
    setError(null);
    try {
      const updated =
        scopeType === "organization"
          ? await organizationMembersUpdate(organizationId, member.membershipId, {
              role: nextRole,
            })
          : await workspaceMembersUpdate(
              organizationId,
              workspaceId ?? "",
              member.membershipId,
              { role: nextRole }
            );
      setMembers((current) =>
        current.map((entry) => (entry.userId === updated.userId ? updated : entry))
      );
      if (member.userId === memberList.currentUserId) {
        router.refresh();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Member role could not be updated.");
    } finally {
      setUpdatingId(null);
    }
  }

  async function removeMember(member: MemberRead) {
    if (!member.membershipId) {
      return;
    }
    setUpdatingId(member.membershipId);
    setError(null);
    try {
      if (scopeType === "organization") {
        await organizationMembersRemove(organizationId, member.membershipId);
      } else {
        await workspaceMembersRemove(organizationId, workspaceId ?? "", member.membershipId);
      }
      setMembers((current) => current.filter((entry) => entry.userId !== member.userId));
      if (member.userId === memberList.currentUserId) {
        router.push(
          scopeType === "organization"
            ? "/org"
            : `/org/${encodeURIComponent(organizationId)}/workspaces`
        );
        router.refresh();
      }
    } finally {
      setUpdatingId(null);
    }
  }

  async function revokeInvitation(invitation: InvitationRead) {
    if (scopeType === "organization") {
      await organizationInvitationsRevoke(organizationId, invitation.id);
    } else {
      await workspaceInvitationsRevoke(organizationId, workspaceId ?? "", invitation.id);
    }
    setInvitations((current) =>
      current.map((entry) =>
        entry.id === invitation.id ? { ...entry, status: "revoked" as const } : entry
      )
    );
  }

  return (
    <div className="space-y-6">
      {canInvite ? (
        <Card>
          <CardHeader>
            <CardTitle>Invite a member</CardTitle>
            <CardDescription>
              Create a secure invitation link to share manually. Email delivery is not enabled yet.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <form className="grid gap-4 md:grid-cols-[minmax(0,1fr)_180px_auto]" onSubmit={createInvitation}>
              <div className="space-y-2">
                <Label htmlFor={`${scopeType}-invite-email`}>Email</Label>
                <Input
                  autoComplete="email"
                  id={`${scopeType}-invite-email`}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="teammate@example.com"
                  required
                  type="email"
                  value={email}
                />
              </div>
              <div className="space-y-2">
                <Label>Role</Label>
                <Select onValueChange={(value) => setRole(value as Role)} value={role}>
                  <SelectTrigger aria-label="Invitation role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {roleOptions.map((option) => (
                      <SelectItem key={option} value={option}>
                        {roleLabel(option)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button className="w-full gap-2 md:w-auto" disabled={submitting} type="submit">
                  {submitting ? <Loader2 className="size-4 animate-spin" /> : <MailPlus className="size-4" />}
                  {submitting ? "Creating" : "Create invite"}
                </Button>
              </div>
            </form>

            {inviteLink ? (
              <AsyncFeedback variant="success">
                <div className="space-y-2">
                  <div className="font-medium">Invitation created</div>
                  <p>Copy this link now. Wardn stores only a secure hash and cannot show it again.</p>
                  <div className="flex gap-2">
                    <Input
                      aria-label="Invitation link"
                      readOnly
                      ref={inviteLinkInput}
                      value={inviteLink}
                    />
                    <Button onClick={copyInvitationLink} type="button" variant="outline">
                      {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                      {copied ? "Copied" : "Copy"}
                    </Button>
                  </div>
                </div>
              </AsyncFeedback>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

      <Card>
        <CardHeader>
          <CardTitle>{scopeName} members</CardTitle>
          <CardDescription>
            {scopeType === "workspace"
              ? "Workspace assignments and inherited organization administration access."
              : "People who can access this organization and their organization-wide role."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {members.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Member</TableHead>
                  <TableHead>Access</TableHead>
                  <TableHead>Role</TableHead>
                  {memberList.canManage ? <TableHead className="w-20 text-right">Actions</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => {
                  const inherited = member.accessSource === "organization" && scopeType === "workspace";
                  const ownerRestricted = member.role === "owner" && !memberList.canManageOwners;
                  const editable = memberList.canManage && Boolean(member.membershipId) && !ownerRestricted;
                  return (
                    <TableRow key={`${member.accessSource}-${member.userId}`}>
                      <TableCell>
                        <div className="font-medium">{member.displayName}</div>
                        <div className="text-xs text-muted-foreground">{member.email}</div>
                      </TableCell>
                      <TableCell>
                        {inherited ? (
                          <Badge variant="outline">Organization {member.organizationRole}</Badge>
                        ) : scopeType === "organization" ? (
                          <Badge variant="secondary">Organization</Badge>
                        ) : member.organizationRole ? (
                          <Badge variant="secondary">
                            Direct + organization {member.organizationRole}
                          </Badge>
                        ) : (
                          <Badge variant="secondary">Direct</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {editable ? (
                          <Select
                            disabled={updatingId === member.membershipId}
                            onValueChange={(value) => updateMember(member, value as Role)}
                            value={member.role}
                          >
                            <SelectTrigger aria-label={`Role for ${member.email}`} className="w-36">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {roleOptions.map((option) => (
                                <SelectItem key={option} value={option}>
                                  {roleLabel(option)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <div className="flex items-center gap-2">
                            <ShieldCheck className="size-4 text-muted-foreground" />
                            {roleLabel(member.role)}
                          </div>
                        )}
                      </TableCell>
                      {memberList.canManage ? (
                        <TableCell className="text-right">
                          {editable ? (
                            <ConfirmActionDialog
                              actionLabel="Remove access"
                              description={`Remove ${member.displayName} from ${scopeName}?`}
                              onConfirm={() => removeMember(member)}
                              title={`Remove ${member.displayName}?`}
                              variant="destructive"
                            >
                              <Button
                                aria-label={`Remove ${member.email}`}
                                disabled={updatingId === member.membershipId}
                                size="icon"
                                type="button"
                                variant="outline"
                              >
                                {updatingId === member.membershipId ? (
                                  <Loader2 className="size-4 animate-spin" />
                                ) : (
                                  <Trash2 className="size-4" />
                                )}
                              </Button>
                            </ConfirmActionDialog>
                          ) : null}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <EmptyState description="Invite someone to collaborate in this scope." icon={Users} title="No members" />
          )}
        </CardContent>
      </Card>

      {canInvite ? (
        <Card>
          <CardHeader>
            <CardTitle>Invitations</CardTitle>
            <CardDescription>Invitation history and pending access.</CardDescription>
          </CardHeader>
          <CardContent>
            {invitations.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead className="w-20 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invitations.map((invitation) => (
                    <TableRow key={invitation.id}>
                      <TableCell className="font-medium">{invitation.email}</TableCell>
                      <TableCell>{roleLabel(invitation.role)}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(invitation.status)}>{roleLabel(invitation.status)}</Badge>
                      </TableCell>
                      <TableCell>{formatUserDateTime(invitation.expiresAt)}</TableCell>
                      <TableCell className="text-right">
                        {invitation.status === "pending" &&
                        (invitation.role !== "owner" || memberList.canManageOwners) ? (
                          <ConfirmActionDialog
                            actionLabel="Revoke invitation"
                            description={`${invitation.email} will no longer be able to use this invitation link.`}
                            onConfirm={() => revokeInvitation(invitation)}
                            title="Revoke invitation?"
                            variant="destructive"
                          >
                            <Button aria-label={`Revoke invitation for ${invitation.email}`} size="icon" type="button" variant="outline">
                              <Trash2 className="size-4" />
                            </Button>
                          </ConfirmActionDialog>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState description="Create an invitation link to add someone." icon={MailPlus} title="No invitations" />
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
