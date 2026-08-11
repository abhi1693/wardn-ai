"use client";

import { CheckCircle2, Loader2, LogIn, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/atoms/brand-mark";
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
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import type { InvitationAcceptanceRead, InvitationPreview } from "@/lib/api/generated/model";
import { authLogout } from "@/lib/api/generated/auth/auth";
import {
  invitationsAccept,
  invitationsPreview,
  invitationsRegister,
} from "@/lib/api/generated/invitations/invitations";

type InvitationClientProps = {
  token: string;
};

function destination(acceptance: InvitationAcceptanceRead) {
  if (acceptance.workspaceId) {
    return `/org/${encodeURIComponent(acceptance.organizationId)}/workspace/${encodeURIComponent(
      acceptance.workspaceId
    )}/dashboard`;
  }
  return `/org/${encodeURIComponent(acceptance.organizationId)}/dashboard`;
}

function roleLabel(role: string) {
  return role ? role[0].toUpperCase() + role.slice(1) : "Member";
}

export function InvitationClient({ token }: InvitationClientProps) {
  const router = useRouter();
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    invitationsPreview(token)
      .then((result) => {
        if (active) {
          setPreview(result);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Invitation could not be loaded.");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function accept() {
    setSubmitting(true);
    setError(null);
    try {
      const acceptance = await invitationsAccept(token);
      router.replace(destination(acceptance));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invitation could not be accepted.");
      setSubmitting(false);
    }
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const formData = new FormData(event.currentTarget);
    try {
      const acceptance = await invitationsRegister(token, {
        firstName: String(formData.get("firstName") ?? ""),
        lastName: String(formData.get("lastName") ?? ""),
        password: String(formData.get("password") ?? ""),
      });
      router.replace(destination(acceptance));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Account could not be created.");
      setSubmitting(false);
    }
  }

  async function signOut() {
    setSubmitting(true);
    await authLogout();
    window.location.reload();
  }

  function oidcSignIn() {
    const redirectTo = `/invitations/${encodeURIComponent(token)}`;
    window.location.assign(`/api/auth/oidc/login?redirectTo=${encodeURIComponent(redirectTo)}`);
  }

  const signedIn = Boolean(preview?.currentUserEmail);
  const emailMatches =
    preview?.currentUserEmail?.toLocaleLowerCase() === preview?.email.toLocaleLowerCase();
  const loginPath = `/login?reauth=1&next=${encodeURIComponent(
    `/invitations/${encodeURIComponent(token)}`
  )}`;

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-5">
      <Card className="w-full max-w-[520px]">
        <CardHeader className="space-y-6">
          <div className="flex items-center gap-3">
            <BrandMark priority />
            <div className="text-sm font-semibold">Wardn AI</div>
          </div>
          <div>
            <CardTitle className="text-2xl">Join Wardn</CardTitle>
            <CardDescription>Review and accept your membership invitation.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" />
              Loading invitation
            </div>
          ) : preview ? (
            <>
              <div className="rounded-md border bg-muted/20 p-4">
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="mt-0.5 size-5 text-primary" />
                  <div>
                    <div className="font-medium">
                      {preview.scopeType === "workspace"
                        ? preview.workspaceName
                        : preview.organizationName}
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Join as {roleLabel(preview.role)} using {preview.email}.
                    </p>
                    {preview.scopeType === "workspace" ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Organization: {preview.organizationName}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>

              {signedIn && emailMatches ? (
                <Button className="w-full gap-2" disabled={submitting} onClick={accept}>
                  {submitting ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
                  {submitting ? "Joining" : "Accept invitation"}
                </Button>
              ) : signedIn ? (
                <AsyncFeedback variant="error">
                  <div className="space-y-3">
                    <p>
                      You are signed in as {preview.currentUserEmail}. This invitation is for {preview.email}.
                    </p>
                    <Button disabled={submitting} onClick={signOut} type="button" variant="outline">
                      Sign out and continue
                    </Button>
                  </div>
                </AsyncFeedback>
              ) : preview.authMode === "oidc" ? (
                <Button className="w-full gap-2" disabled={submitting} onClick={oidcSignIn}>
                  <LogIn className="size-4" />
                  Sign in with {preview.oidcProviderName}
                </Button>
              ) : (
                <div className="space-y-5">
                  <form className="space-y-4" onSubmit={register}>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="space-y-2">
                        <Label htmlFor="firstName">First name</Label>
                        <Input autoComplete="given-name" id="firstName" name="firstName" />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="lastName">Last name</Label>
                        <Input autoComplete="family-name" id="lastName" name="lastName" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label>Email</Label>
                      <Input disabled value={preview.email} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="password">Create password</Label>
                      <Input
                        autoComplete="new-password"
                        id="password"
                        minLength={8}
                        name="password"
                        required
                        type="password"
                      />
                    </div>
                    <Button className="w-full gap-2" disabled={submitting} type="submit">
                      {submitting ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
                      {submitting ? "Creating account" : "Create account and join"}
                    </Button>
                  </form>
                  <div className="text-center text-sm text-muted-foreground">
                    Already have an account?{" "}
                    <Link className="font-medium text-foreground hover:underline" href={loginPath}>
                      Sign in
                    </Link>
                  </div>
                </div>
              )}
            </>
          ) : null}

          {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}
        </CardContent>
      </Card>
    </main>
  );
}
