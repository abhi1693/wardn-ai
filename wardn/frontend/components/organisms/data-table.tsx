"use client";

import {
  type ColumnDef,
  type ColumnFiltersState,
  flexRender,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
  useTable,
  type ColumnVisibilityState,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, Columns3, Search, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/atoms/button";
import { Checkbox } from "@/components/atoms/checkbox";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/atoms/dropdown-menu";
import { Input } from "@/components/atoms/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import {
  dataTableFeatures,
  type DataTableFeatures,
} from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

export type DataTableFilter = {
  columnId: string;
  label: string;
  options: { label: string; value: string }[];
};

export type DataTableColumnDef<TData extends object> = ColumnDef<
  DataTableFeatures,
  TData,
  unknown
>;

type DataTableProps<TData extends object> = {
  bulkActions?: (selectedRows: TData[]) => ReactNode;
  className?: string;
  columns: DataTableColumnDef<TData>[];
  data: TData[];
  emptyState?: ReactNode;
  filters?: DataTableFilter[];
  getRowId?: (row: TData) => string;
  pageSize?: number;
  search?: { columnId: string; placeholder: string };
  selectable?: boolean;
  urlSyncKey?: string;
};

function queryParams() {
  return typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
}

function queryKey(prefix: string, value: string) {
  return `${prefix}-${value}`;
}

