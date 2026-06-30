import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const port = Number(process.env.WARDN_E2E_BACKEND_PORT ?? 4100);
const now = "2026-06-30T00:00:00.000Z";

const organization = {
  id: "org-1",
  name: "Default Organization",
  slug: "default",
  status: "active",
  currentUserRole: "owner",
  createdAt: now,
  updatedAt: now,
};

const workspace = {
  id: "workspace-1",
  organizationId: organization.id,
  name: "Platform",
  slug: "platform",
  description: "",
  status: "active",
  currentUserRole: "owner",
  createdAt: now,
  updatedAt: now,
};

const secretStore = {
  id: "store-1",
  organizationId: organization.id,
  workspaceId: null,
  name: "k3s wardn",
  provider: "openbao",
  config: {},
  authConfig: {},
  isActive: true,
  createdById: null,
  createdAt: now,
  updatedAt: now,
};

const defaultSource = {
  id: "source-1",
  organizationId: organization.id,
  name: "Wardn Hub",
  provider: "wardn_hub",
  baseUrl: "https://hub.wardnai.dev",
  tenantId: "",
  syncMode: "latest_only",
  lastSuccessAt: null,
  lastSyncedUpdatedSince: null,
  lastError: "",
  isEnabled: true,
  hasAuthToken: true,
  createdAt: now,
  updatedAt: now,
};

let state = initialState();

function initialState(overrides = {}) {
  return {
    requests: [],
    sources: overrides.sources ?? [{ ...defaultSource }],
  };
}

function json(response, status = 200) {
  return {
    status,
    body: JSON.stringify(response),
    headers: { "content-type": "application/json" },
  };
}

function empty(status = 204) {
  return { status, body: "", headers: {} };
}

function normalizeHubUrl(provider, baseUrl) {
  const value = String(baseUrl ?? "").trim().replace(/\/+$/, "");
  if (provider !== "wardn_hub") {
    return value;
  }
  const parsed = new URL(value);
  return `${parsed.protocol}//${parsed.host}`;
}

async function requestBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function record(request, url, body) {
  if (url.pathname.startsWith("/__test")) {
    return;
  }
  state.requests.push({
    method: request.method,
    path: url.pathname,
    body,
  });
}

function sourcePathMatch(pathname) {
  return pathname.match(
    /^\/api\/v1\/organizations\/([^/]+)\/mcp\/catalog\/sources(?:\/([^/]+)(?:\/sync)?)?$/
  );
}

async function handle(request) {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  const body = ["POST", "PATCH", "PUT"].includes(request.method ?? "")
    ? await requestBody(request)
    : undefined;
  record(request, url, body);

  if (request.method === "GET" && url.pathname === "/__test/health") {
    return json({ ok: true });
  }
  if (request.method === "POST" && url.pathname === "/__test/reset") {
    state = initialState(body ?? {});
    return json({ ok: true });
  }
  if (request.method === "GET" && url.pathname === "/__test/requests") {
    return json({ requests: state.requests });
  }

  if (request.method === "POST" && url.pathname === "/api/v1/auth/login") {
    return {
      status: 200,
      body: JSON.stringify({ id: "user-1", email: "owner@example.com", isSuperuser: true }),
      headers: {
        "content-type": "application/json",
        "set-cookie": "wardn_session=test-session; Path=/; HttpOnly; SameSite=Lax",
      },
    };
  }
  if (request.method === "GET" && url.pathname === "/api/v1/auth/me") {
    return json({ id: "user-1", email: "owner@example.com", isSuperuser: true });
  }
  if (request.method === "GET" && url.pathname === "/api/v1/organizations") {
    return json({ organizations: [organization] });
  }
  if (request.method === "GET" && url.pathname === `/api/v1/organizations/${organization.id}`) {
    return json(organization);
  }
  if (
    request.method === "GET" &&
    url.pathname === `/api/v1/organizations/${organization.id}/workspaces`
  ) {
    return json({ workspaces: [workspace] });
  }
  if (
    request.method === "GET" &&
    url.pathname === `/api/v1/organizations/${organization.id}/secrets/stores`
  ) {
    return json({ stores: [secretStore] });
  }

  const match = sourcePathMatch(url.pathname);
  if (!match || match[1] !== organization.id) {
    return json({ detail: "not found" }, 404);
  }

  const sourceId = match[2];
  const isSync = url.pathname.endsWith("/sync");
  if (request.method === "GET" && !sourceId) {
    return json({ sources: state.sources });
  }
  if (request.method === "POST" && !sourceId) {
    const source = {
      ...defaultSource,
      id: randomUUID(),
      name: body.name,
      provider: body.provider,
      baseUrl: normalizeHubUrl(body.provider, body.baseUrl),
      tenantId: body.tenantId ?? "",
      syncMode: body.syncMode ?? "latest_only",
      isEnabled: body.isEnabled ?? true,
      hasAuthToken: Boolean(body.apiToken),
    };
    state.sources.push(source);
    return json(source, 201);
  }

  const index = state.sources.findIndex((source) => source.id === sourceId);
  if (index < 0) {
    return json({ detail: "catalog source not found" }, 404);
  }

  if (request.method === "GET" && sourceId && !isSync) {
    return json(state.sources[index]);
  }
  if (request.method === "PATCH" && sourceId && !isSync) {
    const current = state.sources[index];
    const updated = {
      ...current,
      ...Object.fromEntries(
        Object.entries(body).filter(([key]) => !["apiToken", "apiTokenSecretStoreId"].includes(key))
      ),
      baseUrl:
        body.baseUrl === undefined
          ? current.baseUrl
          : normalizeHubUrl(body.provider ?? current.provider, body.baseUrl),
      hasAuthToken: current.hasAuthToken || Boolean(body.apiToken),
      updatedAt: now,
    };
    state.sources[index] = updated;
    return json(updated);
  }
  if (request.method === "DELETE" && sourceId && !isSync) {
    state.sources.splice(index, 1);
    return empty();
  }
  if (request.method === "POST" && sourceId && isSync) {
    const synced = {
      ...state.sources[index],
      lastSuccessAt: "2026-06-30T02:00:00.000Z",
      lastSyncedUpdatedSince: "2026-06-30T02:00:00.000Z",
      lastError: "",
    };
    state.sources[index] = synced;
    return json({ source: synced, syncedCount: 2 });
  }

  return json({ detail: "method not allowed" }, 405);
}

const server = createServer(async (request, response) => {
  try {
    const result = await handle(request);
    response.writeHead(result.status, result.headers);
    response.end(result.body);
  } catch (error) {
    response.writeHead(500, { "content-type": "application/json" });
    response.end(JSON.stringify({ detail: error instanceof Error ? error.message : "error" }));
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Wardn E2E mock backend listening on ${port}`);
});
