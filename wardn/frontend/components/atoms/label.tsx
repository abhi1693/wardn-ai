import * as React from "react";

import { cn } from "@/lib/utils";

function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      data-slot="label"
      className={cn(
        "text-xs leading-4 font-medium tracking-[0.01em] text-foreground",
        className
      )}
      {...props}
    />
  );
}

export { Label };
