"use client";

import { Download, FileText, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/atoms/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/atoms/dialog";
import { Input } from "@/components/atoms/input";
import { ApiError, apiRequest } from "@/lib/api/client";
import type { RuntimeLogEntry, RuntimeLogPage } from "@/lib/api/generated/model";

type Props = {
  organizationId: string;
  jobId?: string;
  kind?: "mcp_operation" | "scheduled_task" | "agent_run";
  sourceId?: string;
};

export function RuntimeLogViewer(props: Props) {
  const identity = [props.organizationId, props.kind, props.jobId, props.sourceId].join(":");
  return <RuntimeLogContent key={identity} {...props} />;
}

function RuntimeLogContent({ organizationId, jobId, kind, sourceId }: Props) {
  const [entries, setEntries] = useState<RuntimeLogEntry[]>([]);
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("ALL");
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [page, setPage] = useState<RuntimeLogPage | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let cursor: string | null = null;
    let activeJob: string | null = null;
    let terminalPolls = 0;
    const base = `/api/v1/organizations/${encodeURIComponent(organizationId)}/runtime-logs`;
    const path = sourceId
      ? `${base}/catalog-sources/${encodeURIComponent(sourceId)}`
      : `${base}/${kind}/${encodeURIComponent(jobId ?? "")}`;
    async function load() {
      try {
        const result = await apiRequest<RuntimeLogPage>(
          `${path}?limit=100${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`,
          { signal: controller.signal, cache: "no-store" }
        );
        if (controller.signal.aborted) return;
        if (activeJob && result.jobId !== activeJob) {
          // The source may have started another run while its viewer was open.
          activeJob = result.jobId ?? null;
          cursor = null;
          terminalPolls = 0;
          setEntries([]);
          timer = setTimeout(load, 0);
          return;
        }
        activeJob = result.jobId ?? null;
        cursor = result.nextCursor ?? cursor;
        setEntries((current) => {
          const unique = new Map(current.map((entry) => [entry.id, entry]));
          for (const entry of result.items) unique.set(entry.id, entry);
          return [...unique.values()].slice(-result.maxEntries);
        });
        setPage(result);
        setError("");
        setLoading(false);
        const done = !result.jobId || ["succeeded", "completed", "failed", "canceled", "cancelled", "expired", "blocked", "partially_delivered", "delivery_failed"]
          .includes(result.jobStatus ?? "");
        terminalPolls = done && !result.hasMore ? terminalPolls + 1 : 0;
        if (result.hasMore || terminalPolls < 3) timer = setTimeout(load, result.hasMore ? 0 : 2000);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof ApiError && caught.status === 403
          ? "Organization administrator access is required to view runtime logs."
          : caught instanceof Error ? caught.message : "Runtime logs could not be loaded.");
        setLoading(false);
      }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [organizationId, jobId, kind, sourceId, refresh]);

  const visible = useMemo(() => entries.filter((entry) =>
    (level === "ALL" || entry.level === level)
    && `${entry.message} ${JSON.stringify(entry.fields)}`.toLowerCase().includes(query.toLowerCase())
  ), [entries, level, query]);

  function download() {
    const text = visible.map((entry) => `${entry.timestamp} ${entry.level} ${entry.message}\n${JSON.stringify(entry.fields)}`).join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `wardn-runtime-${page?.jobId ?? "logs"}.log`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <div className="min-w-0 space-y-3" data-runtime-logs>
    <div className="flex flex-wrap items-center gap-2">
      <Input aria-label="Search runtime logs" className="min-w-40 flex-1" placeholder="Search loaded logs" value={query} onChange={(event) => setQuery(event.target.value)} />
      <select aria-label="Log level" className="rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground" value={level} onChange={(event) => setLevel(event.target.value)}>
        {["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((value) => <option key={value}>{value}</option>)}
      </select>
      <Button variant="outline" size="sm" onClick={() => { setEntries([]); setPage(null); setError(""); setLoading(true); setRefresh((value) => value + 1); }}><RefreshCw className="size-4" />Refresh logs</Button>
      <Button variant="outline" size="sm" disabled={!visible.length} onClick={download}><Download className="size-4" />Download</Button>
    </div>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    {loading ? <p role="status" className="text-sm text-muted-foreground">Loading logs…</p> : null}
    {page ? <p className="text-xs text-muted-foreground">
      {visible.length} of {entries.length} loaded entries · {page.jobStatus ?? "No run yet"} · Retained for up to {Math.round(page.retentionSeconds / 86400)} days, latest {page.maxEntries} entries.
      {page.truncated ? " Earlier entries may have been removed." : ""}
      {page.unreadableEntries ? " Some unreadable entries were skipped." : ""}
    </p> : null}
    {!loading && !error && !entries.length ? <p className="text-sm text-muted-foreground">No retained runtime logs. Older runs and runs before log capture was enabled have no captured history.</p> : null}
    {!!entries.length && !visible.length ? <p className="text-sm text-muted-foreground">No logs match these filters.</p> : null}
    <div className="max-h-[55vh] overflow-auto rounded-md border border-border" aria-label="Runtime log entries">
      {visible.map((entry) => <details key={entry.id} className="border-b border-border p-3 text-xs last:border-b-0">
        <summary className="cursor-pointer break-words font-mono whitespace-pre-wrap">
          <time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString()}</time>{" "}
          <span className={entry.level === "ERROR" || entry.level === "CRITICAL" ? "text-destructive" : "text-muted-foreground"}>{entry.level}</span>{" "}{entry.message}
        </summary>
        <pre className="mt-2 overflow-auto rounded bg-muted p-2 whitespace-pre-wrap break-all">{JSON.stringify(entry.fields, null, 2)}</pre>
      </details>)}
    </div>
  </div>;
}

export function RuntimeLogsButton(props: Props) {
  const [open, setOpen] = useState(false);
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><Button variant="outline" size="sm" type="button"><FileText className="size-4" />Runtime logs</Button></DialogTrigger>
    <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
      <DialogHeader><DialogTitle>Runtime logs</DialogTitle><DialogDescription>Live diagnostic events across attempts, with search and download.</DialogDescription></DialogHeader>
      {open ? <RuntimeLogViewer {...props} /> : null}
    </DialogContent>
  </Dialog>;
}
