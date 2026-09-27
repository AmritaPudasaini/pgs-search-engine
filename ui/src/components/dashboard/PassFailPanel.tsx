"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { generateCrawlJobs } from "@/lib/mock/metrics";
import type { CrawlJobResult } from "@/lib/types";

export function PassFailPanel() {
  const [jobs, setJobs] = useState<CrawlJobResult[]>([]);

  useEffect(() => {
    // Generated after mount so server and client render the same initial (empty) HTML.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setJobs(generateCrawlJobs());
  }, []);

  const passCount = jobs.filter((j) => j.status === "pass").length;
  const failCount = jobs.length - passCount;
  const chartData = [
    { name: "Pass", count: passCount },
    { name: "Fail", count: failCount },
  ];

  return (
    <Card>
      <CardHeader
        title="Crawl job results"
        subtitle={`${passCount} passing · ${failCount} failing of last ${jobs.length} runs`}
      />
      <div className="grid gap-4 p-4 sm:grid-cols-[160px_1fr]">
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-slate-100 dark:stroke-slate-800" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" width={28} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.name === "Pass" ? "#16a34a" : "#e11d48"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="max-h-40 space-y-1 overflow-y-auto">
          {jobs.map((job) => (
            <div key={job.id} className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800">
              <span className="truncate text-slate-700 dark:text-slate-300">{job.job}</span>
              <div className="flex shrink-0 items-center gap-2">
                <span className="text-xs text-slate-400">{job.duration}ms</span>
                <Badge tone={job.status === "pass" ? "green" : "red"}>{job.status}</Badge>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
