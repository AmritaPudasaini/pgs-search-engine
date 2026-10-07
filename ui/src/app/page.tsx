import { TopNav } from "@/components/layout/TopNav";
import { PgsLogo } from "@/components/home/PgsLogo";
import { SearchBox } from "@/components/home/SearchBox";
import { GeoTeaser } from "@/components/home/GeoTeaser";

export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-white dark:bg-slate-950">
      <TopNav />

      <main className="flex flex-1 flex-col items-center px-6 pt-[14vh] pb-16">
        <PgsLogo />

        <div className="mt-8 w-full max-w-[600px]">
          <SearchBox />
        </div>

        <div className="mt-6 flex gap-3">
          <button className="rounded-md bg-slate-50 px-4 py-2 text-sm text-slate-700 hover:border hover:border-slate-200 hover:shadow-sm dark:bg-slate-800 dark:text-slate-200">
            PGS Search
          </button>
          <button className="rounded-md bg-slate-50 px-4 py-2 text-sm text-slate-700 hover:border hover:border-slate-200 hover:shadow-sm dark:bg-slate-800 dark:text-slate-200">
            Feeling Precise
          </button>
        </div>

        <div className="mt-14">
          <GeoTeaser />
        </div>
      </main>

      <footer className="border-t border-slate-200 px-6 py-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span>Nepal</span>
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span>About</span>
            <span>Coverage</span>
            <span>Privacy</span>
            <span>Terms</span>
            <a href="/login" className="hover:underline">
              Sign in
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
