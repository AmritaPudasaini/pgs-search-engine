export interface SearchResult {
  id: string;
  title: string;
  url: string;
  domain: string;
  snippet: string;
  category: "web" | "place" | "news";
  district?: string;
}

export interface ProvinceProperties {
  ADM1_PCODE: string;
  ADM1_EN: string;
}

export interface DistrictProperties {
  DISTRICT: string;
}

export interface MunicipalityProperties {
  id: number | null;
  F_ID: number;
  N_ID: string;
  NAME: string;
  LEVEL: "Mahanagarpalika" | "Upa-Mahanagarpalika" | "Nagarpalika" | "Gaunpalika" | string;
  DISTRICT: string;
}

export interface GeoTag {
  id: string;
  label: string;
  note: string;
  lat: number;
  lng: number;
  district?: string;
  createdAt: string;
}

export type LogLevel = "info" | "warn" | "error" | "debug";

export interface LogEntry {
  id: string;
  timestamp: string;
  level: LogLevel;
  service: string;
  message: string;
}

export interface MetricPoint {
  time: string;
  cpu: number;
  ram: number;
  queriesPerSec: number;
  latencyMs: number;
}

export type FindingSeverity = "critical" | "high" | "medium" | "low";
export type FindingStatus = "open" | "investigating" | "resolved";

export interface Finding {
  id: string;
  title: string;
  description: string;
  severity: FindingSeverity;
  status: FindingStatus;
  source: string;
  detectedAt: string;
}

export interface CrawlJobResult {
  id: string;
  job: string;
  status: "pass" | "fail";
  duration: number;
  timestamp: string;
}

export interface User {
  email: string;
  name: string;
  role: "admin" | "analyst";
}
