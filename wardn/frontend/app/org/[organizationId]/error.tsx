"use client";

import { AppShellError } from "@/components/templates/app-shell-error";

export default function OrganizationError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry?: () => void;
}) {
  return (
    <AppShellError
      embedded
      error={error}
      reset={() => {
        if (unstable_retry) {
          unstable_retry();
          return;
        }
        window.location.reload();
      }}
      scope="organization"
    />
  );
}
