"use client";

import { cn } from "@/lib/cn";
import { useState } from "react";

const TABS = ["All", "Places", "News", "Images"];

export function SearchTabs() {
  const [active, setActive] = useState("All");
  return (
    <div className="flex gap-6 border-b border-slate-200 px-1 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
      {TABS.map((tab) => (
        <button
          key={tab}
          onClick={() => setActive(tab)}
          className={cn(
            "-mb-px border-b-2 py-3",
            active === tab
              ? "border-blue-600 text-blue-700 dark:text-blue-400"
              : "border-transparent hover:text-slate-700 dark:hover:text-slate-200"
          )}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
