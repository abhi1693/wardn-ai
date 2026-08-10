"use client";

import type { Column } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/atoms/button";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

type DataTableColumnHeaderProps<TData extends object> = {
  className?: string;
  column: Column<DataTableFeatures, TData, unknown>;
  title: string;
};

export function DataTableColumnHeader<TData extends object>({
  className,
  column,
  title,
}: DataTableColumnHeaderProps<TData>) {
  if (!column.getCanSort()) {
    return <span className={className}>{title}</span>;
  }

  const direction = column.getIsSorted();
  const Icon = direction === "asc" ? ArrowUp : direction === "desc" ? ArrowDown : ChevronsUpDown;

  return (
    <Button
      aria-label={direction ? `${title}, sorted ${direction}ending` : `Sort by ${title}`}
      className={cn("-ml-2 h-8 px-2 text-xs font-medium", className)}
      onClick={() => column.toggleSorting(direction === "asc")}
      size="sm"
      type="button"
      variant="ghost"
    >
      {title}
      <Icon className="size-3.5" />
    </Button>
  );
}
