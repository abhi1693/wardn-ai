"use client";

import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { MCPRegistryServerResponse } from "@/lib/api/generated/model";
import {
  organizationMcpRegistryListServers,
  organizationMcpRegistryListServerVersions,
} from "@/lib/api/generated/organization-mcp-registry/organization-mcp-registry";

import { SERVER_PICKER_PAGE_SIZE, uniqueServerResponses } from "./install-form-domain";

type UseInstallServerPickerOptions = {
  initialNextCursor: string;
  initialServers: MCPRegistryServerResponse[];
  initialVersions: MCPRegistryServerResponse[];
  organizationId: string;
  selectedServer: MCPRegistryServerResponse | null;
  setError: Dispatch<SetStateAction<string>>;
};

export function useInstallServerPicker({
  initialNextCursor,
  initialServers,
  initialVersions,
  organizationId,
  selectedServer,
  setError,
}: UseInstallServerPickerOptions) {
  const [serverQuery, setServerQuery] = useState("");
  const [appliedServerQuery, setAppliedServerQuery] = useState("");
  const [serverResults, setServerResults] = useState(() => uniqueServerResponses(initialServers));
  const [serverCurrentCursor, setServerCurrentCursor] = useState("");
  const [serverNextCursor, setServerNextCursor] = useState(initialNextCursor);
  const [serverPreviousCursors, setServerPreviousCursors] = useState<string[]>([]);
  const [hasSearched, setHasSearched] = useState(initialServers.length > 0);
  const [isSearching, setIsSearching] = useState(false);
  const [serverVersions, setServerVersions] = useState(initialVersions);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const hasInitializedSearch = useRef(false);
  const searchRequestId = useRef(0);
  const selectedServerName = selectedServer?.server.name ?? "";

  useEffect(() => {
    if (!selectedServerName) {
      return;
    }
    let cancelled = false;
    async function loadVersions() {
      setIsLoadingVersions(true);
      try {
        const data = await organizationMcpRegistryListServerVersions(
          organizationId,
          selectedServerName
        );
        if (!cancelled) {
          setServerVersions(data.servers);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingVersions(false);
        }
      }
    }
    void loadVersions();
    return () => {
      cancelled = true;
    };
  }, [organizationId, selectedServerName]);

  const loadServerOptions = useCallback(
    async ({ query, cursor, previous }: { query: string; cursor: string; previous: string[] }) => {
      const requestId = searchRequestId.current + 1;
      searchRequestId.current = requestId;
      setError("");
      setHasSearched(true);
      setIsSearching(true);
      try {
        const data = await organizationMcpRegistryListServers(organizationId, {
          limit: SERVER_PICKER_PAGE_SIZE,
          version: "latest",
          ...(query.trim() ? { search: query.trim() } : {}),
          ...(cursor ? { cursor } : {}),
        });
        if (searchRequestId.current !== requestId) {
          return;
        }
        setServerResults(uniqueServerResponses(data.servers));
        setAppliedServerQuery(query);
        setServerCurrentCursor(cursor);
        setServerNextCursor(data.metadata.nextCursor ?? "");
        setServerPreviousCursors(previous);
      } catch (caught) {
        if (searchRequestId.current === requestId) {
          setError(caught instanceof Error ? caught.message : "Server search failed.");
        }
      } finally {
        if (searchRequestId.current === requestId) {
          setIsSearching(false);
        }
      }
    },
    [organizationId, setError]
  );

  async function loadNextServerPage() {
    if (!serverNextCursor) {
      return;
    }
    await loadServerOptions({
      query: appliedServerQuery,
      cursor: serverNextCursor,
      previous: [...serverPreviousCursors, serverCurrentCursor],
    });
  }

  async function loadPreviousServerPage() {
    if (serverPreviousCursors.length === 0) {
      return;
    }
    const previousCursor = serverPreviousCursors.at(-1) ?? "";
    await loadServerOptions({
      query: appliedServerQuery,
      cursor: previousCursor,
      previous: serverPreviousCursors.slice(0, -1),
    });
  }

  useEffect(() => {
    if (selectedServer) {
      return;
    }
    if (!hasInitializedSearch.current) {
      hasInitializedSearch.current = true;
      return;
    }
    const timeout = window.setTimeout(() => {
      void loadServerOptions({ query: serverQuery, cursor: "", previous: [] });
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [loadServerOptions, serverQuery, selectedServer]);

  return {
    appliedServerQuery,
    hasSearched,
    isLoadingVersions,
    isSearching,
    loadNextServerPage,
    loadPreviousServerPage,
    serverNextCursor,
    serverPreviousCursors,
    serverQuery,
    serverResults,
    serverVersions,
    setServerQuery,
    setIsLoadingVersions,
    setServerVersions,
  };
}
