"use client";

import { useEffect, useMemo, useRef } from "react";
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, useMap, useMapEvents } from "react-leaflet";
import L, { type Layer, type LeafletMouseEvent } from "leaflet";
import type { Feature } from "geojson";
import type { DistrictFeature, DistrictCollection, MunicipalityCollection, MunicipalityFeature } from "@/lib/geo";
import type { GeoTag } from "@/lib/types";

const TAG_ICON = L.divIcon({
  className: "",
  html: `<div style="width:16px;height:16px;border-radius:9999px;background:#2563eb;border:2px solid white;box-shadow:0 0 0 2px #2563eb55"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const NEPAL_CENTER: [number, number] = [28.3949, 84.124];

export interface FocusRequest {
  seq: number;
  kind: "district" | "municipality";
  name: string;
  district?: string;
}

function ClickCatcher({ onMapClick }: { onMapClick: (lat: number, lng: number) => void }) {
  useMapEvents({
    click(e: LeafletMouseEvent) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

function FocusHandler({
  focusRequest,
  districts,
  municipalities,
}: {
  focusRequest: FocusRequest | null;
  districts: DistrictCollection | null;
  municipalities: MunicipalityCollection | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!focusRequest) return;

    if (focusRequest.kind === "district" && districts) {
      const feature = districts.features.find(
        (f) => f.properties.DISTRICT.toLowerCase() === focusRequest.name.toLowerCase()
      );
      if (feature) {
        map.flyToBounds(L.geoJSON(feature).getBounds(), { padding: [40, 40], duration: 0.8 });
      }
      return;
    }

    if (focusRequest.kind === "municipality" && municipalities) {
      const feature = municipalities.features.find(
        (f) =>
          f.properties.NAME.toLowerCase() === focusRequest.name.toLowerCase() &&
          f.properties.DISTRICT.toLowerCase() === (focusRequest.district ?? "").toLowerCase()
      );
      if (feature) {
        map.flyToBounds(L.geoJSON(feature).getBounds(), { padding: [60, 60], duration: 0.8 });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest]);

  return null;
}

export function NepalMap({
  districts,
  municipalities,
  selectedDistrict,
  onSelectDistrict,
  focusRequest,
  taggingMode,
  onMapClick,
  tags,
  onRemoveTag,
}: {
  districts: DistrictCollection | null;
  municipalities: MunicipalityCollection | null;
  selectedDistrict: string | null;
  onSelectDistrict: (name: string) => void;
  focusRequest: FocusRequest | null;
  taggingMode: boolean;
  onMapClick: (lat: number, lng: number) => void;
  tags: GeoTag[];
  onRemoveTag: (id: string) => void;
}) {
  const districtLayerRef = useRef<L.GeoJSON | null>(null);

  const filteredMunicipalities = useMemo(() => {
    if (!municipalities || !selectedDistrict) return null;
    return {
      ...municipalities,
      features: municipalities.features.filter(
        (f) => f.properties.DISTRICT.toLowerCase() === selectedDistrict.toLowerCase()
      ),
    };
  }, [municipalities, selectedDistrict]);

  function districtStyle(feature?: Feature) {
    const name = (feature as DistrictFeature | undefined)?.properties.DISTRICT;
    const isSelected = name?.toLowerCase() === selectedDistrict?.toLowerCase();
    return {
      color: isSelected ? "#1d4ed8" : "#64748b",
      weight: isSelected ? 2.5 : 1,
      fillColor: isSelected ? "#3b82f6" : "#94a3b8",
      fillOpacity: isSelected ? 0.25 : 0.08,
    };
  }

  function onEachDistrict(feature: Feature, layer: Layer) {
    const props = (feature as DistrictFeature).properties;
    layer.bindTooltip(props.DISTRICT, { sticky: true, className: "!text-xs" });
    layer.on("click", () => onSelectDistrict(props.DISTRICT));
    layer.on("mouseover", () => (layer as L.Path).setStyle({ fillOpacity: 0.3 }));
    layer.on("mouseout", () => {
      const name = props.DISTRICT;
      const isSelected = name.toLowerCase() === selectedDistrict?.toLowerCase();
      (layer as L.Path).setStyle({ fillOpacity: isSelected ? 0.25 : 0.08 });
    });
  }

  function municipalityStyle() {
    return {
      color: "#16a34a",
      weight: 1,
      fillColor: "#22c55e",
      fillOpacity: 0.18,
    };
  }

  function onEachMunicipality(feature: Feature, layer: Layer) {
    const props = (feature as MunicipalityFeature).properties;
    layer.bindTooltip(`${props.NAME} (${props.LEVEL})`, { sticky: true, className: "!text-xs" });
  }

  return (
    <MapContainer
      center={NEPAL_CENTER}
      zoom={7}
      minZoom={6}
      className="h-full w-full"
      style={{ cursor: taggingMode ? "crosshair" : "" }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {districts && (
        <GeoJSON
          ref={districtLayerRef}
          data={districts}
          style={districtStyle}
          onEachFeature={onEachDistrict}
        />
      )}

      {filteredMunicipalities && (
        <GeoJSON
          key={selectedDistrict}
          data={filteredMunicipalities}
          style={municipalityStyle}
          onEachFeature={onEachMunicipality}
        />
      )}

      {tags.map((tag) => (
        <Marker key={tag.id} position={[tag.lat, tag.lng]} icon={TAG_ICON}>
          <Popup>
            <div className="min-w-[160px] text-sm">
              <p className="font-semibold">{tag.label}</p>
              {tag.note && <p className="mt-1 text-slate-600">{tag.note}</p>}
              <p className="mt-1 text-xs text-slate-400">
                {tag.lat.toFixed(4)}, {tag.lng.toFixed(4)}
              </p>
              <button
                onClick={() => onRemoveTag(tag.id)}
                className="mt-2 text-xs font-medium text-rose-600 hover:underline"
              >
                Remove tag
              </button>
            </div>
          </Popup>
        </Marker>
      ))}

      <ClickCatcher onMapClick={onMapClick} />
      <FocusHandler focusRequest={focusRequest} districts={districts} municipalities={municipalities} />
    </MapContainer>
  );
}
