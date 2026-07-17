"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { BrandMark } from "@/app/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export default function ApplicationError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-5">
      <Card
        aria-atomic="true"
        aria-labelledby="application-error-title"
        aria-live="assertive"
        className="w-full max-w-lg"
        role="alert"
      >
        <CardHeader>
          <div className="mb-4 flex items-center gap-3">
            <BrandMark priority />
            <span className="text-sm font-semibold">Wardn AI</span>
          </div>
          <h1
            className="flex items-center gap-2 text-xl font-semibold"
            id="application-error-title"
          >
            <AlertTriangle className="size-5 text-destructive" />
            This page could not be loaded
          </h1>
          <CardDescription>
            The Wardn API may be temporarily unavailable. Your data has not been replaced or
            deleted.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button onClick={reset} type="button">
            <RefreshCw className="size-4" />
            Try again
          </Button>
          <Button asChild variant="outline">
            <Link href="/org">Organizations</Link>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
