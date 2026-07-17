export default function ApplicationLoading() {
  return (
    <main aria-busy="true" aria-label="Loading page" className="min-h-screen bg-background">
      <div aria-live="polite" className="sr-only" role="status">
        Loading page
      </div>
      <div className="h-16 border-b border-border bg-card" />
      <div className="mx-auto grid w-full max-w-[1440px] gap-5 px-8 py-7 max-md:px-4">
        <div className="h-4 w-32 animate-pulse rounded bg-muted" />
        <div className="h-8 w-64 animate-pulse rounded bg-muted" />
        <div className="grid gap-4 md:grid-cols-3">
          <div className="h-32 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-32 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-32 animate-pulse rounded-xl border border-border bg-card" />
        </div>
        <div className="h-80 animate-pulse rounded-xl border border-border bg-card" />
      </div>
    </main>
  );
}
