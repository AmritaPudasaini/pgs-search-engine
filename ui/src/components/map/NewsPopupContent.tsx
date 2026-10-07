import { Newspaper } from "lucide-react";
import { generateMockNews } from "@/lib/mock/news";

export function NewsPopupContent({ place, listMaxHeight }: { place: string; listMaxHeight?: number }) {
  const news = generateMockNews(place, 4);

  return (
    <div className="w-64 max-w-[80vw]">
      <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <Newspaper className="h-4 w-4 text-blue-600" />
        Latest news · {place}
      </div>
      <ul
        className="max-h-64 space-y-2 overflow-y-auto"
        style={listMaxHeight ? { maxHeight: listMaxHeight } : undefined}
      >
        {news.map((item) => (
          <li key={item.id} className="border-b border-slate-100 pb-2 last:border-0 last:pb-0">
            <p className="text-sm font-medium leading-snug text-slate-900">{item.title}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {item.source} · {item.publishedAt}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">{item.snippet}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
