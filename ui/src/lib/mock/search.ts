import type { SearchResult } from "@/lib/types";

const NEPAL_PLACES = [
  "Kathmandu", "Pokhara", "Lalitpur", "Bhaktapur", "Chitwan", "Biratnagar",
  "Butwal", "Dharan", "Nepalgunj", "Hetauda", "Janakpur", "Dhangadhi",
  "Itahari", "Birgunj", "Bharatpur",
];

const DOMAINS = [
  "pgs.gov.np", "records.pgs.np", "survey.pgs.np", "docs.pgs.np",
  "open-data.pgs.np", "reports.pgs.np", "gis.pgs.np",
];

function seededRandom(seed: number) {
  let value = seed;
  return () => {
    value = (value * 9301 + 49297) % 233280;
    return value / 233280;
  };
}

function hashString(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash) || 1;
}

export function matchedPlace(query: string): string | null {
  const lower = query.toLowerCase();
  return NEPAL_PLACES.find((place) => lower.includes(place.toLowerCase())) ?? null;
}

export function generateMockResults(query: string, count = 8): SearchResult[] {
  const trimmed = query.trim();
  if (!trimmed) return [];

  const rand = seededRandom(hashString(trimmed));
  const place = matchedPlace(trimmed);

  const templates = [
    {
      title: `${trimmed} — Records overview | PGS Search`,
      snippet: `Browse indexed government and public records related to "${trimmed}", including geo-tagged locations, survey data, and cross-referenced documents.`,
    },
    {
      title: `${trimmed}: dataset index and metadata`,
      snippet: `Structured metadata, boundary references, and municipality-level breakdowns for "${trimmed}" collected across verified sources.`,
    },
    {
      title: `Latest filings mentioning "${trimmed}"`,
      snippet: `Recently indexed filings and reports referencing ${trimmed}, sorted by relevance and last-crawled timestamp.`,
    },
    {
      title: `${trimmed} — statistics and coverage map`,
      snippet: `Aggregated statistics for ${trimmed} with a linked coverage map showing district and ward-level tagging.`,
    },
    {
      title: `Frequently referenced: ${trimmed}`,
      snippet: `A curated list of documents, PDFs, and public notices that reference "${trimmed}" across the PGS index.`,
    },
  ];

  const results: SearchResult[] = Array.from({ length: count }).map((_, i) => {
    const template = templates[i % templates.length];
    const domain = DOMAINS[Math.floor(rand() * DOMAINS.length)];
    const slug = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
    return {
      id: `${slug || "result"}-${i}`,
      title: template.title,
      url: `https://${domain}/${slug || "search"}/${1000 + Math.floor(rand() * 8999)}`,
      domain,
      snippet: template.snippet,
      category: "web",
    };
  });

  if (place) {
    results.unshift({
      id: `place-${place.toLowerCase()}`,
      title: `${place} — Geo Explorer result`,
      url: `/map?focus=${encodeURIComponent(place)}`,
      domain: "map.pgs.np",
      snippet: `${place} is indexed in the PGS Geo Explorer with district boundaries and municipality-level tagging. Open the interactive map to inspect coverage.`,
      category: "place",
      district: place,
    });
  }

  return results;
}
