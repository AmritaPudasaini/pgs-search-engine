import type { DistrictProperties, GeoTag, MunicipalityProperties, ProvinceProperties } from "@/lib/types";
import type { Feature, FeatureCollection, Polygon, MultiPolygon } from "geojson";

export type ProvinceFeature = Feature<Polygon | MultiPolygon, ProvinceProperties>;
export type DistrictFeature = Feature<Polygon | MultiPolygon, DistrictProperties>;
export type MunicipalityFeature = Feature<Polygon | MultiPolygon, MunicipalityProperties>;
export type ProvinceCollection = FeatureCollection<Polygon | MultiPolygon, ProvinceProperties>;
export type DistrictCollection = FeatureCollection<Polygon | MultiPolygon, DistrictProperties>;
export type MunicipalityCollection = FeatureCollection<Polygon | MultiPolygon, MunicipalityProperties>;

// The province layer (public/data/nepal-provinces.geojson) only carries a numeric
// ADM1_PCODE (NP01..NP07); map it to Nepal's official province names.
export const PROVINCE_NAMES: Record<string, string> = {
  NP01: "Koshi Province",
  NP02: "Madhesh Province",
  NP03: "Bagmati Province",
  NP04: "Gandaki Province",
  NP05: "Lumbini Province",
  NP06: "Karnali Province",
  NP07: "Sudurpashchim Province",
};

export function getProvinceName(feature: ProvinceFeature): string {
  return PROVINCE_NAMES[feature.properties.ADM1_PCODE] ?? `Province ${feature.properties.ADM1_EN}`;
}

// Categorical fill per province for the static overview map + sidebar legend.
// Picked for mutual contrast rather than any official branding.
export const PROVINCE_COLORS: Record<string, string> = {
  "Koshi Province": "#f2a58e",
  "Madhesh Province": "#93c5fd",
  "Bagmati Province": "#86e0a0",
  "Gandaki Province": "#f7b267",
  "Lumbini Province": "#f0a3d0",
  "Karnali Province": "#f6e07a",
  "Sudurpashchim Province": "#b3b3e6",
};

export const DEFAULT_PROVINCE_COLOR = "#cbd5e1";

export function getProvinceColor(provinceName: string | undefined): string {
  if (!provinceName) return DEFAULT_PROVINCE_COLOR;
  return PROVINCE_COLORS[provinceName] ?? DEFAULT_PROVINCE_COLOR;
}

// The district layer predates the 2017 province split, so Nawalparasi and Rukum
// are each still one district even though their post-split halves sit in different
// provinces today. They're bucketed under their historically dominant province.
export const DISTRICT_TO_PROVINCE: Record<string, string> = {
  TAPLEJUNG: "Koshi Province", PANCHTHAR: "Koshi Province", ILAM: "Koshi Province",
  JHAPA: "Koshi Province", MORANG: "Koshi Province", SUNSARI: "Koshi Province",
  DHANKUTA: "Koshi Province", TEHRATHUM: "Koshi Province", SANKHUWASABHA: "Koshi Province",
  BHOJPUR: "Koshi Province", SOLUKHUMBU: "Koshi Province", OKHALDHUNGA: "Koshi Province",
  KHOTANG: "Koshi Province", UDAYAPUR: "Koshi Province",

  SAPTARI: "Madhesh Province", SIRAHA: "Madhesh Province", DHANUSA: "Madhesh Province",
  MAHOTTARI: "Madhesh Province", SARLAHI: "Madhesh Province", BARA: "Madhesh Province",
  PARSA: "Madhesh Province", RAUTAHAT: "Madhesh Province",

  SINDHULI: "Bagmati Province", RAMECHHAP: "Bagmati Province", DOLAKHA: "Bagmati Province",
  BHAKTAPUR: "Bagmati Province", DHADING: "Bagmati Province", KATHMANDU: "Bagmati Province",
  KAVRE: "Bagmati Province", LALITPUR: "Bagmati Province", NUWAKOT: "Bagmati Province",
  RASUWA: "Bagmati Province", SINDHUPALCHOK: "Bagmati Province", CHITWAN: "Bagmati Province",
  MAKWANPUR: "Bagmati Province",

  BAGLUNG: "Gandaki Province", GORKHA: "Gandaki Province", KASKI: "Gandaki Province",
  LAMJUNG: "Gandaki Province", MANANG: "Gandaki Province", MUSTANG: "Gandaki Province",
  MYAGDI: "Gandaki Province", NAWALPARASI: "Gandaki Province", PARBAT: "Gandaki Province",
  SYANGJA: "Gandaki Province", TANAHU: "Gandaki Province",

  RUPANDEHI: "Lumbini Province", KAPILBASTU: "Lumbini Province", ARGHAKHANCHI: "Lumbini Province",
  GULMI: "Lumbini Province", PALPA: "Lumbini Province", DANG: "Lumbini Province",
  PYUTHAN: "Lumbini Province", ROLPA: "Lumbini Province", BANKE: "Lumbini Province",
  BARDIYA: "Lumbini Province",

  RUKUM: "Karnali Province", SALYAN: "Karnali Province", DOLPA: "Karnali Province",
  HUMLA: "Karnali Province", JUMLA: "Karnali Province", KALIKOT: "Karnali Province",
  MUGU: "Karnali Province", SURKHET: "Karnali Province", DAILEKH: "Karnali Province",
  JAJARKOT: "Karnali Province",

  KAILALI: "Sudurpashchim Province", ACHHAM: "Sudurpashchim Province", DOTI: "Sudurpashchim Province",
  BAJURA: "Sudurpashchim Province", BAJHANG: "Sudurpashchim Province", KANCHANPUR: "Sudurpashchim Province",
  DADELDHURA: "Sudurpashchim Province", BAITADI: "Sudurpashchim Province", DARCHULA: "Sudurpashchim Province",
};

export function getDistrictProvince(districtName: string): string | undefined {
  return DISTRICT_TO_PROVINCE[districtName.toUpperCase()];
}

// The municipality layer uses Nepali local-government terms, spelled
// inconsistently in the source data ("Upamahanagarpalika", "maha Nagarpalika",
// "gaupaika", "hungint-reserve", trailing newlines…). Normalize to letters only
// and map to plain English so the map reads for everyone.
const LEVEL_LABELS: Record<string, string> = {
  mahanagarpalika: "Metropolitan city",
  upamahanagarpalika: "Sub-metropolitan city",
  nagarpalika: "Municipality",
  gaunpalika: "Rural municipality",
  gaupaika: "Rural municipality",
  nationalpark: "National park",
  wildlifereserve: "Wildlife reserve",
  huntingreserve: "Hunting reserve",
  hungintreserve: "Hunting reserve",
};

export function getLevelLabel(level: string | null | undefined): string {
  if (!level) return "Local area";
  const key = level.toLowerCase().replace(/[^a-z]/g, "");
  return LEVEL_LABELS[key] ?? titleCase(level.trim());
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(" ")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export const GEO_TAGS_STORAGE_KEY = "pgs_geo_tags";

export function loadStoredTags(): GeoTag[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(GEO_TAGS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveStoredTags(tags: GeoTag[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(GEO_TAGS_STORAGE_KEY, JSON.stringify(tags));
  } catch {
    // ignore write failures (private browsing, quota, etc.)
  }
}
