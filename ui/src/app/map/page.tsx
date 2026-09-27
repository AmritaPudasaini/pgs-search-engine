import { TopNav } from "@/components/layout/TopNav";
import { GeoExplorer } from "@/components/map/GeoExplorer";

export default async function MapPage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string }>;
}) {
  const { focus } = await searchParams;

  return (
    <div className="flex h-screen flex-col bg-white dark:bg-slate-950">
      <div className="shrink-0 border-b border-slate-200 dark:border-slate-800">
        <TopNav />
      </div>
      <div className="min-h-0 flex-1">
        <GeoExplorer initialFocus={focus} />
      </div>
    </div>
  );
}
