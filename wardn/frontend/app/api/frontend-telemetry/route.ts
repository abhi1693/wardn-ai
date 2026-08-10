import { NextResponse } from "next/server";

type FrontendMetricPayload = {
  detail?: Record<string, boolean | number | string>;
  kind?: string;
  name?: string;
  path?: string;
  recordedAt?: string;
  value?: number;
};

const metricKinds = new Set(["api", "navigation", "web-vital"]);
const maximumPayloadBytes = 4_096;

export async function POST(request: Request) {
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > maximumPayloadBytes) {
    return NextResponse.json({ detail: "Frontend metric is too large." }, { status: 413 });
  }
  const payload = (() => {
    try {
      return JSON.parse(body) as FrontendMetricPayload;
    } catch {
      return null;
    }
  })();
  if (
    !payload ||
    !metricKinds.has(payload.kind ?? "") ||
    !payload.name ||
    payload.name.length > 80 ||
    (payload.path?.length ?? 0) > 300 ||
    typeof payload.value !== "number" ||
    !Number.isFinite(payload.value) ||
    payload.value < 0
  ) {
    return NextResponse.json({ detail: "Invalid frontend metric." }, { status: 400 });
  }

  console.info(
    JSON.stringify({
      event: "wardn.frontend.metric",
      ...payload,
      userAgent: request.headers.get("user-agent")?.slice(0, 160) ?? "",
    })
  );
  return new NextResponse(null, { status: 204 });
}
