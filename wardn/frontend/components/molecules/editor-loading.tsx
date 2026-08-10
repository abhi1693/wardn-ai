type EditorLoadingProps = {
  label?: string;
};

export function EditorLoading({ label = "Loading editor" }: EditorLoadingProps) {
  return (
    <div aria-label={label} className="space-y-6 py-6" role="status">
      <div className="h-24 animate-pulse rounded-md border border-border bg-muted/45" />
      <div className="grid min-h-[420px] grid-cols-[minmax(0,1fr)_320px] gap-6">
        <div className="space-y-4 rounded-md border border-border p-5">
          <div className="h-5 w-40 animate-pulse rounded-sm bg-muted" />
          <div className="h-10 animate-pulse rounded-md bg-muted/70" />
          <div className="h-10 animate-pulse rounded-md bg-muted/70" />
          <div className="h-28 animate-pulse rounded-md bg-muted/70" />
        </div>
        <div className="space-y-4 rounded-md border border-border p-5">
          <div className="h-5 w-32 animate-pulse rounded-sm bg-muted" />
          <div className="h-20 animate-pulse rounded-md bg-muted/70" />
          <div className="h-20 animate-pulse rounded-md bg-muted/70" />
        </div>
      </div>
    </div>
  );
}
