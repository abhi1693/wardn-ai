import Image from "next/image";

import { cn } from "@/lib/utils";

type BrandMarkProps = {
  className?: string;
  imageClassName?: string;
  priority?: boolean;
  sizes?: string;
};

export function BrandMark({
  className,
  imageClassName,
  priority = false,
  sizes = "36px",
}: BrandMarkProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative flex size-9 shrink-0 overflow-hidden rounded-md border border-border bg-card shadow-[var(--shadow-card)]",
        className
      )}
    >
      <Image
        alt=""
        className={cn("object-cover", imageClassName)}
        fill
        priority={priority}
        sizes={sizes}
        src="/brand.png"
      />
    </span>
  );
}
