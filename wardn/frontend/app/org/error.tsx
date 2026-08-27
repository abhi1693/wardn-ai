"use client";

import { AppShellError } from "@/components/templates/app-shell-error";

export default function OrganizationLayoutError({
  error,
}: {
  error: Error & { digest?: string };
}) {
  return (
    <AppShellError
      error={error}
      reset={() => window.location.reload()}
      scope="organization"
    />
  );
}
