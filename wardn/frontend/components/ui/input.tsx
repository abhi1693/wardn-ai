import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-9 w-full rounded-[var(--radius)] border border-input bg-card px-3 py-1 text-sm transition-colors outline-none ring-offset-background placeholder:text-muted-foreground file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 focus-visible:border-ring focus-visible:ring-ring/15 focus-visible:ring-[3px]",
        className
      )}
      {...props}
    />
  );
}

export { Input };
