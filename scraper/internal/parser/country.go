package parser

import (
	"encoding/json"
	"strings"
)

// countryNameToCode maps the country-name spellings JSON-LD addresses
// commonly use (schema.org's addressCountry accepts either an ISO code or a
// plain name) to ISO 3166-1 alpha-2. Not exhaustive -- it covers the names
// likely to actually appear on South Asian sites plus a handful of large
// neighbors, since that's this crawler's current focus (see DetectCountry).
// Extend as new source countries matter.
var countryNameToCode = map[string]string{
	"nepal":          "NP",
	"india":          "IN",
	"bhutan":         "BT",
	"bangladesh":     "BD",
	"pakistan":       "PK",
	"china":          "CN",
	"sri lanka":      "LK",
	"united states":  "US",
	"united kingdom": "GB",
}

// ccTLDToCountry maps a handful of country-code TLDs to ISO 3166-1 alpha-2.
// This is the fallback signal used when nothing on the page itself declares
// a country -- reliable for ccTLD-registered sites (most .com.np/.np,
// .co.in/.in sites genuinely are hosted for that country) but absent for
// generic .com/.org sites, which is why it's tried last.
var ccTLDToCountry = map[string]string{
	"np": "NP",
	"in": "IN",
	"bt": "BT",
	"bd": "BD",
	"pk": "PK",
	"cn": "CN",
	"lk": "LK",
	"uk": "GB",
	"us": "US",
}

// langToCountry maps a bare (regionless) BCP-47 primary language subtag to
// the country it's the de-facto national/primary language of, for languages
// where that association is strong enough to be a useful heuristic. "ne"
// (Nepali) is the motivating case: near all Nepali-language content is
// Nepal-origin, unlike e.g. "hi" (Hindi) or "en", which are each spoken
// natively across many countries and would be a false signal.
var langToCountry = map[string]string{
	"ne": "NP",
}

// normalizeCountry accepts a raw country token (an ISO alpha-2 code already,
// or a plain English name as schema.org addressCountry/og:locale territory
// subtags use) and returns its ISO 3166-1 alpha-2 code, or "" if it isn't
// recognized.
func normalizeCountry(raw string) string {
	s := strings.TrimSpace(raw)
	if len(s) == 2 {
		return strings.ToUpper(s)
	}
	if code, ok := countryNameToCode[strings.ToLower(s)]; ok {
		return code
	}
	return ""
}

// DetectCountry resolves a page's best-guess origin country from whichever
// signal is available, checked in priority order (most deliberate/explicit
// first, cheapest-but-noisiest last):
//
//  1. JSON-LD PostalAddress.addressCountry -- a site explicitly declaring
//     its own address is the strongest signal available.
//  2. og:locale's territory subtag (e.g. "ne_NP" -> NP).
//  3. geo.region meta content (e.g. "NP" or "NP-BA" -> NP).
//  4. <html lang> -- a region subtag if present (e.g. "en-NP" -> NP),
//     otherwise the bare language via langToCountry (e.g. "ne" -> NP).
//  5. The page's host ccTLD (e.g. example.com.np -> NP).
//
// Returns "" if none of these yielded a recognized country.
func DetectCountry(host, htmlLang, geoRegion, ogLocale string, jsonld []string) string {
	if c := addressCountryFromJSONLD(jsonld); c != "" {
		return c
	}
	if c := countryFromLocale(ogLocale); c != "" {
		return c
	}
	if geoRegion != "" {
		region := geoRegion
		if i := strings.IndexAny(region, "-_"); i > 0 {
			region = region[:i]
		}
		if c := normalizeCountry(region); c != "" {
			return c
		}
	}
	if c := countryFromLocale(htmlLang); c != "" {
		return c
	}
	if htmlLang != "" {
		base := strings.ToLower(strings.SplitN(htmlLang, "-", 2)[0])
		if c, ok := langToCountry[base]; ok {
			return c
		}
	}
	if host != "" {
		labels := strings.Split(strings.TrimSuffix(host, "."), ".")
		tld := strings.ToLower(labels[len(labels)-1])
		if c, ok := ccTLDToCountry[tld]; ok {
			return c
		}
	}
	return ""
}

// countryFromLocale extracts a region subtag from a BCP-47-ish locale value
// ("ne_NP", "en-NP") and normalizes it, or "" if the value has no region
// part or that part isn't a recognized country.
func countryFromLocale(locale string) string {
	if locale == "" {
		return ""
	}
	parts := strings.FieldsFunc(locale, func(r rune) bool { return r == '-' || r == '_' })
	if len(parts) < 2 {
		return ""
	}
	return normalizeCountry(parts[len(parts)-1])
}

// addressCountryFromJSONLD searches each JSON-LD block for a PostalAddress
// (top-level or nested under e.g. Organization/LocalBusiness.address) and
// returns its addressCountry, normalized to an ISO code.
func addressCountryFromJSONLD(blocks []string) string {
	for _, raw := range blocks {
		var v interface{}
		if err := json.Unmarshal([]byte(raw), &v); err != nil {
			continue
		}
		if c := findAddressCountry(v); c != "" {
			return c
		}
	}
	return ""
}

func findAddressCountry(v interface{}) string {
	switch val := v.(type) {
	case map[string]interface{}:
		if raw, ok := val["addressCountry"]; ok {
			switch ac := raw.(type) {
			case string:
				if c := normalizeCountry(ac); c != "" {
					return c
				}
			case map[string]interface{}:
				if name, ok := ac["name"].(string); ok {
					if c := normalizeCountry(name); c != "" {
						return c
					}
				}
			}
		}
		for _, child := range val {
			if c := findAddressCountry(child); c != "" {
				return c
			}
		}
	case []interface{}:
		for _, child := range val {
			if c := findAddressCountry(child); c != "" {
				return c
			}
		}
	}
	return ""
}
