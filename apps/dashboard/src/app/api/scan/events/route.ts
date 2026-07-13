import { NextRequest, NextResponse } from "next/server";

// ── Scan Events Proxy ────────────────────────────────────────────
// Proxies GET /api/scan/events?scan_id=xxx to sandbox-svc
// GET /scan/{scan_id}/events. Returns the structured event buffer
// emitted by the pipeline for real-time progress display.

const SANDBOX_URL = process.env.SANDBOX_SVC_URL || "http://localhost:8080";

export async function GET(req: NextRequest) {
  const scanId = req.nextUrl.searchParams.get("scan_id");
  if (!scanId) {
    return NextResponse.json({ error: "scan_id required" }, { status: 400 });
  }

  try {
    const res = await fetch(`${SANDBOX_URL}/scan/${encodeURIComponent(scanId)}/events`, {
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) {
      if (res.status === 404) return NextResponse.json([]);
      return NextResponse.json({ error: "Failed to fetch events" }, { status: 502 });
    }
    const events = await res.json();
    return NextResponse.json(events);
  } catch {
    return NextResponse.json([]);
  }
}
