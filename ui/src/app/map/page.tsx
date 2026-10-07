import { Suspense } from "react";
import { TopNav } from "@/components/layout/TopNav";
import { GeoExplorer } from "@/components/map/GeoExplorer";

export default function MapPage() {
  return (
    <div className="flex h-screen flex-col bg-white dark:bg-slate-950">
      <div className="shrink-0 border-b border-slate-200 dark:border-slate-800">
        <TopNav />
      </div>
      <div className="min-h-0 flex-1">
        {/* GeoExplorer reads ?focus= with useSearchParams, which needs a
            Suspense boundary if this page is ever statically rendered. */}
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center text-sm text-slate-500">Loading map…</div>
          }
        >
          <GeoExplorer />
        </Suspense>
      </div>
    </div>
  );
}
