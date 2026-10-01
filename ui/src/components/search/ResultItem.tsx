import Link from "next/link";
import { MapPinned } from "lucide-react";
import type { SearchResult } from "@/lib/types";

export function ResultItem({ result }: { result: SearchResult }) {
  if (result.category === "place") {
    return (
      <Link
        href={result.url}
        className="mb-6 flex gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 hover:border-blue-200 dark:border-blue-500/20 dark:bg-blue-500/5"
      >
        <MapPinned className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div>
          <p className="text-xs text-emerald-700 dark:text-emerald-400">{result.domain}</p>
          <p className="text-lg text-blue-700 hover:underline dark:text-blue-400">{result.title}</p>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{result.snippet}</p>
        </div>
      </Link>
    );
  }

  return (
    <div className="mb-6 max-w-2xl">
      <p className="text-xs text-slate-500 dark:text-slate-400">{result.url}</p>
      <a href={result.url} className="block text-lg text-blue-700 hover:underline dark:text-blue-400">
        {result.title}
      </a>
      <p className="mt-1 text-sm leading-relaxed text-slate-600 dark:text-slate-400">{result.snippet}</p>
    </div>
  );
}
