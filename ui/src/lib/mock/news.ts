export interface NewsItem {
  id: string;
  title: string;
  source: string;
  publishedAt: string;
  snippet: string;
  url: string;
}

const SOURCES = ["Kathmandu Post", "Setopati", "Rising Nepal", "PGS Wire", "Himal Khabar", "Nepal Today"];

const HEADLINE_TEMPLATES = [
  (place: string) => `${place} local unit approves new infrastructure budget for next fiscal year`,
  (place: string) => `Survey team completes ward-boundary verification in ${place}`,
  (place: string) => `${place} reports rise in agricultural exports this quarter`,
  (place: string) => `Road expansion project in ${place} enters second phase`,
  (place: string) => `${place} residents raise concerns over drinking water supply`,
  (place: string) => `PGS index adds 340 new public records for ${place}`,
  (place: string) => `${place} schools receive digital learning grant`,
  (place: string) => `Weather advisory issued for ${place} and surrounding areas`,
];

const SNIPPET_TEMPLATES = [
  (place: string) => `Officials in ${place} confirmed the plan during a public hearing held earlier this week, citing community feedback as the main driver.`,
  (place: string) => `The update follows a routine field survey conducted across ${place}'s wards, with results now indexed in the PGS registry.`,
  (place: string) => `Local representatives say the initiative is part of a broader push to modernize public services across ${place}.`,
  (place: string) => `Residents of ${place} can expect updated records to reflect these changes within the next indexing cycle.`,
];

function hashString(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash) || 1;
}

function seededRandom(seed: number) {
  let value = seed;
  return () => {
    value = (value * 9301 + 49297) % 233280;
    return value / 233280;
  };
}

const HOURS_AGO = [1, 2, 4, 6, 9, 14, 22, 30, 48];

export function generateMockNews(place: string, count = 5): NewsItem[] {
  const rand = seededRandom(hashString(place));
  const slug = place.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

  return Array.from({ length: count }).map((_, i) => {
    const headline = HEADLINE_TEMPLATES[Math.floor(rand() * HEADLINE_TEMPLATES.length)](place);
    const snippet = SNIPPET_TEMPLATES[Math.floor(rand() * SNIPPET_TEMPLATES.length)](place);
    const hoursAgo = HOURS_AGO[Math.floor(rand() * HOURS_AGO.length)];
    return {
      id: `${slug}-news-${i}`,
      title: headline,
      source: SOURCES[Math.floor(rand() * SOURCES.length)],
      publishedAt: hoursAgo < 24 ? `${hoursAgo}h ago` : `${Math.round(hoursAgo / 24)}d ago`,
      snippet,
      url: `https://news.pgs.np/${slug}/${1000 + Math.floor(rand() * 8999)}`,
    };
  });
}
