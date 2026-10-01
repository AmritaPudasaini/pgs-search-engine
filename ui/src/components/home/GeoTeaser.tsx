import Link from "next/link";
import { ArrowRight, MapPinned } from "lucide-react";

export function GeoTeaser() {
  return (
    <Link
      href="/map"
      className="group flex w-full max-w-xl items-center gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400">
        <MapPinned className="h-5 w-5" />
      </div>
      <div className="flex-1 text-left">
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
          Explore the Geo Tagging map of Nepal
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          75 districts · 766 local levels · tag and search any location
        </p>
      </div>
      <ArrowRight className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-hover:translate-x-1" />
    </Link>
  );
}
