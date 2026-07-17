"use client";

import { apiUrl } from "@/lib/api/client";

import type { FormEvent } from "react";
import { LoaderCircle, LogIn } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { AsyncFeedback } from "@/components/ui/async-feedback";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BrandMark } from "@/app/components/brand-mark";
import { authConfig, authLogin } from "@/lib/api/generated/auth/auth";

type AuthConfig = {
  authMode: "local" | "oidc";
  localLoginEnabled: boolean;
  oidcLoginEnabled: boolean;
  oidcProviderName: string;
};

function requestedDestination() {
  if (typeof window === "undefined") {
    return "/org";
  }
  const value = new URLSearchParams(window.location.search).get("next") ?? "";
  return value.startsWith("/") && !value.startsWith("//") ? value : "/org";
}

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return new URLSearchParams(window.location.search).get("error") === "oidc"
      ? "External sign in could not be completed."
      : "";
  });
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [isConfigLoading, setIsConfigLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    async function loadConfig() {
      try {
        const payload = (await authConfig()) as AuthConfig;
        if (active) {
          const oidcReturnedError =
            new URLSearchParams(window.location.search).get("error") === "oidc";
          setConfig(payload);
          if (payload.authMode === "oidc" && payload.oidcLoginEnabled && !oidcReturnedError) {
            setIsSubmitting(true);
            window.location.assign(
              apiUrl(
                `/api/v1/auth/oidc/login?redirectTo=${encodeURIComponent(requestedDestination())}`
              )
            );
          }
        }
      } catch {
        if (active) {
          setError("Sign in is currently unavailable.");
        }
      } finally {
        if (active) {
          setIsConfigLoading(false);
        }
      }
    }

    void loadConfig();
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    try {
      await authLogin({
          email: String(formData.get("email") ?? ""),
          password: String(formData.get("password") ?? ""),
      });
    } catch {
      setIsSubmitting(false);
      setError("The email or password is incorrect.");
      return;
    }

    router.replace(requestedDestination());
    router.refresh();
  }

  function handleOidcSignIn() {
    setError("");
    setIsSubmitting(true);
    window.location.assign(
      apiUrl(
        `/api/v1/auth/oidc/login?redirectTo=${encodeURIComponent(requestedDestination())}`
      )
    );
  }

  const showOidc = config?.authMode === "oidc";
  const showLocal = config?.authMode === "local";

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-5">
      <Card className="w-full max-w-[420px]">
        <CardHeader className="space-y-6">
          <div className="flex items-center gap-3">
            <BrandMark priority />
            <div className="text-sm font-semibold">Wardn AI</div>
          </div>
          <div>
            <CardTitle className="text-2xl">Sign in</CardTitle>
            <CardDescription>Access your organization workspace.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isConfigLoading || !config ? (
            <div className="grid gap-4">
              {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

              <Button className="w-full gap-2" disabled type="button">
                <LoaderCircle className="size-4 animate-spin" />
                Checking sign-in
              </Button>
            </div>
          ) : showOidc ? (
            <div className="grid gap-4">
              {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

              <Button
                className="w-full gap-2"
                disabled={isConfigLoading || isSubmitting || !config?.oidcLoginEnabled}
                onClick={handleOidcSignIn}
                type="button"
              >
                <LogIn className="size-4" />
                {isSubmitting ? "Redirecting" : `Sign in with ${config.oidcProviderName}`}
              </Button>
            </div>
          ) : showLocal ? (
            <form className="grid gap-4" method="post" onSubmit={handleSubmit}>
              <div className="grid gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  autoComplete="email"
                  disabled={isConfigLoading}
                  id="email"
                  name="email"
                  placeholder="admin@example.com"
                  required
                  type="email"
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  autoComplete="current-password"
                  disabled={isConfigLoading}
                  id="password"
                  name="password"
                  placeholder="Enter password"
                  required
                  type="password"
                />
              </div>

              {error ? <AsyncFeedback variant="error">{error}</AsyncFeedback> : null}

              <Button
                className="w-full"
                disabled={isConfigLoading || isSubmitting || config?.localLoginEnabled === false}
                type="submit"
              >
                {isSubmitting ? "Signing in" : "Sign in"}
              </Button>
            </form>
          ) : (
            <AsyncFeedback variant="error">Sign in is currently unavailable.</AsyncFeedback>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
