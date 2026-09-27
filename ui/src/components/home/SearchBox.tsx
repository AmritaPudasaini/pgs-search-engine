"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Mic, Search, X } from "lucide-react";
import { cn } from "@/lib/cn";

const SUGGESTIONS = [
  "Kathmandu district boundary",
  "Pokhara municipality ward map",
  "Chitwan geo tagging",
  "PGS dashboard metrics",
  "municipality index nepal",
  "Bhaktapur survey records",
];

export function SearchBox({
  autoFocus = true,
  initialValue = "",
  compact = false,
}: {
  autoFocus?: boolean;
  initialValue?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [value, setValue] = useState(initialValue);
  const [focused, setFocused] = useState(false);

  const suggestions = useMemo(() => {
    if (!value.trim()) return [];
    return SUGGESTIONS.filter((s) => s.toLowerCase().includes(value.toLowerCase())).slice(0, 5);
  }, [value]);

  function submit(query: string) {
    const q = query.trim();
    if (!q) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="relative w-full">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(value);
        }}
        className={cn(
          "flex items-center gap-3 rounded-full border border-slate-200 bg-white px-5 shadow-sm transition-shadow hover:shadow-md dark:border-slate-700 dark:bg-slate-800",
          compact ? "h-11" : "h-14",
          focused && "shadow-md"
        )}
      >
        <Search className="h-4 w-4 shrink-0 text-slate-400" />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 120)}
          autoFocus={autoFocus}
          placeholder="Search PGS records, districts, municipalities…"
          className="h-full flex-1 bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400 dark:text-slate-100"
        />
        {value && (
          <button
            type="button"
            onClick={() => setValue("")}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        <Mic className="h-4 w-4 shrink-0 text-blue-500" />
      </form>

      {focused && suggestions.length > 0 && (
        <ul className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-2xl border border-slate-200 bg-white py-2 shadow-lg dark:border-slate-700 dark:bg-slate-800">
          {suggestions.map((s) => (
            <li key={s}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => submit(s)}
                className="flex w-full items-center gap-3 px-5 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                <Search className="h-3.5 w-3.5 text-slate-400" />
                {s}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
