import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const port = Number(process.env.WARDN_E2E_BACKEND_PORT ?? 4100);
const frontendPort = Number(process.env.WARDN_E2E_FRONTEND_PORT ?? 3100);
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
const sessionCookieName = process.env.WARDN_SESSION_COOKIE_NAME ?? "wardn_session";
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

const otherOrganization = {
  ...organization,
  id: "org-2",
  name: "Research Organization",
  slug: "research",
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

const workspaceAgent = {
  id: "agent-1",
  name: "Workspace Assistant",
  enabledSkillIds: [],
  assignedApprovedSkillIds: [],
  assignedWorkspaceSkillIds: [],
  availableSkillCount: 0,
  observedSkillIds: [],
  callsLast7d: 0,
  searchesLast7d: 0,
  fetchesLast7d: 0,
  failuresLast7d: 0,
  recentRunId: null,
  lastUsedAt: null,
};

const hubSkillResult = {
  id: "owner/repo/kubernetes-ops",
  name: "Kubernetes ops",
  description: "Operate Kubernetes clusters with safe inspection and rollout checks.",
  url: "https://hub.wardnai.dev/skills/owner/repo/kubernetes-ops",
  source: "owner/repo",
  sourceOwner: "owner",
  sourceName: "repo",
  isOfficial: false,
  installs: 12,
  auditStatus: "pass",
  auditScore: 99,
  auditRank: "A",
  approved: false,
  workspaceSkillId: null,
  installed: false,
  temporary: true,
  permissions: [],
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

const registrySchema = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";

const googleSearchConsoleServer = {
  $schema: registrySchema,
  _meta: {
    wardnCatalogSource: {
      id: "source-1",
      name: "Wardn Hub",
      provider: "wardn_hub",
      baseUrl: "https://hub.wardnai.dev",
      sourceUrl: "https://hub.wardnai.dev/api/v1/mcp/catalog",
    },
  },
  name: "io.github.acamolese/google-search-console-mcp",
  title: "Google Search Console",
  description: "Inspect Google Search Console properties and performance data.",
  version: "1.0.0",
  icons: [
    {
      src: "https://skills.sh/badge/google-search-console.svg",
    },
  ],
  packages: [
    {
      registryType: "npm",
      identifier: "@acamolese/google-search-console-mcp",
      version: "1.0.0",
      environmentVariables: [
        {
          name: "GSC_CLIENT_ID",
          description:
            "Google OAuth client ID used with GSC_CLIENT_SECRET for stateless authentication.",
          isRequired: false,
          isSecret: false,
        },
      ],
    },
    {
      registryType: "uvx",
      identifier: "google-search-console-mcp",
      version: "1.0.0",
      environmentVariables: [
        {
          name: "GSC_CLIENT_ID",
          description:
            "Google OAuth client ID used with GSC_CLIENT_SECRET for stateless authentication.",
          isRequired: false,
          isSecret: false,
        },
      ],
    },
  ],
  remotes: [],
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

const usageWindow = {
  startDate: "2026-06-01",
  endDate: "2026-06-30",
  timezone: "UTC",
  breakdownLimit: 25,
};

function usageBreakdownRow(id, label, requests, toolCalls) {
  return {
    id,
    label,
    requests,
    inputTokens: requests * 100,
    outputTokens: requests * 40,
    totalTokens: requests * 140,
    costUsd: String((requests * 0.01).toFixed(4)),
    toolCalls,
  };
}

function usageSummaryResponse(scope) {
  const isPersonal = scope === "me";
  const requests = isPersonal ? 3 : 8;
  const toolCalls = isPersonal ? 2 : 5;
  const primaryUser = usageBreakdownRow(
    isPersonal ? "user-1" : "user-all",
    isPersonal ? "owner@example.com" : "All users",
    requests,
    toolCalls
  );
  return {
    window: usageWindow,
    summary: {
      requests,
      succeeded: requests,
      failed: 0,
      running: 0,
      inputTokens: requests * 100,
      outputTokens: requests * 40,
      totalTokens: requests * 140,
      costUsd: String((requests * 0.01).toFixed(4)),
      toolCalls,
    },
    byUser: isPersonal ? [] : [primaryUser],
    byWorkspace: [usageBreakdownRow(workspace.id, workspace.name, requests, toolCalls)],
    byAgent: [
      usageBreakdownRow(
        "agent-1",
        isPersonal ? "My assistant" : "Support agent",
        requests,
        toolCalls
      ),
    ],
    byModel: [usageBreakdownRow("openai:gpt-4.1-mini", "gpt-4.1-mini", requests, toolCalls)],
    daily: [
      {
        date: "2026-06-30",
        requests,
        inputTokens: requests * 100,
        outputTokens: requests * 40,
        totalTokens: requests * 140,
        costUsd: String((requests * 0.01).toFixed(4)),
        toolCalls,
      },
    ],
  };
}

let state = initialState();

function initialState(overrides = {}) {
  return {
    authMode: overrides.authMode ?? "local",
    catalogJobPollsBeforeSuccess: overrides.catalogJobPollsBeforeSuccess ?? 2,
    catalogStatus: overrides.catalogStatus ?? 200,
    jobs: new Map(),
    organizationsStatus: overrides.organizationsStatus ?? 200,
    requests: [],
    installations: overrides.installations ?? [],
    skillLibrary: overrides.skillLibrary ?? [],
    sources: overrides.sources ?? [{ ...defaultSource }],
    tokens: [],
  };
}

function registryServerResponse(server, isLatest = true) {
  return {
    server,
    _meta: {
      "io.modelcontextprotocol.registry/official": {
        status: "active",
        statusChangedAt: now,
        publishedAt: now,
        updatedAt: now,
        isLatest,
      },
    },
  };
}

function operationJob(jobId, status, progressMessage, result = undefined) {
  return {
    attemptCount: 1,
    cleanupAttemptCount: 0,
    cleanupError: "",
    cleanupMaxAttempts: 3,
    cleanupStatus: "not_required",
    createdAt: now,
    errorCode: "",
    errorMessage: "",
    jobId,
    maxAttempts: 3,
    operation: "sync_catalog_source",
    organizationId: organization.id,
    progressCurrent: status === "succeeded" ? 1 : 0,
    progressMessage,
    progressTotal: 1,
    resourceKey: "catalog-source:source-1",
    result,
    status,
    updatedAt: now,
    workspaceId: null,
  };
}

function installOperationJob(jobId, status, progressMessage, result = undefined) {
  return {
    attemptCount: 1,
    cleanupAttemptCount: 0,
    cleanupError: "",
    cleanupMaxAttempts: 3,
    cleanupStatus: "not_required",
    createdAt: now,
    errorCode: "",
    errorMessage: "",
    jobId,
    maxAttempts: 3,
    operation: "install_server",
    organizationId: organization.id,
    progressCurrent: status === "succeeded" ? 1 : 0,
    progressMessage,
    progressTotal: 1,
    resourceKey: `mcp-install:${googleSearchConsoleServer.name}`,
    result,
    status,
    updatedAt: now,
    workspaceId: workspace.id,
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
    query: Object.fromEntries(url.searchParams),
    body,
  });
}

function sourcePathMatch(pathname) {
  return pathname.match(
    /^\/api\/v1\/organizations\/([^/]+)\/mcp\/catalog\/sources(?:\/([^/]+)(?:\/sync)?)?$/
  );
}

function installedServerFromPayload(body) {
  const installTarget = String(body.installTarget ?? "package");
  const [, rawIndex = "0"] = installTarget.split(":");
  const packageIndex = Number.parseInt(rawIndex, 10);
  const packageDefinition =
    googleSearchConsoleServer.packages[
      Number.isFinite(packageIndex) && packageIndex >= 0 ? packageIndex : 0
    ] ?? googleSearchConsoleServer.packages[0];

  return {
    id: "installation-1",
    workspaceId: workspace.id,
    serverName: googleSearchConsoleServer.name,
    configName: body.configName ?? "default",
    installedVersion: body.version ?? googleSearchConsoleServer.version,
    latestVersion: googleSearchConsoleServer.version,
    updateAvailable: false,
    status: "enabled",
    installType: "package",
    installPath: "/tmp/wardn/mcp/google-search-console",
    runtimeConfig: {
      kind: "package",
      package: packageDefinition,
    },
    configuredValues: body.configValues ?? {},
    installError: null,
    installedAt: now,
    updatedAt: now,
    server: googleSearchConsoleServer,
    latestServer: googleSearchConsoleServer,
  };
}

function skillCatalogResponse() {
  const library = state.skillLibrary;
  const assignedSkillIds = library
    .filter((skill) => skill.assignedAgentIds.includes(workspaceAgent.id))
    .map((skill) => skill.skillId);
  const assignedWorkspaceSkillIds = library
    .filter((skill) => skill.assignedAgentIds.includes(workspaceAgent.id))
    .map((skill) => skill.id);
  const hasAssignments = assignedSkillIds.length > 0;
  const recentActivity = hasAssignments
    ? [
        {
          id: "step-1",
          agentRunId: "run-1",
          agentId: workspaceAgent.id,
          agentName: workspaceAgent.name,
          skillId: "abhi1693/wardn-hub/find-skills",
          skillName: "find-skills",
          toolName: "Wardn Hub skill fetch",
          eventType: "fetch",
          status: "completed",
          query: "",
          resultCount: null,
          fetchedSkillId: assignedSkillIds[0],
          auditStatus: "pass",
          source: "owner/repo",
          approved: true,
          temporary: false,
          summary: `Fetched ${assignedSkillIds[0]} with audit pass.`,
          createdAt: now,
        },
      ]
    : [];
  return {
    skills: [
      {
        id: "abhi1693/wardn-hub/find-skills",
        name: "find-skills",
        description: "Search Wardn Hub for audited workflow guidance.",
        url: "https://hub.wardnai.dev/skills/abhi1693/wardn-hub/find-skills",
        source: "abhi1693/wardn-hub",
        sourceUrl: "https://github.com/abhi1693/wardn-hub",
        sourceOwner: "abhi1693",
        sourceName: "wardn-hub",
        auditStatus: "pass",
        auditScore: 100,
        auditRank: "S",
        auditSummary: "No known threat patterns.",
        permissions: [],
        installed: hasAssignments,
        temporary: false,
        enabledAgentIds: hasAssignments ? [workspaceAgent.id] : [],
        enabledAgentNames: hasAssignments ? [workspaceAgent.name] : [],
        healthStatus: "healthy",
        healthDetail: "",
      },
    ],
    library,
    agents: [
      {
        ...workspaceAgent,
        enabledSkillIds: hasAssignments ? ["abhi1693/wardn-hub/find-skills"] : [],
        assignedApprovedSkillIds: assignedSkillIds,
        assignedWorkspaceSkillIds,
        availableSkillCount: assignedSkillIds.length + (hasAssignments ? 1 : 0),
        callsLast7d: recentActivity.length,
        fetchesLast7d: recentActivity.length,
        recentRunId: hasAssignments ? "run-1" : null,
        lastUsedAt: hasAssignments ? now : null,
      },
    ],
    recommendations: [
      {
        id: "kubernetes-ops",
        title: "Kubernetes ops",
        description: "Recommended because this workspace has Kubernetes-style connections.",
        query: "kubernetes ops",
        connectionIds: [],
        connectionNames: [],
        workflowIds: ["kubernetes-ops"],
      },
    ],
    guidedWorkflows: [],
    usageSummary: {
      activeSkills: hasAssignments ? 1 : 0,
      approvedSkills: library.length,
      assignedApprovedSkills: assignedSkillIds.length,
      totalAgents: 1,
      enabledAgents: hasAssignments ? 1 : 0,
      skillEventsLast7d: recentActivity.length,
      skillRunsLast7d: recentActivity.length,
      searchesLast7d: 0,
      fetchesLast7d: recentActivity.length,
      failuresLast7d: 0,
      lastUsedAt: hasAssignments ? now : null,
    },
    recentActivity,
  };
}

function approvedSkillFromBody(body) {
  return {
    id: "library-1",
    skillId: body.skillId,
    name: "Kubernetes ops",
    description: "Operate Kubernetes clusters with safe inspection and rollout checks.",
    url: "https://hub.wardnai.dev/skills/owner/repo/kubernetes-ops",
    source: "owner/repo",
    sourceUrl: "https://github.com/owner/repo",
    sourceOwner: "owner",
    sourceName: "repo",
    auditStatus: "pass",
    auditScore: 99,
    auditRank: "A",
    auditSummary: "No known threat patterns.",
    contentHash: "hash-123",
    status: "active",
    assignedAgentIds: [],
    assignedAgentNames: [],
    lastUsedAt: null,
    usageCountLast7d: 0,
    approvedById: "user-1",
    createdAt: now,
    updatedAt: now,
  };
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
        "set-cookie": `${sessionCookieName}=test-session; Path=/; HttpOnly; SameSite=Lax`,
      },
    };
  }
  if (request.method === "GET" && url.pathname === "/api/v1/auth/config") {
    const oidcEnabled = state.authMode === "oidc";
    return json({
      authMode: state.authMode,
      localLoginEnabled: !oidcEnabled,
      oidcLoginEnabled: oidcEnabled,
      oidcProviderName: oidcEnabled ? "Zitadel" : "",
    });
  }
  if (request.method === "GET" && url.pathname === "/api/v1/auth/oidc/login") {
    return {
      status: 302,
      body: "",
      headers: {
        location: `${frontendOrigin}/favicon.ico?oidc-provider=1&state=test-state`,
        "set-cookie": [
          "wardn_oidc_state=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax",
          "wardn_oidc_state_test=state-cookie; Path=/; HttpOnly; Max-Age=600; SameSite=Lax",
        ],
      },
    };
  }
  if (request.method === "GET" && url.pathname === "/api/v1/auth/oidc/callback") {
    if (!request.headers.cookie?.includes("wardn_oidc_state_test=state-cookie")) {
      return json({ detail: "missing OIDC state" }, 401);
    }
    return {
      status: 302,
      body: "",
      headers: {
        location: `${frontendOrigin}/org`,
        "set-cookie": [
          `${sessionCookieName}=test-session; Path=/; HttpOnly; SameSite=Lax`,
          "wardn_oidc_state_test=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax",
        ],
      },
    };
  }
  if (request.method === "GET" && url.pathname === "/api/v1/auth/me") {
    return json({ id: "user-1", email: "owner@example.com", isSuperuser: true });
  }
  const agentApprovalMatch = url.pathname.match(
    /^\/api\/v1\/organizations\/([^/]+)\/workspaces\/([^/]+)\/agents\/([^/]+)\/tool-approvals\/([^/]+)$/
  );
  if (
    request.method === "POST" &&
    agentApprovalMatch?.[1] === organization.id &&
    agentApprovalMatch[2] === workspace.id
  ) {
    const denied = body.decision === "deny";
    return json({
      approvalId: agentApprovalMatch[4],
      assistantMessage: null,
      error: denied ? "Denied by user." : "",
      result: denied ? "" : "namespace/default",
      status: denied ? "denied" : "completed",
      toolName: "namespace_list",
    });
  }
  if (url.pathname === "/api/v1/auth/api-tokens") {
    if (request.method === "GET") {
      return json({ tokens: state.tokens });
    }
    if (request.method === "POST") {
      const record = {
        createdAt: now,
        description: body.description ?? "",
        expiresAt: body.expiresAt ?? null,
        id: randomUUID(),
        isActive: true,
        lastUsedAt: null,
        name: body.name,
        organizationIds: body.organizationIds ?? [],
        tokenPrefix: "wardn_test",
        updatedAt: now,
        userId: "user-1",
        workspaceIds: body.workspaceIds ?? [],
      };
      state.tokens.push(record);
      return json({ record, token: "wardn_test_secret_token" }, 201);
    }
  }
  if (request.method === "GET" && url.pathname === "/api/v1/organizations") {
    if (state.organizationsStatus !== 200) {
      return json({ detail: "organization request failed" }, state.organizationsStatus);
    }
    return json({ organizations: [organization, otherOrganization] });
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
    url.pathname === `/api/v1/organizations/${otherOrganization.id}/workspaces`
  ) {
    return json({ workspaces: [] });
  }
  if (
    request.method === "GET" &&
    url.pathname === `/api/v1/organizations/${organization.id}/usage/summary`
  ) {
    return json(usageSummaryResponse("organization"));
  }
  if (request.method === "GET" && url.pathname === "/api/v1/me/usage") {
    return json(usageSummaryResponse("me"));
  }
  if (
    request.method === "GET" &&
    url.pathname === `/api/v1/organizations/${organization.id}/secrets/stores`
  ) {
    return json({ stores: [secretStore] });
  }

  if (
    request.method === "GET" &&
    url.pathname === `/api/v1/organizations/${organization.id}/mcp/registry/servers`
  ) {
    const search = url.searchParams.get("search")?.trim().toLowerCase() ?? "";
    const servers =
      search && !googleSearchConsoleServer.title.toLowerCase().includes(search)
        ? []
        : [registryServerResponse(googleSearchConsoleServer)];
    return json({ servers, metadata: { count: servers.length, nextCursor: "" } });
  }

  const serverVersionsMatch = url.pathname.match(
    /^\/api\/v1\/organizations\/([^/]+)\/mcp\/registry\/servers\/([^/]+\/[^/]+)\/versions(?:\/([^/]+))?$/
  );
  if (
    request.method === "GET" &&
    serverVersionsMatch?.[1] === organization.id &&
    decodeURIComponent(serverVersionsMatch[2]) === googleSearchConsoleServer.name
  ) {
    const version = decodeURIComponent(serverVersionsMatch[3] ?? "");
    if (version && version !== "latest" && version !== googleSearchConsoleServer.version) {
      return json({ detail: "server version not found" }, 404);
    }
    const response = registryServerResponse(googleSearchConsoleServer);
    return version ? json(response) : json({ servers: [response], metadata: { count: 1, nextCursor: "" } });
  }

  if (
    request.method === "GET" &&
    url.pathname ===
      `/api/v1/organizations/${organization.id}/workspaces/${workspace.id}/mcp/registry/installed-servers`
  ) {
    return json({
      installations: state.installations,
      metadata: { count: state.installations.length, nextCursor: "" },
      packageRuntimeProvider: "local",
    });
  }

  const installServerMatch = url.pathname.match(
    /^\/api\/v1\/organizations\/([^/]+)\/workspaces\/([^/]+)\/mcp\/registry\/installed-servers\/([^/]+\/[^/]+)$/
  );
  if (
    request.method === "PUT" &&
    installServerMatch?.[1] === organization.id &&
    installServerMatch[2] === workspace.id &&
    decodeURIComponent(installServerMatch[3]) === googleSearchConsoleServer.name
  ) {
    const installation = installedServerFromPayload(body ?? {});
    state.installations = [
      ...state.installations.filter((item) => item.id !== installation.id),
      installation,
    ];
    return json(
      installOperationJob(randomUUID(), "succeeded", "Server installation completed", {
        installation,
      })
    );
  }

  const workspaceSkillsPath = `/api/v1/organizations/${organization.id}/workspaces/${workspace.id}/skills`;
  if (request.method === "GET" && url.pathname === workspaceSkillsPath) {
    return json(skillCatalogResponse());
  }
  if (request.method === "GET" && url.pathname === `${workspaceSkillsPath}/search`) {
    const approved = state.skillLibrary.find((skill) => skill.skillId === hubSkillResult.id);
    return json({
      query: url.searchParams.get("query") ?? "",
      count: 1,
      results: [
        {
          ...hubSkillResult,
          approved: Boolean(approved),
          workspaceSkillId: approved?.id ?? null,
          installed: Boolean(approved),
          temporary: !approved,
        },
      ],
    });
  }
  if (request.method === "POST" && url.pathname === `${workspaceSkillsPath}/library`) {
    const approved = approvedSkillFromBody(body ?? {});
    state.skillLibrary = [
      ...state.skillLibrary.filter((skill) => skill.skillId !== approved.skillId),
      approved,
    ];
    return json(approved, 201);
  }
  const skillLibraryMatch = url.pathname.match(
    /^\/api\/v1\/organizations\/org-1\/workspaces\/workspace-1\/skills\/library\/([^/]+)(?:\/agents)?$/
  );
  if (skillLibraryMatch?.[1]) {
    const skillId = skillLibraryMatch[1];
    const libraryIndex = state.skillLibrary.findIndex((skill) => skill.id === skillId);
    if (libraryIndex < 0) {
      return json({ detail: "workspace skill not found" }, 404);
    }
    if (request.method === "DELETE" && url.pathname.endsWith(`/library/${skillId}`)) {
      state.skillLibrary = state.skillLibrary.filter((skill) => skill.id !== skillId);
      return empty();
    }
    if (request.method === "PATCH" && url.pathname.endsWith(`/library/${skillId}/agents`)) {
      const assignedAgentIds = body.agentIds ?? [];
      const updated = {
        ...state.skillLibrary[libraryIndex],
        assignedAgentIds,
        assignedAgentNames: assignedAgentIds.includes(workspaceAgent.id)
          ? [workspaceAgent.name]
          : [],
        lastUsedAt: assignedAgentIds.includes(workspaceAgent.id) ? now : null,
        usageCountLast7d: assignedAgentIds.includes(workspaceAgent.id) ? 1 : 0,
        updatedAt: now,
      };
      state.skillLibrary[libraryIndex] = updated;
      return json(updated);
    }
  }

  const catalogJobMatch = url.pathname.match(
    /^\/api\/v1\/organizations\/([^/]+)\/mcp\/catalog\/jobs\/([^/]+)$/
  );
  if (request.method === "GET" && catalogJobMatch?.[1] === organization.id) {
    const job = state.jobs.get(catalogJobMatch[2]);
    if (!job) {
      return json({ detail: "operation job not found" }, 404);
    }
    job.pollCount += 1;
    if (job.pollCount >= job.pollsBeforeSuccess) {
      return json(
        operationJob(job.id, "succeeded", "Catalog synchronization completed", job.result)
      );
    }
    return json(operationJob(job.id, "running", "Synchronizing catalog"));
  }

  const match = sourcePathMatch(url.pathname);
  if (!match || match[1] !== organization.id) {
    return json({ detail: "not found" }, 404);
  }

  const sourceId = match[2];
  const isSync = url.pathname.endsWith("/sync");
  if (state.catalogStatus !== 200) {
    return json({ detail: "catalog request failed" }, state.catalogStatus);
  }
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
    const jobId = randomUUID();
    state.jobs.set(jobId, {
      id: jobId,
      pollCount: 0,
      pollsBeforeSuccess: state.catalogJobPollsBeforeSuccess,
      result: { source: synced, syncedCount: 2 },
    });
    return json(operationJob(jobId, "queued", "Catalog synchronization queued"));
  }

  return json({ detail: "method not allowed" }, 405);
}

const server = createServer(async (request, response) => {
  response.setHeader("access-control-allow-origin", frontendOrigin);
  response.setHeader("access-control-allow-credentials", "true");
  response.setHeader("access-control-allow-headers", "content-type");
  response.setHeader("access-control-allow-methods", "DELETE, GET, OPTIONS, PATCH, POST, PUT");
  if (request.method === "OPTIONS") {
    response.writeHead(204);
    response.end();
    return;
  }
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
