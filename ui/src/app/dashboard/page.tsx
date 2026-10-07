import { Activity, Cpu, Gauge, MemoryStick } from "lucide-react";
import { StatCard } from "@/components/dashboard/StatCard";
import { SystemChart } from "@/components/dashboard/SystemChart";
import { PassFailPanel } from "@/components/dashboard/PassFailPanel";
import { LogStream } from "@/components/dashboard/LogStream";
import { FindingsTable } from "@/components/dashboard/FindingsTable";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="CPU usage" value={42} unit="%" delta={3} icon={Cpu} tone="blue" />
        <StatCard label="RAM usage" value={58} unit="%" delta={-2} icon={MemoryStick} tone="emerald" />
        <StatCard label="Queries / sec" value={186} icon={Activity} tone="amber" delta={12} />
        <StatCard label="Avg latency" value={94} unit="ms" icon={Gauge} tone="rose" delta={-5} />
      </div>

      <SystemChart />

      <div className="grid gap-6 lg:grid-cols-2">
        <PassFailPanel />
        <LogStream />
      </div>

      <FindingsTable />
    </div>
  );
}
