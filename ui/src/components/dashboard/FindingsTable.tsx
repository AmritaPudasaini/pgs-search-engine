"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { generateFindings } from "@/lib/mock/metrics";
import type { Finding, FindingSeverity } from "@/lib/types";

const SEVERITY_TONE: Record<FindingSeverity, "red" | "yellow" | "blue" | "neutral"> = {
  critical: "red",
  high: "yellow",
  medium: "blue",
  low: "neutral",
};

const SEVERITIES: Array<FindingSeverity | "all"> = ["all", "critical", "high", "medium", "low"];

export function FindingsTable() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [filter, setFilter] = useState<FindingSeverity | "all">("all");

  useEffect(() => {
    // Generated after mount so server and client render the same initial (empty) HTML.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFindings(generateFindings());
  }, []);

  const visible = useMemo(
    () => (filter === "all" ? findings : findings.filter((f) => f.severity === filter)),
    [findings, filter]
  );

  return (
    <Card>
      <CardHeader
        title="Findings"
        subtitle={`${findings.filter((f) => f.status !== "resolved").length} open issues across the index`}
        action={
          <div className="flex items-center gap-1">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                onClick={() => setFilter(s)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-medium capitalize",
                  filter === s
                    ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                )}
              >
                {s}
              </button>
            ))}
          </div>
        }
      />
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {visible.map((finding) => (
          <div key={finding.id} className="flex items-start gap-3 p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{finding.title}</p>
                <Badge tone={SEVERITY_TONE[finding.severity]}>{finding.severity}</Badge>
                <Badge tone={finding.status === "resolved" ? "green" : "neutral"}>{finding.status}</Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{finding.description}</p>
              <p className="mt-1 text-xs text-slate-400">
                {finding.source} · detected {finding.detectedAt}
              </p>
            </div>
          </div>
        ))}
        {visible.length === 0 && (
          <p className="p-4 text-sm text-slate-400">No findings at this severity.</p>
        )}
      </div>
    </Card>
  );
}
