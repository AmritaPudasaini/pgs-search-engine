"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";
import { MapSidebar } from "@/components/map/MapSidebar";
import type { FocusRequest } from "@/components/map/NepalMap";
import type { DistrictCollection, MunicipalityCollection } from "@/lib/geo";
import { loadStoredTags, saveStoredTags } from "@/lib/geo";
import type { GeoTag } from "@/lib/types";

const NepalMap = dynamic(() => import("@/components/map/NepalMap").then((m) => m.NepalMap), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-sm text-slate-400">
      Loading map…
    </div>
  ),
});

export function GeoExplorer({ initialFocus }: { initialFocus?: string }) {
  const [districts, setDistricts] = useState<DistrictCollection | null>(null);
  const [municipalities, setMunicipalities] = useState<MunicipalityCollection | null>(null);
  const [loading, setLoading] = useState(true);

  const [selectedDistrict, setSelectedDistrict] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
  const focusSeq = useRef(0);

  const [taggingMode, setTaggingMode] = useState(false);
  const [pendingTag, setPendingTag] = useState<{ lat: number; lng: number } | null>(null);
  const [tags, setTags] = useState<GeoTag[]>([]);

  useEffect(() => {
    // Reads localStorage, which isn't available during SSR.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTags(loadStoredTags());
    Promise.all([
      fetch("/data/nepal-districts.geojson").then((r) => r.json()),
      fetch("/data/nepal-municipalities.geojson").then((r) => r.json()),
    ])
      .then(([d, m]: [DistrictCollection, MunicipalityCollection]) => {
        setDistricts(d);
        // The source dataset has a handful of malformed entries (null name/id) — drop them.
        setMunicipalities({
          ...m,
          features: m.features.filter((f) => f.properties.NAME && f.properties.N_ID),
        });
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (initialFocus && districts) {
      handleSelectDistrict(initialFocus);
    }
  }, [initialFocus, districts]);

  function handleSelectDistrict(name: string) {
    if (!name) {
      setSelectedDistrict(null);
      return;
    }
    setSelectedDistrict(name);
    focusSeq.current += 1;
    setFocusRequest({ seq: focusSeq.current, kind: "district", name });
  }

  function handleFocusMunicipality(name: string, district: string) {
    setSelectedDistrict(district);
    focusSeq.current += 1;
    setFocusRequest({ seq: focusSeq.current, kind: "municipality", name, district });
  }

  function handleMapClick(lat: number, lng: number) {
    if (!taggingMode) return;
    setPendingTag({ lat, lng });
  }

  function handleSavePendingTag(label: string, note: string) {
    if (!pendingTag) return;
    const tag: GeoTag = {
      id: `tag-${Date.now()}`,
      label,
      note,
      lat: pendingTag.lat,
      lng: pendingTag.lng,
      district: selectedDistrict ?? undefined,
      createdAt: new Date().toISOString(),
    };
    const next = [tag, ...tags];
    setTags(next);
    saveStoredTags(next);
    setPendingTag(null);
    setTaggingMode(false);
  }

  function handleRemoveTag(id: string) {
    const next = tags.filter((t) => t.id !== id);
    setTags(next);
    saveStoredTags(next);
  }

  const mapProps = useMemo(
    () => ({
      districts,
      municipalities,
      selectedDistrict,
      onSelectDistrict: handleSelectDistrict,
      focusRequest,
      taggingMode,
      onMapClick: handleMapClick,
      tags,
      onRemoveTag: handleRemoveTag,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [districts, municipalities, selectedDistrict, focusRequest, taggingMode, tags]
  );

  return (
    <div className="flex h-full w-full flex-col sm:flex-row">
      <MapSidebar
        districts={districts}
        municipalities={municipalities}
        selectedDistrict={selectedDistrict}
        onSelectDistrict={handleSelectDistrict}
        onFocusMunicipality={handleFocusMunicipality}
        taggingMode={taggingMode}
        onToggleTagging={() => {
          setTaggingMode((v) => !v);
          setPendingTag(null);
        }}
        pendingTag={pendingTag}
        onSavePendingTag={handleSavePendingTag}
        onCancelPendingTag={() => setPendingTag(null)}
        tags={tags}
        onRemoveTag={handleRemoveTag}
        loading={loading}
      />
      <div className="relative flex-1">
        <NepalMap {...mapProps} />
      </div>
    </div>
  );
}
