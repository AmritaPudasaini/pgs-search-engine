"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardHeader } from "@/components/ui/Card";
import { generateMetricSeries } from "@/lib/mock/metrics";
import type { MetricPoint } from "@/lib/types";

export function SystemChart() {
  const [data, setData] = useState<MetricPoint[]>([]);

  useEffect(() => {
    // Generated after mount so server and client render the same initial (empty) HTML.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setData(generateMetricSeries());
    const interval = setInterval(() => {
      setData((prev) => {
        const [, ...rest] = prev;
        const last = prev[prev.length - 1];
        const cpu = clamp(last.cpu + (Math.random() - 0.5) * 12, 15, 92);
        const ram = clamp(last.ram + (Math.random() - 0.5) * 8, 30, 88);
        const qps = clamp(last.queriesPerSec + (Math.random() - 0.5) * 40, 60, 320);
        const latencyMs = clamp(last.latencyMs + (Math.random() - 0.5) * 20, 40, 260);
        return [
          ...rest,
          {
            time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            cpu: Math.round(cpu),
            ram: Math.round(ram),
            queriesPerSec: Math.round(qps),
            latencyMs: Math.round(latencyMs),
          },
        ];
      });
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Card>
      <CardHeader title="System load" subtitle="CPU and RAM utilization, live" />
      <div className="h-64 p-4">
        {data.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="cpuFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="ramFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#16a34a" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#16a34a" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" className="stroke-slate-100 dark:stroke-slate-800" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" unit="%" width={40} />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
                formatter={(value, name) => [`${value}%`, name]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="cpu" name="CPU" stroke="#2563eb" fill="url(#cpuFill)" strokeWidth={2} />
              <Area type="monotone" dataKey="ram" name="RAM" stroke="#16a34a" fill="url(#ramFill)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}
