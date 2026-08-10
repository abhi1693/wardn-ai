import { Search } from "lucide-react";
import type { ComponentProps } from "react";

import { Input } from "@/components/atoms/input";
import { Label } from "@/components/atoms/label";
import { cn } from "@/lib/utils";

type SearchFieldProps = Omit<ComponentProps<typeof Input>, "type"> & {
  label?: string | null;
};

export function SearchField({ className, id, label = "Search", ...props }: SearchFieldProps) {
  return (
    <div className={cn(label ? "space-y-1" : "", className)}>
      {label ? (
        <Label className="text-xs text-muted-foreground" htmlFor={id}>
          {label}
        </Label>
      ) : null}
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          autoComplete="off"
          className="pl-9"
          id={id}
          type="search"
          {...props}
        />
      </div>
    </div>
  );
}