export function DataTable<TData extends object>({
  bulkActions,
  className,
  columns,
  data,
  emptyState = "No records found.",
  filters = [],
  getRowId,
  pageSize = 10,
  search,
  selectable = false,
  urlSyncKey,
}: DataTableProps<TData>) {
  const initialParams = useMemo(() => queryParams(), []);
  const initialSortId = urlSyncKey ? initialParams.get(queryKey(urlSyncKey, "sort")) : null;
  const [sorting, setSorting] = useState<SortingState>(() =>
    initialSortId
      ? [{ desc: initialParams.get(queryKey(urlSyncKey!, "direction")) === "desc", id: initialSortId }]
      : []
  );
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(() => {
    if (!urlSyncKey) {
      return [];
    }
    const initialFilters = filters.flatMap((filter) => {
      const value = initialParams.get(queryKey(urlSyncKey, filter.columnId));
      return value ? [{ id: filter.columnId, value }] : [];
    });
    const searchValue = search ? initialParams.get(queryKey(urlSyncKey, "query")) : null;
    return searchValue && search
      ? [...initialFilters, { id: search.columnId, value: searchValue }]
      : initialFilters;
  });
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>(() => {
    const hidden = urlSyncKey
      ? initialParams.get(queryKey(urlSyncKey, "hidden"))?.split(",").filter(Boolean) ?? []
      : [];
    return Object.fromEntries(hidden.map((id) => [id, false]));
  });
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [pagination, setPagination] = useState<PaginationState>(() => ({
    pageIndex: Math.max(
      0,
      Number(urlSyncKey ? initialParams.get(queryKey(urlSyncKey, "page")) : 1) - 1 || 0
    ),
    pageSize,
  }));

  const tableColumns = useMemo<DataTableColumnDef<TData>[]>(() => {
    const filterColumnIds = new Set(filters.map((filter) => filter.columnId));
    const configuredColumns = columns.map((column) => {
      const columnId = column.id ?? ("accessorKey" in column ? String(column.accessorKey) : "");
      if (search?.columnId === columnId) {
        return { ...column, filterFn: "includesString" } as DataTableColumnDef<TData>;
      }
      if (filterColumnIds.has(columnId)) {
        return { ...column, filterFn: "equalsString" } as DataTableColumnDef<TData>;
      }
      return column;
    });
    if (!selectable) {
      return configuredColumns;
    }
    return [
      {
        id: "select",
        enableHiding: false,
        enableSorting: false,
        header: ({ table }) => (
          <Checkbox
            aria-label="Select all visible rows"
            checked={
              table.getIsAllPageRowsSelected()
                ? true
                : table.getIsSomePageRowsSelected()
                  ? "indeterminate"
                  : false
            }
            onCheckedChange={(checked) => table.toggleAllPageRowsSelected(Boolean(checked))}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            aria-label="Select row"
            checked={row.getIsSelected()}
            onCheckedChange={(checked) => row.toggleSelected(Boolean(checked))}
          />
        ),
      },
      ...configuredColumns,
    ];
  }, [columns, filters, search?.columnId, selectable]);

  const table = useTable({
    features: dataTableFeatures,
    columns: tableColumns,
    data,
    enableRowSelection: selectable,
    getRowId,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    state: { columnFilters, columnVisibility, pagination, rowSelection, sorting },
  });

  useEffect(() => {
    if (!urlSyncKey) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const setParam = (name: string, value: string | undefined) => {
      const key = queryKey(urlSyncKey, name);
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    };
    const activeSort = sorting[0];
    setParam("sort", activeSort?.id);
    setParam("direction", activeSort ? (activeSort.desc ? "desc" : "asc") : undefined);
    setParam("page", pagination.pageIndex > 0 ? String(pagination.pageIndex + 1) : undefined);
    setParam(
      "hidden",
      Object.entries(columnVisibility)
        .filter(([, visible]) => !visible)
        .map(([id]) => id)
        .join(",") || undefined
    );
    setParam(
      "query",
      search ? String(table.getColumn(search.columnId)?.getFilterValue() ?? "") : undefined
    );
    for (const filter of filters) {
      setParam(filter.columnId, String(table.getColumn(filter.columnId)?.getFilterValue() ?? ""));
    }
    const nextUrl = `${window.location.pathname}${params.size ? `?${params}` : ""}${window.location.hash}`;
    window.history.replaceState(window.history.state, "", nextUrl);
  }, [columnFilters, columnVisibility, filters, pagination.pageIndex, search, sorting, table, urlSyncKey]);

  const selectedRows = table.getSelectedRowModel().rows.map((row) => row.original);
  const canHideColumns = table.getAllColumns().filter((column) => column.getCanHide());
  const hasActiveFilters = columnFilters.length > 0;

  function resetFilters() {
    table.resetColumnFilters();
    table.setPageIndex(0);
  }

  return (
    <div className={cn("space-y-3", className)} data-slot="data-table">
      <div className="flex min-h-10 flex-wrap items-center gap-2">
        {search ? (
          <div className="relative w-[320px] max-w-full">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label={search.placeholder}
              className="pl-9"
              onChange={(event) => {
                table.getColumn(search.columnId)?.setFilterValue(event.target.value);
                table.setPageIndex(0);
              }}
              placeholder={search.placeholder}
              value={String(table.getColumn(search.columnId)?.getFilterValue() ?? "")}
            />
          </div>
        ) : null}
        {filters.map((filter) => (
          <Select
            key={filter.columnId}
            onValueChange={(value) => {
              table.getColumn(filter.columnId)?.setFilterValue(value === "all" ? undefined : value);
              table.setPageIndex(0);
            }}
            value={String(table.getColumn(filter.columnId)?.getFilterValue() ?? "all")}
          >
            <SelectTrigger aria-label={filter.label} className="w-[180px]">
              <SelectValue placeholder={filter.label} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All {filter.label.toLowerCase()}</SelectItem>
              {filter.options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ))}
        {hasActiveFilters ? (
          <Button onClick={resetFilters} size="sm" type="button" variant="ghost">
            <X className="size-4" />
            Clear
          </Button>
        ) : null}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button className="ml-auto" size="sm" type="button" variant="outline">
              <Columns3 className="size-4" />
              Columns
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>Visible columns</DropdownMenuLabel>
            {canHideColumns.map((column) => (
              <DropdownMenuCheckboxItem
                checked={column.getIsVisible()}
                key={column.id}
                onCheckedChange={(checked) => column.toggleVisibility(Boolean(checked))}
              >
                {column.id}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {selectedRows.length > 0 && bulkActions ? (
        <div className="flex min-h-11 items-center justify-between gap-3 rounded-md border border-primary/30 bg-primary/5 px-3">
          <span className="text-sm font-medium">{selectedRows.length} selected</span>
          <div className="flex items-center gap-2">{bulkActions(selectedRows)}</div>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-md border border-border bg-card">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    className={cn(
                      header.column.id === "select" && "sticky left-0 z-10 w-10 bg-muted",
                      header.column.id === "actions" &&
                        "sticky right-0 z-10 w-40 min-w-40 bg-muted text-right shadow-[-8px_0_12px_-12px_var(--foreground)]"
                    )}
                    key={header.id}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <TableRow data-state={row.getIsSelected() ? "selected" : undefined} key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      className={cn(
                        cell.column.id === "select" && "sticky left-0 z-[5] w-10 bg-card",
                        cell.column.id === "actions" &&
                          "sticky right-0 z-[5] w-40 min-w-40 bg-card shadow-[-8px_0_12px_-12px_var(--foreground)]"
                      )}
                      key={cell.id}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell className="h-40 text-center text-muted-foreground" colSpan={table.getVisibleLeafColumns().length}>
                  {emptyState}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex min-h-10 items-center justify-between gap-3 text-sm">
        <span className="text-muted-foreground">
          {table.getFilteredRowModel().rows.length.toLocaleString("en-US")} records
        </span>
        <div className="flex items-center gap-2">
          <span className="min-w-24 text-center text-muted-foreground">
            Page {table.state.pagination.pageIndex + 1} of {Math.max(table.getPageCount(), 1)}
          </span>
          <Button
            aria-label="Previous page"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
            size="icon"
            type="button"
            variant="outline"
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            aria-label="Next page"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
            size="icon"
            type="button"
            variant="outline"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
