import { Skeleton } from "@/components/atoms/skeleton";

type AppShellLoadingProps = {
  label: string;
};

export function AppShellLoading({ label }: AppShellLoadingProps) {
  return (
    <div
      aria-busy="true"
      aria-label={label}
      className="mx-auto min-h-screen w-full max-w-[1360px] px-6 pb-8 pt-20"
      data-testid="route-loading"
      role="status"
    >
      <span className="sr-only">{label}</span>
      <div className="space-y-6">
        <div className="flex items-end justify-between gap-6">
          <div className="space-y-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-8 w-64" />
          </div>
          <Skeleton className="h-9 w-32" />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
        <Skeleton className="h-80 w-full" />
      </div>
    </div>
  );
}
