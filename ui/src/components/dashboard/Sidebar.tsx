import Link from "next/link";
import { Gauge, MapPinned, Search } from "lucide-react";
import { PgsLogo } from "@/components/home/PgsLogo";

const NAV = [
  { label: "Overview", href: "/dashboard", icon: Gauge, active: true },
  { label: "Geo Explorer", href: "/map", icon: MapPinned, active: false },
  { label: "Search", href: "/", icon: Search, active: false },
];

export function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 border-r border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:block">
      <Link href="/" className="block px-1">
        <PgsLogo size="small" />
      </Link>
      <nav className="mt-8 space-y-1">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={
              item.active
                ? "flex items-center gap-2 rounded-lg bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-400"
                : "flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
