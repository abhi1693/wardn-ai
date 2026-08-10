import { BrandMark } from "@/components/atoms/brand-mark";
import { Skeleton } from "@/components/atoms/skeleton";

type AppShellLoadingProps = {
  label: string;
};

export function AppShellLoading({ label }: AppShellLoadingProps) {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <aside
        aria-hidden="true"
        className="fixed left-0 top-0 flex h-screen w-[260px] flex-col border-r border-border bg-sidebar px-3 py-4"
      >
        <div className="mb-5 flex items-center gap-3 px-2">
          <BrandMark className="size-8" sizes="32px" />
          <span className="text-[15px] font-semibold">Wardn AI</span>
        </div>
        <div className="space-y-6 px-2 pt-1">
          {[3, 2, 3].map((count, sectionIndex) => (
            <div className="space-y-2" key={`${sectionIndex}:${count}`}>
              <Skeleton className="h-3 w-20" />
              {Array.from({ length: count }, (_, itemIndex) => (
                <Skeleton className="h-9 w-full" key={`${sectionIndex}:${itemIndex}`} />
              ))}
            </div>
          ))}
        </div>
        <div className="mt-auto border-t border-border pt-3">
          <Skeleton className="h-11 w-full" />
        </div>
      </aside>

      <section className="min-h-screen min-w-0 bg-background pl-[260px]">
        <header
          aria-hidden="true"
          className="fixed right-0 top-0 z-40 flex h-14 w-[calc(100%-260px)] items-center border-b border-border bg-card/90 px-6"
        >
          <Skeleton className="h-5 w-48" />
          <div className="ml-auto flex items-center gap-2">
            <Skeleton className="h-8 w-52" />
            <Skeleton className="size-8" />
            <Skeleton className="size-8" />
          </div>
        </header>

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
      </section>
    </main>
  );
}
