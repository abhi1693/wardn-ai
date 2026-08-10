import { Slot } from "@radix-ui/react-slot";
import type { ComponentPropsWithoutRef } from "react";

type DeferredRenderProps = ComponentPropsWithoutRef<"div"> & {
  asChild?: boolean;
  estimatedHeight?: number;
};

export function DeferredRender({
  asChild = false,
  estimatedHeight = 80,
  style,
  ...props
}: DeferredRenderProps) {
  const Component = asChild ? Slot : "div";
  return (
    <Component
      data-deferred-render=""
      style={{
        containIntrinsicSize: `auto ${estimatedHeight}px`,
        contentVisibility: "auto",
        ...style,
      }}
      {...props}
    />
  );
}
