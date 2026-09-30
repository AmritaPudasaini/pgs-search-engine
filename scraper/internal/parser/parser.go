// Package parser extracts structured data (title, visible text, outbound
// links) from raw HTML using a proper tokenizer, so downstream ETL/indexing
// gets clean fields instead of markup.
package parser

import (
	"bytes"
	"encoding/json"
	"net/url"
	"strconv"
	"strings"

	"golang.org/x/net/html"
	"golang.org/x/net/html/charset"

	"search-engine-scraper/internal/model"
	"search-engine-scraper/internal/normalize"
	"search-engine-scraper/internal/simhash"
)

// Parsed holds the extracted fields for one page.
type Parsed struct {
	Title string
	// MetaDescription is <meta name="description"> content, falling back to
	// og:description if the page only declares that.
	MetaDescription string
	Text            string
	// Headings is the page's h1-h6 outline, in document order.
	Headings []model.Heading
	Links    []string // absolute, canonicalized, deduped
	// AnchorTexts is parallel to Links (same index, same length): the
	// visible text of the first <a> tag seen for each URL, collapsed to a
	// single line. Empty string for links with no text (image-only
	// anchors, etc). Kept as a separate slice rather than a []Link struct
	// so Links stays a plain URL list for existing consumers (frontier
	// queue, DB link column) that don't care about anchor text.
	AnchorTexts []string

	// JSONLD holds the raw text of each <script type="application/ld+json">
	// block that parses as valid JSON, in document order.
	JSONLD []string
	// Geo is the page's resolved geo-spatial location, or nil if none of
	// the sources checked (JSON-LD, Open Graph place tags, geo.position,
	// ICBM) yielded coordinates.
	Geo *model.GeoPoint

	// CanonicalURL is the page's declared <link rel="canonical" href="...">
	// target, absolute and canonicalized, or "" if the page doesn't declare
	// one. When set, callers should treat it (not the fetched URL) as the
	// page's dedupe identity -- the whole point of rel=canonical is that
	// the same content is reachable at multiple URLs (tracking params, AMP
	// variants, etc) and the page itself is telling the crawler which one
	// is authoritative.
	CanonicalURL string

	// RobotsNoIndex is true when <meta name="robots" content="..."> (or a
	// combined directive like "none") declares "noindex": the page asked
	// not to be stored/indexed. RobotsNoFollow is true when it declares
	// "nofollow": the page asked not to have its outbound links followed.
	// These are independent -- a page can be noindex but still followable,
	// or indexable but nofollow -- so callers must check both, not just one.
	// The X-Robots-Tag HTTP header is an equivalent, header-based way to
	// declare the same thing; since it's not part of the HTML body it isn't
	// captured here (see ParseRobotsDirectives, exported so callers with
	// access to response headers can parse it with the same logic).
	RobotsNoIndex  bool
	RobotsNoFollow bool

	// SimHash is a 64-bit near-duplicate fingerprint of Text (see
	// internal/simhash) -- computed from the full extracted text, before
	// any downstream truncation, so two pages differing only by a
	// timestamp/ad-slot/view-counter still produce fingerprints a few bits
	// apart instead of the completely unrelated digests a cryptographic
	// content hash would give them.
	SimHash uint64

	// Country is the page's best-guess origin country (ISO 3166-1 alpha-2),
	// or "" if no signal resolved one. See DetectCountry.
	Country string
}

// skipTextTags never contribute to the visible-text field, and their
// content isn't real page content in the first place (markup/script, not
// prose).
var skipTextTags = map[string]bool{
	"script": true, "style": true, "noscript": true, "svg": true, "template": true,
}

// boilerplateTags are structural chrome, not article content: site
// navigation, page header/footer, sidebars, and forms. Their text is
// excluded from Text, but NOT from Links/AnchorTexts -- a nav menu's links
// are still legitimate pages to crawl, only their text shouldn't dilute the
// main content signal.
var boilerplateTags = map[string]bool{
	"nav": true, "header": true, "footer": true, "aside": true, "form": true,
}

// blockTags are the granularity at which the link-density check (see
// extractMainText) runs: elements that normally hold one discrete unit of
// prose or a single table/list cell. A block whose text is mostly link text
// reads as a menu/teaser-list item rather than article content, even when
// it isn't wrapped in a semantic nav/aside tag.
var blockTags = map[string]bool{
	"p": true, "li": true, "dd": true, "td": true, "th": true,
	"blockquote": true, "figcaption": true,
	"h1": true, "h2": true, "h3": true, "h4": true, "h5": true, "h6": true,
}

