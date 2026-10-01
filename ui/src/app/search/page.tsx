import Link from "next/link";
import { TopNav } from "@/components/layout/TopNav";
import { SearchBox } from "@/components/home/SearchBox";
import { SearchTabs } from "@/components/search/SearchTabs";
import { ResultItem } from "@/components/search/ResultItem";
import { PgsLogo } from "@/components/home/PgsLogo";
import { generateMockResults } from "@/lib/mock/search";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q = "" } = await searchParams;
  const results = generateMockResults(q);

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950">
      <TopNav />

      <div className="border-b border-slate-200 px-6 pb-4 dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-6">
          <Link href="/">
            <PgsLogo size="small" />
          </Link>
          <div className="min-w-[280px] max-w-xl flex-1">
            <SearchBox autoFocus={false} initialValue={q} compact />
          </div>
        </div>
        <div className="mt-3">
          <SearchTabs />
        </div>
      </div>

      <main className="px-6 py-6">
        {q ? (
          <>
            <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
              About {(1200 + q.length * 37).toLocaleString()} results for &ldquo;{q}&rdquo;
            </p>
            {results.map((r) => (
              <ResultItem key={r.id} result={r} />
            ))}
          </>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Type a query above to search PGS records.
          </p>
        )}
      </main>
    </div>
  );
}
