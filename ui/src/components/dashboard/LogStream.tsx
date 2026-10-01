"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import { generateInitialLogs, generateLogEntry } from "@/lib/mock/metrics";
import type { LogEntry, LogLevel } from "@/lib/types";

const LEVEL_COLOR: Record<LogLevel, string> = {
  info: "text-sky-400",
  debug: "text-slate-400",
  warn: "text-amber-400",
  error: "text-rose-400",
};

export function LogStream() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [live, setLive] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Generated after mount so server and client render the same initial (empty) HTML.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLogs(generateInitialLogs());
  }, []);

  useEffect(() => {
    if (!live) return;
    const interval = setInterval(() => {
      setLogs((prev) => [...prev.slice(-99), generateLogEntry()]);
    }, 2200);
    return () => clearInterval(interval);
  }, [live]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [logs]);

  return (
    <Card>
      <CardHeader
        title="Live logs"
        subtitle={`${logs.length} recent entries · crawler, indexer, api-gateway`}
        action={
          <button
            onClick={() => setLive((v) => !v)}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {live ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {live ? "Pause" : "Resume"}
          </button>
        }
      />
      <div
        ref={scrollRef}
        className="h-64 overflow-y-auto bg-slate-950 p-3 font-mono text-xs leading-relaxed"
      >
        {logs.map((log) => (
          <div key={log.id} className="flex gap-2 whitespace-pre text-slate-300">
            <span className="text-slate-500">{log.timestamp}</span>
            <span className={cn("w-12 shrink-0 uppercase", LEVEL_COLOR[log.level])}>{log.level}</span>
            <span className="shrink-0 text-slate-500">[{log.service}]</span>
            <span className="whitespace-normal text-slate-200">{log.message}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
