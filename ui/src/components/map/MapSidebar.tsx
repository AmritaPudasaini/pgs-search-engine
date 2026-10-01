"use client";

import { useMemo, useState } from "react";
import { MapPin, Search, Tag, Trash2, X } from "lucide-react";
import { cn } from "@/lib/cn";
import type { GeoTag } from "@/lib/types";
import type { DistrictCollection, MunicipalityCollection } from "@/lib/geo";

interface SearchHit {
  type: "district" | "municipality";
  name: string;
  district: string;
  level?: string;
}

export function MapSidebar({
  districts,
  municipalities,
  selectedDistrict,
  onSelectDistrict,
  onFocusMunicipality,
  taggingMode,
  onToggleTagging,
  pendingTag,
  onSavePendingTag,
  onCancelPendingTag,
  tags,
  onRemoveTag,
  loading,
}: {
  districts: DistrictCollection | null;
  municipalities: MunicipalityCollection | null;
  selectedDistrict: string | null;
  onSelectDistrict: (name: string) => void;
  onFocusMunicipality: (name: string, district: string) => void;
  taggingMode: boolean;
  onToggleTagging: () => void;
  pendingTag: { lat: number; lng: number } | null;
  onSavePendingTag: (label: string, note: string) => void;
  onCancelPendingTag: () => void;
  tags: GeoTag[];
  onRemoveTag: (id: string) => void;
  loading: boolean;
}) {
  const [query, setQuery] = useState("");
  const [labelDraft, setLabelDraft] = useState("");
  const [noteDraft, setNoteDraft] = useState("");

  const hits = useMemo<SearchHit[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q || !districts) return [];
    const districtHits: SearchHit[] = districts.features
      .filter((f) => f.properties.DISTRICT.toLowerCase().includes(q))
      .map((f) => ({ type: "district", name: f.properties.DISTRICT, district: f.properties.DISTRICT }));

    const seenMuni = new Set<string>();
    const muniHits: SearchHit[] = municipalities
      ? municipalities.features
          .filter((f) => f.properties.NAME.toLowerCase().includes(q))
          .filter((f) => {
            if (seenMuni.has(f.properties.N_ID)) return false;
            seenMuni.add(f.properties.N_ID);
            return true;
          })
          .slice(0, 20)
          .map((f) => ({
            type: "municipality",
            name: f.properties.NAME,
            district: f.properties.DISTRICT,
            level: f.properties.LEVEL,
          }))
      : [];

    return [...districtHits, ...muniHits].slice(0, 25);
  }, [query, districts, municipalities]);

  const districtMunicipalities = useMemo(() => {
    if (!municipalities || !selectedDistrict) return [];
    const seen = new Set<string>();
    return municipalities.features
      .filter((f) => f.properties.DISTRICT.toLowerCase() === selectedDistrict.toLowerCase())
      .filter((f) => {
        if (seen.has(f.properties.N_ID)) return false;
        seen.add(f.properties.N_ID);
        return true;
      })
      .map((f) => f.properties);
  }, [municipalities, selectedDistrict]);

  return (
    <aside className="flex h-full w-full flex-col overflow-hidden border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 sm:w-80">
      <div className="border-b border-slate-200 p-3 dark:border-slate-800">
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search district or municipality"
            className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
          {query && (
            <button onClick={() => setQuery("")} aria-label="Clear">
              <X className="h-3.5 w-3.5 text-slate-400" />
            </button>
          )}
        </div>

        {hits.length > 0 && (
          <ul className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-slate-100 dark:border-slate-800">
            {hits.map((hit) => (
              <li key={`${hit.type}-${hit.name}-${hit.district}`}>
                <button
                  onClick={() => {
                    if (hit.type === "district") onSelectDistrict(hit.name);
                    else onFocusMunicipality(hit.name, hit.district);
                    setQuery("");
                  }}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                >
                  <span className="truncate">{hit.name}</span>
                  <span className="shrink-0 text-xs text-slate-400">
                    {hit.type === "district" ? "District" : hit.district}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <button
        onClick={onToggleTagging}
        className={cn(
          "mx-3 mt-3 flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
          taggingMode
            ? "border-blue-600 bg-blue-600 text-white"
            : "border-slate-200 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        )}
      >
        <Tag className="h-4 w-4" />
        {taggingMode ? "Tagging mode on — click the map" : "Add a geo-tag"}
      </button>

      {pendingTag && (
        <div className="mx-3 mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-500/30 dark:bg-blue-500/10">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {pendingTag.lat.toFixed(4)}, {pendingTag.lng.toFixed(4)}
          </p>
          <input
            value={labelDraft}
            onChange={(e) => setLabelDraft(e.target.value)}
            placeholder="Label (e.g. Survey point A)"
            className="mt-2 w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm outline-none focus:border-blue-500 dark:border-slate-700 dark:bg-slate-900"
          />
          <textarea
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            placeholder="Note (optional)"
            rows={2}
            className="mt-2 w-full resize-none rounded-md border border-slate-200 px-2 py-1.5 text-sm outline-none focus:border-blue-500 dark:border-slate-700 dark:bg-slate-900"
          />
          <div className="mt-2 flex gap-2">
            <button
              disabled={!labelDraft.trim()}
              onClick={() => {
                onSavePendingTag(labelDraft.trim(), noteDraft.trim());
                setLabelDraft("");
                setNoteDraft("");
              }}
              className="flex-1 rounded-md bg-blue-600 py-1.5 text-sm font-medium text-white disabled:opacity-40"
            >
              Save tag
            </button>
            <button
              onClick={() => {
                onCancelPendingTag();
                setLabelDraft("");
                setNoteDraft("");
              }}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3">
        {loading && <p className="text-sm text-slate-400">Loading boundaries…</p>}

        {!loading && selectedDistrict && (
          <div className="mb-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{selectedDistrict}</h3>
              <button
                onClick={() => onSelectDistrict("")}
                className="text-xs text-slate-400 hover:text-slate-600"
              >
                Clear
              </button>
            </div>
            <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
              {districtMunicipalities.length} local levels
            </p>
            <ul className="space-y-1">
              {districtMunicipalities.map((m) => (
                <li key={m.N_ID}>
                  <button
                    onClick={() => onFocusMunicipality(m.NAME, m.DISTRICT)}
                    className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <span className="flex items-center gap-1.5 truncate">
                      <MapPin className="h-3 w-3 shrink-0 text-emerald-600" />
                      {m.NAME}
                    </span>
                    <span className="shrink-0 text-xs text-slate-400">{m.LEVEL}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!loading && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              Saved tags ({tags.length})
            </h3>
            {tags.length === 0 ? (
              <p className="text-xs text-slate-400">
                No geo-tags yet. Toggle &ldquo;Add a geo-tag&rdquo; and click anywhere on the map.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {tags.map((tag) => (
                  <li
                    key={tag.id}
                    className="flex items-start justify-between gap-2 rounded-md border border-slate-100 px-2 py-1.5 dark:border-slate-800"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-slate-800 dark:text-slate-200">{tag.label}</p>
                      <p className="truncate text-xs text-slate-400">{tag.note || "No note"}</p>
                    </div>
                    <button
                      onClick={() => onRemoveTag(tag.id)}
                      className="shrink-0 text-slate-300 hover:text-rose-600"
                      aria-label="Remove tag"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
