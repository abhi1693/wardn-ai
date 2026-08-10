"use client";

import { AlertTriangle, ArrowLeft, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { BrandMark } from "@/components/atoms/brand-mark";
import { Button } from "@/components/atoms/button";

type AppShellErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
  scope: "organization" | "workspace";
};

export function AppShellError({ error, reset, scope }: AppShellErrorProps) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  const title = `${scope === "workspace" ? "Workspace" : "Organization"} unavailable`;
  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="flex h-14 items-center border-b border-border bg-card px-6">
        <BrandMark className="size-7" sizes="28px" />
        <span className="ml-2.5 text-sm font-semibold">Wardn AI</span>
      </header>
      <section className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-2xl items-center px-6 py-12">
        <div className="w-full border-l-2 border-destructive pl-6" role="alert">
          <AlertTriangle className="mb-4 size-6 text-destructive" />
          <h1 className="text-2xl font-semibold">{title}</h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
            Wardn could not load this {scope}. Retry the request or return to organization
            selection.
          </p>
          <div className="mt-6 flex items-center gap-3">
            <Button onClick={reset} type="button">
              <RotateCcw className="size-4" />
              Try again
            </Button>
            <Button asChild variant="outline">
              <Link href="/org">
                <ArrowLeft className="size-4" />
                Organizations
              </Link>
            </Button>
          </div>
        </div>
      </section>
    </main>
  );
}
