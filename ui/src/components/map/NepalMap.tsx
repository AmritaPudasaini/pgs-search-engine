"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, GeoJSON, Marker, Popup, useMap, useMapEvents } from "react-leaflet";
import L, { type Layer, type LeafletMouseEvent, type PathOptions } from "leaflet";
import type { Feature } from "geojson";
import { House, Minus, MousePointerClick, Plus } from "lucide-react";
import {
  getDistrictProvince,
  getLevelLabel,
  getProvinceColor,
  getProvinceName,
  titleCase,
  type DistrictFeature,
  type DistrictCollection,
  type MunicipalityCollection,
  type MunicipalityFeature,
  type ProvinceCollection,
  type ProvinceFeature,
} from "@/lib/geo";
import type { GeoTag } from "@/lib/types";
import { NewsPopupContent } from "@/components/map/NewsPopupContent";

const TAG_ICON = L.divIcon({
  className: "",
  html: `<div style="width:16px;height:16px;border-radius:9999px;background:#2563eb;border:2px solid white;box-shadow:0 0 0 2px #2563eb55"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

// Short map labels for districts too small to fit their full name. Only the
// label on the map is shortened; the hover card and sidebar show the full name.
const MAP_LABEL_ABBREVIATIONS: Record<string, string> = {
  KATHMANDU: "Ktm",
  LALITPUR: "Lal",
  BHAKTAPUR: "Bkt",
  KAVREPALANCHOK: "Kavre",
};

// The spot the user just clicked in pin mode, before they've named it.
const PENDING_ICON = L.divIcon({
  className: "",
  html: `<div style="width:18px;height:18px;border-radius:9999px;background:#f59e0b;border:3px solid white;box-shadow:0 0 0 3px #f59e0b66"></div>`,
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

// Nepal's approximate extent, used to fit the initial view. There's no tile
// basemap to worry about bleeding into India/China anymore (the GeoJSON is
// drawn on a blank canvas), so the view is free to zoom out as far as it
// needs to fit Nepal's full ~2:1 width. That full-country fit is also the
// zoom-out limit — past it there's only blank canvas.
const NEPAL_BOUNDS = L.latLngBounds([26.3, 80.0], [30.5, 88.3]);
const NEPAL_MAX_BOUNDS: L.LatLngBoundsExpression = [
  [25.9, 79.6],
  [30.9, 88.7],
];
// Floor low enough that fitBounds can always show the whole country regardless
// of panel aspect ratio; ceiling generous enough for the municipality-level
// flyTo when focusing a search result.
const MIN_ZOOM = 5;
const MAX_ZOOM = 13;

export interface FocusRequest {
  seq: number;
  kind: "country" | "province" | "district" | "municipality";
  name: string;
  district?: string;
}

function BoundsController() {
  const map = useMap();

  useEffect(() => {
    let fittedSize: L.Point | null = null;

    function apply() {
      // Inside a flex layout the container can report a 0/stale, pre-layout size
      // on early ticks; invalidateSize() forces Leaflet to re-measure before we
      // fit. Re-fitting on every resize (sidebar toggle, window resize) keeps the
      // full country filling the panel instead of freezing at whatever size the
      // container happened to be first; it does reset any zoom the user applied.
      map.invalidateSize();

      const size = map.getSize();
      // ResizeObserver also fires once right after observe() with the size we
      // just fitted to. Refitting then would cancel a focus flyTo that started
      // on page load (e.g. /map?focus=Pokhara), so only refit on a real change.
      if (fittedSize && size.equals(fittedSize)) return;
      if (size.x > 0 && size.y > 0) {
        fittedSize = size;
        // Drop the floor first: a smaller panel needs a lower fit zoom than the
        // previous floor, and fitBounds would otherwise clamp to it and clip.
        map.setMinZoom(MIN_ZOOM);
        map.fitBounds(NEPAL_BOUNDS, { animate: false, padding: [8, 8] });
        map.setMinZoom(map.getZoom());
      }
    }

    apply();
    const container = map.getContainer();
    const observer = new ResizeObserver(apply);
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);

  return null;
}

// At the full-country view there's nothing to pan to, so dragging only turns on
// once the user has zoomed in (via buttons, wheel/pinch, or a focus flyTo).
// Zooming back out from an off-center spot would otherwise land at the min zoom
// slightly shifted, clipping one edge of the country — so recenter there.
function PanWhenZoomed() {
  const map = useMap();
  useMapEvents({
    zoomend() {
      if (map.getZoom() > map.getMinZoom() + 0.01) {
        map.dragging.enable();
        return;
      }
      map.dragging.disable();
      // Popups belong to the zoomed-in context and won't fit the full-country
      // box without clipping.
      map.closePopup();
      // fitBounds centers on the projected (Mercator) midpoint, not the lat/lng
      // one, so compare in pixel space to match the initial full-country view.
      const zoom = map.getZoom();
      const target = map
        .project(NEPAL_BOUNDS.getSouthWest(), zoom)
        .add(map.project(NEPAL_BOUNDS.getNorthEast(), zoom))
        .divideBy(2);
      if (map.project(map.getCenter(), zoom).distanceTo(target) > 1) {
        map.panTo(map.unproject(target, zoom));
      }
    },
  });
  return null;
}

// Rendered as a sibling overlay rather than inside the Leaflet container: clicks
// then never reach Leaflet's own handlers (district select, tagging), and we
// avoid L.DomEvent.disableClickPropagation, which would also swallow the native
// event before React's root listener sees it.
function ZoomControls({ map }: { map: L.Map }) {
  const [zoomState, setZoomState] = useState(() => ({
    zoom: map.getZoom(),
    min: map.getMinZoom(),
    max: map.getMaxZoom(),
  }));

  useEffect(() => {
    // The min zoom moves whenever the panel resizes (see BoundsController), so
    // re-read it alongside the zoom itself.
    function sync() {
      setZoomState({ zoom: map.getZoom(), min: map.getMinZoom(), max: map.getMaxZoom() });
    }
    sync();
    map.on("zoomend zoomlevelschange resize", sync);
    return () => {
      map.off("zoomend zoomlevelschange resize", sync);
    };
  }, [map]);

  const atMin = zoomState.zoom <= zoomState.min + 0.01;
  const atMax = zoomState.zoom >= zoomState.max - 0.01;
  const buttonClass =
    "flex h-8 w-8 items-center justify-center text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-transparent";

  return (
    <div data-map-overlay className="absolute right-3 top-3 z-[1000] flex flex-col divide-y divide-slate-200 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <button type="button" aria-label="Zoom in" title="Zoom in" disabled={atMax} onClick={() => map.zoomIn(1)} className={buttonClass}>
        <Plus className="h-4 w-4" />
      </button>
      <button type="button" aria-label="Zoom out" title="Zoom out" disabled={atMin} onClick={() => map.zoomOut(1)} className={buttonClass}>
        <Minus className="h-4 w-4" />
      </button>
      <button
        type="button"
        aria-label="Show all of Nepal"
        title="Show all of Nepal"
        disabled={atMin}
        onClick={() => map.flyToBounds(NEPAL_BOUNDS, { padding: [8, 8], duration: 0.6 })}
        className={buttonClass}
      >
        <House className="h-4 w-4" />
      </button>
    </div>
  );
}


function FocusHandler({
  focusRequest,
  provinces,
  districts,
  municipalities,
}: {
  focusRequest: FocusRequest | null;
  provinces: ProvinceCollection | null;
  districts: DistrictCollection | null;
  municipalities: MunicipalityCollection | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!focusRequest) return;

    if (focusRequest.kind === "country") {
      map.flyToBounds(NEPAL_BOUNDS, { padding: [8, 8], duration: 0.8 });
      return;
    }

    if (focusRequest.kind === "province" && provinces) {
      const feature = provinces.features.find(
        (f) => getProvinceName(f).toLowerCase() === focusRequest.name.toLowerCase()
      );
      if (feature) {
        map.flyToBounds(L.geoJSON(feature).getBounds(), { padding: [30, 30], duration: 0.8 });
      }
      return;
    }

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
  provinces,
  districts,
  municipalities,
  selectedProvince,
  selectedDistrict,
  onSelectDistrict,
  focusRequest,
  taggingMode,
  onMapClick,
  pendingTag,
  tags,
  onRemoveTag,
}: {
  provinces: ProvinceCollection | null;
  districts: DistrictCollection | null;
  municipalities: MunicipalityCollection | null;
  selectedProvince: string | null;
  // Districts now cover the whole map, so selecting one (which also implies its
  // province, handled in GeoExplorer) covers what a province-only click used to
  // do. Kept in the prop contract since GeoExplorer still passes it through.
  onSelectProvince: (name: string) => void;
  selectedDistrict: string | null;
  onSelectDistrict: (name: string) => void;
  focusRequest: FocusRequest | null;
  taggingMode: boolean;
  onMapClick: (lat: number, lng: number, district?: string) => void;
  pendingTag: { lat: number; lng: number } | null;
  tags: GeoTag[];
  onRemoveTag: (id: string) => void;
}) {
  const [newsTarget, setNewsTarget] = useState<{ name: string; lat: number; lng: number } | null>(null);
  const [map, setMap] = useState<L.Map | null>(null);
  const [hovered, setHovered] = useState<HoverTarget | null>(null);
  const districtLayersRef = useRef(new Map<string, L.Polygon>());
  // Keyed by N_ID; only the first shape of a multi-part municipality gets a label.
  const municipalityLayersRef = useRef(new Map<string, L.Polygon>());

  // Place labels the way printed maps do: a name may spill past its own border
  // into open space. If its centered spot overlaps a name already placed, try a
  // few spots just around it (above, below, right, left); only if all are taken
  // is it hidden. Placement order decides who gets first pick: municipalities of
  // the selected district, then the selected district, then districts in the
  // selected province, then the rest. Hidden names reappear on zoom; the hover
  // card names every place.
  const updateLabelVisibility = useCallback(() => {
    if (!map) return;
    // Wait a frame so Leaflet has repositioned the tooltips for the new zoom.
    requestAnimationFrame(() => {
      const items: { el: HTMLElement; priority: number; area: number; forced: boolean }[] = [];
      function measure(layer: L.Polygon) {
        const bounds = layer.getBounds();
        const nw = map!.latLngToContainerPoint(bounds.getNorthWest());
        const se = map!.latLngToContainerPoint(bounds.getSouthEast());
        return (se.x - nw.x) * (se.y - nw.y);
      }

      municipalityLayersRef.current.forEach((layer) => {
        const el = layer.getTooltip()?.getElement();
        if (!el || !map.hasLayer(layer)) return;
        items.push({ el, priority: 3, area: measure(layer), forced: false });
      });
      // With its municipalities named on the map, the selected district's own
      // name (also in the context bar and breadcrumb) no longer has to win.
      const showingMunicipalities = items.length > 0;

      districtLayersRef.current.forEach((layer, name) => {
        const el = layer.getTooltip()?.getElement();
        if (!el || !map.hasLayer(layer)) return;
        const isSelected = name.toLowerCase() === selectedDistrict?.toLowerCase();
        const inSelectedProvince = Boolean(selectedProvince) && getDistrictProvince(name) === selectedProvince;
        items.push({
          el,
          priority: isSelected ? 2 : inSelectedProvince ? 1 : 0,
          area: measure(layer),
          forced: isSelected && !showingMunicipalities,
        });
      });
      // Scale-dependent order, as in printed atlases. At the full-country view
      // bigger districts pick first, so the overview names the major ones.
      // Once zoomed in there's room to spare, so smaller districts pick first:
      // a big district can nudge its name aside, a tiny one (Bhaktapur,
      // Lalitpur) has nowhere else to go.
      const zoomedIn = map.getZoom() > map.getMinZoom() + 0.5;
      items.sort((a, b) => b.priority - a.priority || (zoomedIn ? a.area - b.area : b.area - a.area));

      // Clear last time's nudges, then measure every label once at its centered
      // spot (rects are measurable even while visibility:hidden). Candidate
      // spots are then tested arithmetically — no re-layout per try.
      for (const item of items) item.el.style.margin = "0";
      const rects = items.map((item) => item.el.getBoundingClientRect());

      const GAP = 2;
      // A name half cut off by the map's edge is worse than a missing one, so
      // every spot must fit fully inside the map.
      const frame = map.getContainer().getBoundingClientRect();
      // The zoom buttons and credit line sit on top of the map; treat them as
      // already-taken space so no name ends up hidden underneath.
      const placed: { left: number; right: number; top: number; bottom: number }[] = Array.from(
        map.getContainer().parentElement?.querySelectorAll<HTMLElement>("[data-map-overlay]") ?? [],
        (el) => el.getBoundingClientRect()
      );
      items.forEach((item, i) => {
        const r = rects[i];
        const up = -(r.height + GAP);
        const down = r.height + GAP;
        const right = r.width / 2 + GAP;
        const left = -(r.width / 2 + GAP);
        const candidates: [number, number][] = [
          [0, 0],
          [0, up],
          [0, down],
          [right, 0],
          [left, 0],
          [right, up],
          [right, down],
          [left, up],
          [left, down],
        ];
        let chosen: [number, number] | null = null;
        for (const [dx, dy] of candidates) {
          const box = { left: r.left + dx, right: r.right + dx, top: r.top + dy, bottom: r.bottom + dy };
          const insideFrame =
            box.left >= frame.left + GAP &&
            box.right <= frame.right - GAP &&
            box.top >= frame.top + GAP &&
            box.bottom <= frame.bottom - GAP;
          if (!insideFrame) continue;
          const collides = placed.some(
            (p) => box.left < p.right + GAP && box.right > p.left - GAP && box.top < p.bottom + GAP && box.bottom > p.top - GAP
          );
          if (!collides || item.forced) {
            chosen = [dx, dy];
            placed.push(box);
            break;
          }
        }
        item.el.classList.toggle("district-label--placed", Boolean(chosen));
        if (chosen) item.el.style.margin = `${chosen[1]}px 0 0 ${chosen[0]}px`;
      });
    });
  }, [map, selectedDistrict, selectedProvince]);

  useEffect(() => {
    if (!map) return;
    updateLabelVisibility();
    map.on("zoomend", updateLabelVisibility);
    return () => {
      map.off("zoomend", updateLabelVisibility);
    };
    // municipalities: their labels need placing once the background load lands.
  }, [map, updateLabelVisibility, districts, municipalities, selectedProvince]);

  // onEachFeature only runs once per layer, so click handlers close over stale props.
  // Read tagging mode from a ref that's always current instead of the closed-over value.
  const taggingModeRef = useRef(taggingMode);
  const onMapClickRef = useRef(onMapClick);
  useEffect(() => {
    taggingModeRef.current = taggingMode;
    onMapClickRef.current = onMapClick;
  }, [taggingMode, onMapClick]);

  const filteredMunicipalities = useMemo(() => {
    if (!municipalities || !selectedDistrict) return null;
    return {
      ...municipalities,
      features: municipalities.features.filter(
        (f) => f.properties.DISTRICT.toLowerCase() === selectedDistrict.toLowerCase()
      ),
    };
  }, [municipalities, selectedDistrict]);

  // Every district renders at once, tinted by its province, like a printed
  // administrative map — selection just dims everything outside the active
  // province and picks out the active district's border.
  //
  // Memoized on the selection only: GeoJSON calls setStyle() on all 77
  // districts whenever this function's identity changes, so it must not change
  // on hover. Hover is applied to the one layer under the pointer instead.
  const districtStyle = useCallback(
    (feature?: Feature): PathOptions => {
      const name = (feature as DistrictFeature | undefined)?.properties.DISTRICT ?? "";
      const province = getDistrictProvince(name);
      const isSelectedDistrict = name.toLowerCase() === selectedDistrict?.toLowerCase();
      const isDimmed = Boolean(selectedProvince) && province !== selectedProvince;
      return {
        color: isSelectedDistrict ? "#1d4ed8" : "#ffffff",
        weight: isSelectedDistrict ? 2.5 : 1,
        fillColor: getProvinceColor(province),
        fillOpacity: isDimmed ? 0.2 : isSelectedDistrict ? 1 : 0.82,
      };
    },
    [selectedDistrict, selectedProvince]
  );
  // Layer event handlers are bound once per layer, so they read the current
  // style function through a ref rather than the one from when they were bound.
  const districtStyleRef = useRef(districtStyle);
  useEffect(() => {
    districtStyleRef.current = districtStyle;
  }, [districtStyle]);

  function onEachDistrict(feature: Feature, layer: Layer) {
    const props = (feature as DistrictFeature).properties;
    const path = layer as L.Polygon;
    districtLayersRef.current.set(props.DISTRICT, path);
    layer.bindTooltip(MAP_LABEL_ABBREVIATIONS[props.DISTRICT] ?? titleCase(props.DISTRICT), {
      permanent: true,
      direction: "center",
      className: "district-label",
      interactive: false,
    });
    layer.on("click", (e: LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(e);
      // Pin mode: drop the pin where they clicked, without selecting the district
      // (selecting would fly the map away from the spot they just picked).
      if (taggingModeRef.current) {
        onMapClickRef.current(e.latlng.lat, e.latlng.lng, props.DISTRICT);
        return;
      }
      onSelectDistrict(props.DISTRICT);
      const center = (layer as L.Polygon).getBounds().getCenter();
      setNewsTarget({ name: props.DISTRICT, lat: center.lat, lng: center.lng });
    });
    layer.on("mouseover", () => {
      const base = districtStyleRef.current(feature);
      path.setStyle({
        color: base.color === "#ffffff" ? "#0f172a" : base.color,
        weight: 2.5,
        fillOpacity: base.fillOpacity === 0.2 ? 0.45 : 1,
      });
      setHovered({ kind: "district", name: props.DISTRICT });
    });
    layer.on("mouseout", () => {
      path.setStyle(districtStyleRef.current(feature));
      setHovered((current) => (current?.kind === "district" && current.name === props.DISTRICT ? null : current));
    });
  }

  // Province outlines sit on top purely as a bolder boundary between
  // same-colored district clusters — no fill, no clicks of their own (the
  // district layer beneath already reports province selection on click).
  const provinceBoundaryStyle = useCallback(
    (feature?: Feature): PathOptions => {
      const name = feature ? getProvinceName(feature as ProvinceFeature) : undefined;
      const isSelected = name?.toLowerCase() === selectedProvince?.toLowerCase();
      return {
        fill: false,
        color: isSelected ? "#1d4ed8" : "#334155",
        weight: isSelected ? 3 : 1.75,
        opacity: isSelected ? 1 : 0.75,
        interactive: false,
      };
    },
    [selectedProvince]
  );

  // Municipalities keep their district's province color, split by white
  // borders like the districts themselves (a translucent green overlay used to
  // turn e.g. Gandaki's orange a muddy olive).
  const municipalityStyle = useCallback((feature?: Feature): PathOptions => {
    const district = (feature as MunicipalityFeature | undefined)?.properties.DISTRICT ?? "";
    return {
      color: "#ffffff",
      weight: 1,
      fillColor: getProvinceColor(getDistrictProvince(district)),
      fillOpacity: 1,
    };
  }, []);

  // The selected district's blue outline, redrawn above the municipalities
  // (whose white borders would otherwise cover it).
  const selectedDistrictFeature = useMemo(
    () =>
      selectedDistrict
        ? districts?.features.find((f) => f.properties.DISTRICT.toLowerCase() === selectedDistrict.toLowerCase())
        : undefined,
    [districts, selectedDistrict]
  );

  // A multi-part municipality is several features with one N_ID; label only the
  // first. Leaflet hands onEachFeature these same feature objects.
  const labelledMunicipalityFeatures = useMemo(() => {
    const seen = new Set<string>();
    const firsts = new Set<Feature>();
    for (const f of filteredMunicipalities?.features ?? []) {
      if (seen.has(f.properties.N_ID)) continue;
      seen.add(f.properties.N_ID);
      firsts.add(f);
    }
    return firsts;
  }, [filteredMunicipalities]);

  function onEachMunicipality(feature: Feature, layer: Layer) {
    const props = (feature as MunicipalityFeature).properties;
    const path = layer as L.Polygon;
    if (labelledMunicipalityFeatures.has(feature)) {
      municipalityLayersRef.current.set(props.N_ID, path);
      path.bindTooltip(props.NAME, {
        permanent: true,
        direction: "center",
        className: "district-label municipality-label",
        interactive: false,
      });
    }
    layer.on("mouseover", () => {
      path.setStyle({ color: "#0f172a", weight: 2 });
      setHovered({ kind: "municipality", name: props.NAME, district: props.DISTRICT, level: props.LEVEL });
    });
    layer.on("mouseout", () => {
      path.setStyle({ color: "#ffffff", weight: 1 });
      setHovered((current) => (current?.kind === "municipality" && current.name === props.NAME ? null : current));
    });
    layer.on("click", (e: LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(e);
      if (taggingModeRef.current) {
        onMapClickRef.current(e.latlng.lat, e.latlng.lng, props.DISTRICT);
        return;
      }
      const center = (layer as L.Polygon).getBounds().getCenter();
      setNewsTarget({ name: props.NAME, lat: center.lat, lng: center.lng });
    });
  }

  return (
    // NEPAL_BOUNDS is ~1.73:1 in Leaflet's Mercator projection; a stretched
    // full-height panel just letterboxes it in white space. Size the Leaflet box
    // to just over that ratio and fitBounds then fills it nearly edge to edge.
    <div className="flex h-full w-full items-center justify-center p-2 sm:p-4">
      <div
        // Phones fill the panel instead: the country is width-bound either way,
        // and the extra card height gives news popups room to open.
        className={`relative h-full w-full overflow-hidden rounded-xl border bg-white shadow-sm sm:aspect-[7/4] sm:h-auto sm:max-h-full ${
          taggingMode
            ? "border-amber-400 ring-2 ring-amber-300/60 [&_.leaflet-container]:!cursor-crosshair [&_.leaflet-interactive]:!cursor-crosshair"
            : "border-slate-200 dark:border-slate-700"
        }`}
        role="region"
        aria-label="Map of Nepal by district"
        aria-describedby="nepal-map-help"
      >
      {/* The shapes themselves can't be reached by keyboard or read by a screen
          reader, so point to the side panel, which offers every place as a list. */}
      <p id="nepal-map-help" className="sr-only">
        Each district is colored by its province. To choose a province, district, or local government with a
        keyboard or screen reader, use &ldquo;Find a place&rdquo; or the lists in the side panel.
      </p>
      <MapContainer
        ref={setMap}
        center={[28.3949, 84.124]}
        zoom={MIN_ZOOM}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        // Whole-number zoom snapping makes fitBounds round down to the next level
        // that fits, which can leave the country at roughly half the panel size.
        zoomSnap={0}
        maxBounds={NEPAL_MAX_BOUNDS}
        maxBoundsViscosity={1.0}
        zoomControl={false}
        dragging={false}
        scrollWheelZoom
        touchZoom
        doubleClickZoom={false}
        boxZoom={false}
        keyboard={false}
        attributionControl={false}
        className="h-full w-full bg-white"
      >
        <BoundsController />
        <PanWhenZoomed />

        {districts && (
          <GeoJSON
            key={`districts-${selectedProvince ?? "none"}-${selectedDistrict ?? "none"}`}
            data={districts}
            style={districtStyle}
            onEachFeature={onEachDistrict}
          />
        )}

        {provinces && (
          <GeoJSON
            key={`province-outline-${selectedProvince ?? "none"}`}
            data={provinces}
            style={provinceBoundaryStyle}
          />
        )}

        {filteredMunicipalities && (
          <GeoJSON
            key={`municipalities-${selectedDistrict}`}
            data={filteredMunicipalities}
            style={municipalityStyle}
            onEachFeature={onEachMunicipality}
          />
        )}

        {filteredMunicipalities && selectedDistrictFeature && (
          <GeoJSON
            key={`selected-outline-${selectedDistrict}`}
            data={selectedDistrictFeature}
            style={{ fill: false, color: "#1d4ed8", weight: 3, interactive: false }}
          />
        )}

        {tags.map((tag) => (
          <Marker key={tag.id} position={[tag.lat, tag.lng]} icon={TAG_ICON}>
            <Popup>
              <div className="min-w-[160px] text-sm">
                <p className="font-semibold">{tag.label}</p>
                {tag.note && <p className="mt-1 text-slate-600">{tag.note}</p>}
                {tag.district && (
                  <p className="mt-1 text-xs text-slate-500">{titleCase(tag.district)} district</p>
                )}
                <button
                  type="button"
                  onClick={() => onRemoveTag(tag.id)}
                  className="mt-2 text-xs font-medium text-rose-600 hover:underline"
                >
                  Delete pin
                </button>
              </div>
            </Popup>
          </Marker>
        ))}

        {pendingTag && (
          <Marker position={[pendingTag.lat, pendingTag.lng]} icon={PENDING_ICON} interactive={false} />
        )}

        {newsTarget && (
          <Popup
            key={`${newsTarget.name}-${newsTarget.lat}-${newsTarget.lng}`}
            position={[newsTarget.lat, newsTarget.lng]}
            eventHandlers={{ remove: () => setNewsTarget(null) }}
          >
            {/* The popup opens while a flyTo recenters the clicked place, which
                overrides Leaflet's autoPan — so cap the list to the space above
                center (minus header, padding and tip). */}
            <NewsPopupContent
              place={titleCase(newsTarget.name)}
              listMaxHeight={map ? Math.max(90, map.getSize().y / 2 - 110) : undefined}
            />
          </Popup>
        )}

        <FocusHandler
          focusRequest={focusRequest}
          provinces={provinces}
          districts={districts}
          municipalities={municipalities}
        />
      </MapContainer>
      {map && <ZoomControls map={map} />}
      {hovered && <HoverCard target={hovered} taggingMode={taggingMode} />}
      {/* Required by the boundary data's CC BY 4.0 license. */}
      <a
        href="https://localboundries.oknp.org/"
        data-map-overlay
        target="_blank"
        rel="noopener noreferrer"
        className="absolute bottom-1 right-2 z-[1000] rounded bg-white/80 px-1.5 py-0.5 text-[10px] text-slate-500 hover:text-slate-800 hover:underline"
      >
        Boundaries: Open Knowledge Nepal, CC BY 4.0
      </a>
      </div>

      <style jsx global>{`
        .leaflet-container {
          background: #ffffff !important;
        }

        .district-label {
          background: transparent;
          border: none;
          box-shadow: none;
          padding: 0;
          margin: 0;
          font-size: 10px;
          font-weight: 600;
          line-height: 1;
          color: #0f172a;
          text-shadow:
            -1px -1px 0 #fff,
            1px -1px 0 #fff,
            -1px 1px 0 #fff,
            1px 1px 0 #fff,
            0 0 3px #fff;
          pointer-events: none;
          white-space: nowrap;
          /* Hidden until placement finds it a free spot, so freshly drawn
             labels never flash on top of each other. */
          visibility: hidden;
        }

        .district-label--placed {
          visibility: visible;
        }

        /* Lighter than district names, so the district still reads as the
           bigger unit when both are on screen. */
        .municipality-label {
          font-size: 9px;
          font-weight: 500;
          color: #334155;
        }
      `}</style>
    </div>
  );
}

type HoverTarget =
  | { kind: "district"; name: string }
  | { kind: "municipality"; name: string; district: string; level: string };

// Names the place under the pointer (even when its map label is hidden for
// space), shows where it belongs, and says what a click will do. Tucked in the
// bottom-left corner, which Nepal's shape leaves empty. Hidden on touch
// screens: a tap fires mouseover but never mouseout, so it would stick.
function HoverCard({ target, taggingMode }: { target: HoverTarget; taggingMode: boolean }) {
  const district = target.kind === "district" ? target.name : target.district;
  const province = getDistrictProvince(district);
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-[1000] hidden max-w-[70%] rounded-lg border border-slate-200 bg-white/95 px-3 py-2 shadow-md [@media(hover:hover)]:block">
      <p className="text-sm font-semibold text-slate-900">
        {target.kind === "district" ? `${titleCase(target.name)} district` : target.name}
      </p>
      {target.kind === "municipality" && (
        <p className="mt-0.5 text-xs text-slate-600">
          {getLevelLabel(target.level)} · {titleCase(target.district)} district
        </p>
      )}
      {target.kind === "district" && province && (
        <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-600">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: getProvinceColor(province) }} />
          {province}
        </p>
      )}
      <p className="mt-1 flex items-center gap-1 text-xs font-medium text-blue-700">
        <MousePointerClick className="h-3.5 w-3.5" />
        {taggingMode ? "Click to drop your pin here" : "Click to see local news"}
      </p>
    </div>
  );
}