const (
	// linkDensityThreshold: a block whose text is at least this fraction
	// link text (by character count) is dropped as boilerplate (nav-like
	// lists, "related articles" teasers, etc). 0.6 is deliberately
	// conservative -- a paragraph with one or two inline links has much
	// lower density than this and is kept.
	linkDensityThreshold = 0.6
	// minBlockCharsForDensityCheck avoids misjudging very short blocks
	// (e.g. a 3-character block that's entirely a link) where a handful of
	// characters isn't a meaningful sample.
	minBlockCharsForDensityCheck = 20
)

// Parse walks the HTML document rooted at body, resolving links against
// baseURL. contentType is the HTTP response's raw Content-Type header value
// (may be "" or lack a charset param) -- used, together with sniffing a BOM
// or a <meta charset>/<meta http-equiv> tag in the first 1024 bytes of body
// itself, to transcode non-UTF-8 pages before parsing (see
// golang.org/x/net/html/charset.DetermineEncoding for the exact precedence).
// Without this, a non-UTF-8 page would parse "successfully" but produce
// garbled Title/Text -- wrong data with no error to flag it.
func Parse(body []byte, baseURL string, contentType string) (*Parsed, error) {
	base, err := url.Parse(baseURL)
	if err != nil {
		return nil, err
	}

	utf8Body, err := charset.NewReader(bytes.NewReader(body), contentType)
	if err != nil {
		// Only fails on a genuine read error, which an in-memory
		// bytes.Reader never produces; fall back to the raw bytes so a
		// theoretical failure here doesn't lose the whole page.
		utf8Body = bytes.NewReader(body)
	}

	doc, err := html.Parse(utf8Body)
	if err != nil {
		return nil, err
	}

	p := &Parsed{}
	seenLinks := make(map[string]bool)
	inTitle := false

	// Geo candidates gathered from <meta> tags, resolved by priority (after
	// JSON-LD, which is checked separately) once the walk finishes.
	var geoPosition, icbm, ogLat, ogLng string
	// Country-detection candidates -- resolved by DetectCountry once the
	// walk finishes and every JSON-LD block has been collected.
	var htmlLang, geoRegion, ogLocale, ogDescription string

	var walk func(*html.Node)
	walk = func(n *html.Node) {
		switch n.Type {
		case html.ElementNode:
			switch n.Data {
			case "title":
				inTitle = true
				defer func() { inTitle = false }()
			case "html":
				for _, attr := range n.Attr {
					if strings.EqualFold(attr.Key, "lang") && attr.Val != "" {
						htmlLang = attr.Val
					}
				}
			case "h1", "h2", "h3", "h4", "h5", "h6":
				if text := collapseWhitespace(nodeText(n)); text != "" {
					level := int(n.Data[1] - '0')
					p.Headings = append(p.Headings, model.Heading{Level: level, Text: text})
				}
			case "a":
				for _, attr := range n.Attr {
					if attr.Key == "href" {
						if abs, ok := normalize.Resolve(base, attr.Val); ok {
							if !seenLinks[abs] {
								seenLinks[abs] = true
								p.Links = append(p.Links, abs)
								p.AnchorTexts = append(p.AnchorTexts, collapseWhitespace(nodeText(n)))
							}
						}
					}
				}
			case "script":
				if isJSONLD(n) {
					if raw := strings.TrimSpace(nodeText(n)); raw != "" && json.Valid([]byte(raw)) {
						p.JSONLD = append(p.JSONLD, raw)
					}
				}
			case "meta":
				name, property, content := metaAttrs(n)
				switch {
				case name == "robots":
					noindex, nofollow := ParseRobotsDirectives(content)
					p.RobotsNoIndex = p.RobotsNoIndex || noindex
					p.RobotsNoFollow = p.RobotsNoFollow || nofollow
				case name == "geo.position":
					geoPosition = content
				case name == "icbm":
					icbm = content
				case name == "geo.region":
					geoRegion = content
				case name == "description" && p.MetaDescription == "":
					p.MetaDescription = collapseWhitespace(content)
				case property == "og:description" && ogDescription == "":
					ogDescription = collapseWhitespace(content)
				case property == "og:locale":
					ogLocale = content
				case property == "place:location:latitude", property == "og:latitude":
					ogLat = content
				case property == "place:location:longitude", property == "og:longitude":
					ogLng = content
				}
			case "link":
				if p.CanonicalURL == "" {
					rel, href := linkAttrs(n)
					if href != "" && hasRelToken(rel, "canonical") {
						if abs, ok := normalize.Resolve(base, href); ok {
							p.CanonicalURL = abs
						}
					}
				}
			}
		case html.TextNode:
			if inTitle {
				if text := strings.TrimSpace(n.Data); text != "" {
					p.Title = text
				}
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			walk(c)
		}
	}
	walk(doc)

	text, _ := extractMainText(doc)
	p.Text = collapseWhitespace(text)
	p.SimHash = simhash.Fingerprint(p.Text)

	if p.MetaDescription == "" {
		p.MetaDescription = ogDescription
	}

	p.Country = DetectCountry(base.Hostname(), htmlLang, geoRegion, ogLocale, p.JSONLD)

	// Resolution priority: structured JSON-LD GeoCoordinates first (most
	// reliable/unambiguous), then Open Graph place tags, then the older
	// geo.position/ICBM meta conventions.
	switch jsonLDGeo := geoFromJSONLD(p.JSONLD); {
	case jsonLDGeo != nil:
		p.Geo = jsonLDGeo
	case ogLat != "" && ogLng != "":
		p.Geo = parseLatLng(ogLat, ogLng)
	case geoPosition != "":
		p.Geo = parseDelimited(geoPosition)
	case icbm != "":
		p.Geo = parseDelimited(icbm)
	}

	return p, nil
}

// isJSONLD reports whether script element n declares
// type="application/ld+json".
func isJSONLD(n *html.Node) bool {
	for _, attr := range n.Attr {
		if strings.EqualFold(attr.Key, "type") && strings.EqualFold(strings.TrimSpace(attr.Val), "application/ld+json") {
			return true
		}
	}
	return false
}

// ParseRobotsDirectives interprets a comma/space-separated robots directive
// list -- the value of either <meta name="robots" content="..."> or the
// X-Robots-Tag HTTP header -- into the two directives this crawler acts on.
// "none" is shorthand for both noindex and nofollow. Unrecognized tokens
// (e.g. "noarchive", "unavailable_after: ...") are ignored rather than
// erroring, since this crawler only needs to decide whether to store a page
// and whether to follow its links.
func ParseRobotsDirectives(content string) (noindex, nofollow bool) {
	for _, tok := range strings.FieldsFunc(content, func(r rune) bool {
		return r == ',' || r == ' ' || r == '\t'
	}) {
		switch strings.ToLower(strings.TrimSpace(tok)) {
		case "noindex":
			noindex = true
		case "nofollow":
			nofollow = true
		case "none":
			noindex = true
			nofollow = true
		}
	}
	return
}

// metaAttrs extracts a <meta> tag's name, property, and content attributes
// (name/property lowercased for case-insensitive matching).
func metaAttrs(n *html.Node) (name, property, content string) {
	for _, attr := range n.Attr {
		switch strings.ToLower(attr.Key) {
		case "name":
			name = strings.ToLower(strings.TrimSpace(attr.Val))
		case "property":
			property = strings.ToLower(strings.TrimSpace(attr.Val))
		case "content":
			content = attr.Val
		}
	}
	return
}

// extractMainText walks n bottom-up, returning its visible text plus how
// many of those characters came from inside an <a> tag. Two boilerplate
// filters apply, both excluding text only (never the links/anchor text
// captured separately by Parse's top-down walk, since a nav menu's links
// are still worth crawling even though its text isn't article content):
//
//  1. skipTextTags/boilerplateTags: script/style/nav/header/footer/aside/
//     form subtrees contribute no text at all.
//  2. Link density: a blockTags element (p, li, td, heading, ...) whose
//     text is mostly link characters -- a "Read more" teaser list, a menu
//     rendered as plain <li> without a wrapping <nav>, etc -- is dropped as
//     boilerplate even though it isn't inside a semantic chrome tag.
func extractMainText(n *html.Node) (text string, linkChars int) {
	switch n.Type {
	case html.TextNode:
		t := strings.TrimSpace(n.Data)
		if t == "" {
			return "", 0
		}
		return t + " ", 0
	case html.ElementNode:
		if skipTextTags[n.Data] || boilerplateTags[n.Data] {
			return "", 0
		}
	case html.DocumentNode:
		// The tree root: no text/tag of its own, just recurse into children.
	default:
		return "", 0
	}

	var buf strings.Builder
	var childLinkChars int
	for c := n.FirstChild; c != nil; c = c.NextSibling {
		t, l := extractMainText(c)
		buf.WriteString(t)
		childLinkChars += l
	}
	combined := buf.String()

	linkChars = childLinkChars
	if n.Data == "a" {
		linkChars = len(combined)
	}

	if blockTags[n.Data] && len(combined) >= minBlockCharsForDensityCheck {
		if float64(linkChars)/float64(len(combined)) >= linkDensityThreshold {
			return "", linkChars
		}
	}
	return combined, linkChars
}

// linkAttrs extracts a <link> tag's rel and href attributes (rel lowercased
// for case-insensitive token matching).
func linkAttrs(n *html.Node) (rel, href string) {
	for _, attr := range n.Attr {
		switch strings.ToLower(attr.Key) {
		case "rel":
			rel = strings.ToLower(strings.TrimSpace(attr.Val))
		case "href":
			href = attr.Val
		}
	}
	return
}

// hasRelToken reports whether token appears among rel's space-separated
// values (rel is itself space-separated per the HTML spec, e.g.
// rel="alternate canonical" is valid though rare in practice).
func hasRelToken(rel, token string) bool {
	for _, f := range strings.Fields(rel) {
		if f == token {
			return true
		}
	}
	return false
}

// nodeText concatenates all text-node descendants of n (script elements
// have raw-text content, so this is normally just n's single text child).
func nodeText(n *html.Node) string {
	var sb strings.Builder
	var walk func(*html.Node)
	walk = func(n *html.Node) {
		if n.Type == html.TextNode {
			sb.WriteString(n.Data)
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			walk(c)
		}
	}
	walk(n)
	return sb.String()
}

// geoFromJSONLD searches each JSON-LD block for a schema.org GeoCoordinates
// object (either a top-level entity or nested under a "geo" property, e.g.
// on a Place/LocalBusiness/Event) and returns the first one found.
func geoFromJSONLD(blocks []string) *model.GeoPoint {
	for _, raw := range blocks {
		var v interface{}
		if err := json.Unmarshal([]byte(raw), &v); err != nil {
			continue
		}
		if g := findGeoCoordinates(v); g != nil {
			return g
		}
	}
	return nil
}

// findGeoCoordinates recursively walks a decoded JSON-LD value looking for
// an object with "@type": "GeoCoordinates" and numeric latitude/longitude.
func findGeoCoordinates(v interface{}) *model.GeoPoint {
	switch val := v.(type) {
	case map[string]interface{}:
		if t, ok := val["@type"].(string); ok && strings.EqualFold(t, "GeoCoordinates") {
			lat, latOK := toFloat(val["latitude"])
			lng, lngOK := toFloat(val["longitude"])
			if latOK && lngOK {
				return &model.GeoPoint{Lat: lat, Lng: lng}
			}
		}
		for _, child := range val {
			if g := findGeoCoordinates(child); g != nil {
				return g
			}
		}
	case []interface{}:
		for _, child := range val {
			if g := findGeoCoordinates(child); g != nil {
				return g
			}
		}
	}
	return nil
}

// toFloat accepts JSON-LD latitude/longitude values encoded as either a
// JSON number or a numeric string (both appear in the wild).
func toFloat(v interface{}) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(n), 64)
		return f, err == nil
	default:
		return 0, false
	}
}

// parseLatLng parses two separate numeric strings, as used by Open
// Graph/place meta tags.
func parseLatLng(latStr, lngStr string) *model.GeoPoint {
	lat, err1 := strconv.ParseFloat(strings.TrimSpace(latStr), 64)
	lng, err2 := strconv.ParseFloat(strings.TrimSpace(lngStr), 64)
	if err1 != nil || err2 != nil {
		return nil
	}
	return &model.GeoPoint{Lat: lat, Lng: lng}
}

// parseDelimited parses "lat;lon" (geo.position) or "lat, lon" (ICBM) style
// meta content into a GeoPoint.
func parseDelimited(s string) *model.GeoPoint {
	s = strings.ReplaceAll(s, ";", ",")
	parts := strings.Split(s, ",")
	if len(parts) != 2 {
		return nil
	}
	return parseLatLng(parts[0], parts[1])
}

func collapseWhitespace(s string) string {
	fields := strings.Fields(s)
	return strings.Join(fields, " ")
}
