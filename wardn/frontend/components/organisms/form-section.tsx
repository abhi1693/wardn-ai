import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type FormSectionProps = {
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  description?: ReactNode;
  title: ReactNode;
};

export function FormSection({
  actions,
  children,
  className,
  description,
  title,
}: FormSectionProps) {
  return (
    <section className={cn("border-b border-border py-5 first:pt-0 last:border-b-0", className)}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {description ? (
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
