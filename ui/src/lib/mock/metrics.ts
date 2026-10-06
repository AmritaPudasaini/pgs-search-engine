import type {
  CrawlJobResult,
  Finding,
  FindingSeverity,
  FindingStatus,
  LogEntry,
  LogLevel,
  MetricPoint,
} from "@/lib/types";

let counter = 0;
function nextId(prefix: string) {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
}

export function generateMetricSeries(points = 24): MetricPoint[] {
  const now = Date.now();
  let cpu = 38;
  let ram = 52;
  let qps = 140;
  let latency = 85;

  return Array.from({ length: points }).map((_, i) => {
    cpu = clamp(cpu + (Math.random() - 0.5) * 12, 15, 92);
    ram = clamp(ram + (Math.random() - 0.5) * 8, 30, 88);
    qps = clamp(qps + (Math.random() - 0.5) * 40, 60, 320);
    latency = clamp(latency + (Math.random() - 0.5) * 20, 40, 260);
    const time = new Date(now - (points - i) * 60_000);
    return {
      time: time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      cpu: Math.round(cpu),
      ram: Math.round(ram),
      queriesPerSec: Math.round(qps),
      latencyMs: Math.round(latency),
    };
  });
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

const LOG_SERVICES = ["crawler", "indexer", "api-gateway", "geo-service", "auth", "ranker"];
const LOG_MESSAGES: Record<LogLevel, string[]> = {
  info: [
    "Indexed 1,204 new documents from municipal registry sync",
    "Crawl job completed for district=Kaski in 4.2s",
    "Cache warmed for top 500 queries",
    "Geo-tag layer refreshed for 12 districts",
    "Health check passed for all shards",
  ],
  debug: [
    "Query planner selected inverted-index path",
    "Session token refreshed for analyst@pgs.local",
    "Tile cache hit ratio 0.93 for /map viewport",
  ],
  warn: [
    "Latency spike detected on shard-4 (312ms)",
    "Retrying failed fetch for source docs.pgs.np (attempt 2/3)",
    "Disk usage on node-2 crossed 80%",
    "Rate limit approaching for client 10.12.4.9",
  ],
  error: [
    "Timeout indexing batch #4471, moved to dead-letter queue",
    "Failed to resolve municipality boundary for N_ID=unknown-12",
    "Auth token validation failed for stale session",
    "Connection reset while syncing findings-service",
  ],
};

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function weightedLevel(): LogLevel {
  const r = Math.random();
  if (r < 0.62) return "info";
  if (r < 0.8) return "debug";
  if (r < 0.94) return "warn";
  return "error";
}

export function generateLogEntry(): LogEntry {
  const level = weightedLevel();
  return {
    id: nextId("log"),
    timestamp: new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
    level,
    service: pick(LOG_SERVICES),
    message: pick(LOG_MESSAGES[level]),
  };
}

export function generateInitialLogs(count = 18): LogEntry[] {
  return Array.from({ length: count }).map(() => generateLogEntry());
}

const CRAWL_JOBS = [
  "district-boundary-sync", "municipality-index", "ward-tagging",
  "duplicate-content-scan", "link-health-check", "schema-validation",
  "image-alt-audit", "sitemap-crawl",
];

export function generateCrawlJobs(count = 10): CrawlJobResult[] {
  return Array.from({ length: count }).map((_, i) => {
    const pass = Math.random() > 0.22;
    return {
      id: nextId("job"),
      job: CRAWL_JOBS[i % CRAWL_JOBS.length],
      status: pass ? "pass" : "fail",
      duration: Math.round(400 + Math.random() * 3200),
      timestamp: new Date(Date.now() - i * 5 * 60_000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
    };
  });
}

const FINDING_TEMPLATES: Array<{ title: string; description: string; severity: FindingSeverity; source: string }> = [
  {
    title: "Stale boundary geometry for 3 wards",
    description: "Ward-level polygons in Dhanusha district have not been re-validated since the last local-level boundary update.",
    severity: "medium",
    source: "geo-service",
  },
  {
    title: "Duplicate content detected across 2 mirrors",
    description: "records.pgs.np and docs.pgs.np are serving near-identical content for 47 documents, inflating index size.",
    severity: "low",
    source: "indexer",
  },
  {
    title: "Auth token replay attempt blocked",
    description: "3 requests reused an expired session token from the same IP range within a 10s window.",
    severity: "high",
    source: "auth",
  },
  {
    title: "Crawler exceeded memory budget",
    description: "The municipality-index job briefly exceeded its 512MB budget while processing Province 1 data.",
    severity: "medium",
    source: "crawler",
  },
  {
    title: "Unresolved municipality reference",
    description: "N_ID 'unknown-12' referenced by 4 geo-tags does not match any known local level.",
    severity: "critical",
    source: "geo-service",
  },
  {
    title: "Search ranking regression on place queries",
    description: "Click-through rate for place-type results dropped 9% after the last ranker deployment.",
    severity: "high",
    source: "ranker",
  },
];

export function generateFindings(): Finding[] {
  const statuses: FindingStatus[] = ["open", "investigating", "resolved"];
  return FINDING_TEMPLATES.map((f, i) => ({
    id: nextId("finding"),
    ...f,
    status: statuses[i % statuses.length],
    detectedAt: new Date(Date.now() - (i + 1) * 3_600_000).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
  }));
}
