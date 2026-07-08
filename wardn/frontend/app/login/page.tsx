"use client";

import type { FormEvent } from "react";
import { LoaderCircle, LogIn } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
import { BrandMark } from "@/app/components/brand-mark";

type AuthConfig = {
  authMode: "local" | "oidc";
  localLoginEnabled: boolean;
  oidcLoginEnabled: boolean;
  oidcProviderName: string;
};

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
        const response = await fetch("/api/auth/config", { cache: "no-store" });
        if (!response.ok) {
          throw new Error("auth config unavailable");
        }
        const payload = (await response.json()) as AuthConfig;
        if (active) {
          const oidcReturnedError =
            new URLSearchParams(window.location.search).get("error") === "oidc";
          setConfig(payload);
          if (payload.authMode === "oidc" && payload.oidcLoginEnabled && !oidcReturnedError) {
            setIsSubmitting(true);
            window.location.assign("/api/auth/oidc/login?redirectTo=/org");
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
    let response: Response;
    try {
      response = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          email: String(formData.get("email") ?? ""),
          password: String(formData.get("password") ?? ""),
        }),
      });
    } catch {
      setIsSubmitting(false);
      setError("Sign in is currently unavailable.");
      return;
    }

    if (response.status >= 500) {
      setIsSubmitting(false);
      setError("Sign in is currently unavailable.");
      return;
    }

    if (!response.ok) {
      setIsSubmitting(false);
      setError("The email or password is incorrect.");
      return;
    }

    router.replace("/org");
    router.refresh();
  }

  function handleOidcSignIn() {
    setError("");
    setIsSubmitting(true);
    window.location.assign("/api/auth/oidc/login?redirectTo=/org");
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
              {error ? <p className="text-sm text-destructive">{error}</p> : null}

              <Button className="w-full gap-2" disabled type="button">
                <LoaderCircle className="size-4 animate-spin" />
                Checking sign-in
              </Button>
            </div>
          ) : showOidc ? (
            <div className="grid gap-4">
              {error ? <p className="text-sm text-destructive">{error}</p> : null}

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

              {error ? <p className="text-sm text-destructive">{error}</p> : null}

              <Button
                className="w-full"
                disabled={isConfigLoading || isSubmitting || config?.localLoginEnabled === false}
                type="submit"
              >
                {isSubmitting ? "Signing in" : "Sign in"}
              </Button>
            </form>
          ) : (
            <p className="text-sm text-destructive">Sign in is currently unavailable.</p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
