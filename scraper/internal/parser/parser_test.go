package parser

import (
	"strings"
	"testing"

	"golang.org/x/text/encoding/charmap"

	"github.com/tekraj/pgs-search-engine/scraper/internal/simhash"
)

func TestParse_JSONLDAndGeo_NestedGeoCoordinatesWins(t *testing.T) {
	doc := `<html><head><title>Test Place</title>
<meta name="geo.position" content="1.0;2.0">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"LocalBusiness","name":"Foo","geo":{"@type":"GeoCoordinates","latitude":"40.7128","longitude":-74.0060}}
</script>
</head><body><p>Hello world</p><a href="/about">About</a></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}

	if p.Title != "Test Place" {
		t.Errorf("Title = %q, want %q", p.Title, "Test Place")
	}
	if len(p.Links) != 1 || p.Links[0] != "https://example.com/about" {
		t.Errorf("Links = %v, want [https://example.com/about]", p.Links)
	}
	if len(p.JSONLD) != 1 {
		t.Fatalf("JSONLD = %v, want 1 block", p.JSONLD)
	}
	if p.Geo == nil {
		t.Fatal("Geo = nil, want a GeoCoordinates match from JSON-LD")
	}
	// JSON-LD GeoCoordinates should win over the geo.position meta tag.
	if p.Geo.Lat != 40.7128 || p.Geo.Lng != -74.0060 {
		t.Errorf("Geo = %+v, want {40.7128 -74.0060}", p.Geo)
	}
}

func TestParse_Geo_FallsBackToMetaGeoPosition(t *testing.T) {
	doc := `<html><head><title>No JSON-LD</title>
<meta name="geo.position" content="37.7749;-122.4194">
</head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Geo == nil {
		t.Fatal("Geo = nil, want match from geo.position meta tag")
	}
	if p.Geo.Lat != 37.7749 || p.Geo.Lng != -122.4194 {
		t.Errorf("Geo = %+v, want {37.7749 -122.4194}", p.Geo)
	}
}

func TestParse_Geo_FallsBackToICBM(t *testing.T) {
	doc := `<html><head><meta name="ICBM" content="51.5074, -0.1278"></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Geo == nil {
		t.Fatal("Geo = nil, want match from ICBM meta tag")
	}
	if p.Geo.Lat != 51.5074 || p.Geo.Lng != -0.1278 {
		t.Errorf("Geo = %+v, want {51.5074 -0.1278}", p.Geo)
	}
}

func TestParse_Geo_FallsBackToOpenGraphPlace(t *testing.T) {
	doc := `<html><head>
<meta property="place:location:latitude" content="48.8566">
<meta property="place:location:longitude" content="2.3522">
</head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Geo == nil {
		t.Fatal("Geo = nil, want match from Open Graph place tags")
	}
	if p.Geo.Lat != 48.8566 || p.Geo.Lng != 2.3522 {
		t.Errorf("Geo = %+v, want {48.8566 2.3522}", p.Geo)
	}
}

func TestParse_NoGeoOrJSONLD(t *testing.T) {
	doc := `<html><head><title>Plain</title></head><body><p>Nothing here</p></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Geo != nil {
		t.Errorf("Geo = %+v, want nil", p.Geo)
	}
	if len(p.JSONLD) != 0 {
		t.Errorf("JSONLD = %v, want empty", p.JSONLD)
	}
}

func TestParse_AnchorText_CapturedAndParallelToLinks(t *testing.T) {
	doc := `<html><body>
<a href="/about"><b>About</b> Us</a>
<a href="/contact">Contact</a>
<a href="/no-text"></a>
</body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(p.Links) != len(p.AnchorTexts) {
		t.Fatalf("Links and AnchorTexts length mismatch: %d vs %d", len(p.Links), len(p.AnchorTexts))
	}
	want := map[string]string{
		"https://example.com/about":   "About Us",
		"https://example.com/contact": "Contact",
		"https://example.com/no-text": "",
	}
	for i, link := range p.Links {
		if got, ok := want[link]; !ok || got != p.AnchorTexts[i] {
			t.Errorf("link %s: anchor text = %q, want %q", link, p.AnchorTexts[i], want[link])
		}
	}
}

func TestParse_AnchorText_DedupeKeepsFirstOccurrence(t *testing.T) {
	doc := `<html><body>
<a href="/dup">First Text</a>
<a href="/dup">Second Text</a>
</body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(p.Links) != 1 {
		t.Fatalf("Links = %v, want 1 deduped URL", p.Links)
	}
	if p.AnchorTexts[0] != "First Text" {
		t.Errorf("AnchorTexts[0] = %q, want %q (first occurrence)", p.AnchorTexts[0], "First Text")
	}
}

func TestParse_Text_ExcludesStructuralBoilerplateButKeepsItsLinks(t *testing.T) {
	doc := `<html><body>
<nav><ul><li><a href="/a">Home</a></li><li><a href="/b">About</a></li></ul></nav>
<header><h1>Site Name</h1></header>
<article>
<p>This is the real article content that readers care about, explaining something in detail.</p>
</article>
<footer><p>Copyright 2024 Example Corp. All rights reserved.</p></footer>
<aside><p>Sidebar promo text unrelated to the article.</p></aside>
</body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}

	for _, excluded := range []string{"Home", "About", "Site Name", "Copyright 2024", "Sidebar promo"} {
		if strings.Contains(p.Text, excluded) {
			t.Errorf("Text = %q, should not contain boilerplate %q", p.Text, excluded)
		}
	}
	if !strings.Contains(p.Text, "real article content") {
		t.Errorf("Text = %q, should contain the article paragraph", p.Text)
	}

	// Links inside nav/footer/aside are still worth crawling even though
	// their text isn't article content.
	wantLinks := []string{"https://example.com/a", "https://example.com/b"}
	for _, link := range wantLinks {
		found := false
		for _, l := range p.Links {
			if l == link {
				found = true
			}
		}
		if !found {
			t.Errorf("Links = %v, want to include %q (nav links should still be crawled)", p.Links, link)
		}
	}
}

func TestParse_Text_DropsLinkDenseListButKeepsProseWithInlineLink(t *testing.T) {
	doc := `<html><body>
<ul>
<li><a href="/guide-one">Read our comprehensive guide to getting started with the product today</a></li>
<li><a href="/guide-two">Read our comprehensive guide to advanced product configuration options</a></li>
</ul>
<p>The team recommended reading the <a href="/policy">privacy policy</a> before signing up for the service.</p>
</body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}

	if strings.Contains(p.Text, "comprehensive guide") {
		t.Errorf("Text = %q, should drop the link-dense teaser list", p.Text)
	}
	if !strings.Contains(p.Text, "recommended reading") {
		t.Errorf("Text = %q, should keep the prose paragraph with its inline link", p.Text)
	}
	if !strings.Contains(p.Text, "privacy policy") {
		t.Errorf("Text = %q, an inline link's text within a low-link-density paragraph should be kept", p.Text)
	}

	// The teaser list's links are still discovered even though its text
	// was dropped as boilerplate.
	if len(p.Links) != 3 {
		t.Errorf("Links = %v, want 3 (2 teaser links + 1 inline policy link)", p.Links)
	}
}

func TestParse_CanonicalURL_ResolvedAndAbsolute(t *testing.T) {
	doc := `<html><head>
<link rel="canonical" href="/article">
</head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/article?utm_source=x", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.CanonicalURL != "https://example.com/article" {
		t.Errorf("CanonicalURL = %q, want %q", p.CanonicalURL, "https://example.com/article")
	}
}

func TestParse_CanonicalURL_AbsentWhenNoLinkTag(t *testing.T) {
	doc := `<html><head><title>No canonical</title></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.CanonicalURL != "" {
		t.Errorf("CanonicalURL = %q, want empty", p.CanonicalURL)
	}
}

func TestParse_CanonicalURL_IgnoresNonCanonicalRelAndTakesFirstMatch(t *testing.T) {
	doc := `<html><head>
<link rel="stylesheet" href="/style.css">
<link rel="alternate canonical" href="/first">
<link rel="canonical" href="/second">
</head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.CanonicalURL != "https://example.com/first" {
		t.Errorf("CanonicalURL = %q, want %q (first rel=canonical link wins)", p.CanonicalURL, "https://example.com/first")
	}
}

func TestParse_Charset_DecodesUsingContentTypeHeader(t *testing.T) {
	doc := `<html><head><title>Café</title></head><body><p>Résumé</p></body></html>`
	encoded, err := charmap.ISO8859_1.NewEncoder().Bytes([]byte(doc))
	if err != nil {
		t.Fatalf("encode fixture as ISO-8859-1: %v", err)
	}

	p, err := Parse(encoded, "https://example.com/", "text/html; charset=iso-8859-1")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Title != "Café" {
		t.Errorf("Title = %q, want %q (decoded from ISO-8859-1 per Content-Type header)", p.Title, "Café")
	}
	if !strings.Contains(p.Text, "Résumé") {
		t.Errorf("Text = %q, want to contain %q", p.Text, "Résumé")
	}
}

func TestParse_Charset_DecodesUsingMetaTagWhenNoHeader(t *testing.T) {
	doc := `<html><head><meta charset="iso-8859-1"><title>Café</title></head><body></body></html>`
	encoded, err := charmap.ISO8859_1.NewEncoder().Bytes([]byte(doc))
	if err != nil {
		t.Fatalf("encode fixture as ISO-8859-1: %v", err)
	}

	// No Content-Type header at all -- the parser must fall back to
	// sniffing the <meta charset> tag in the document itself.
	p, err := Parse(encoded, "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Title != "Café" {
		t.Errorf("Title = %q, want %q (decoded from <meta charset> sniffing)", p.Title, "Café")
	}
}

func TestParse_RobotsMeta_NoIndexNoFollow(t *testing.T) {
	doc := `<html><head><meta name="robots" content="noindex, nofollow"></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if !p.RobotsNoIndex || !p.RobotsNoFollow {
		t.Errorf("RobotsNoIndex=%v RobotsNoFollow=%v, want both true", p.RobotsNoIndex, p.RobotsNoFollow)
	}
}

func TestParse_RobotsMeta_NoIndexOnlyLeavesFollowUnset(t *testing.T) {
	doc := `<html><head><meta name="robots" content="noindex"></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if !p.RobotsNoIndex {
		t.Error("RobotsNoIndex = false, want true")
	}
	if p.RobotsNoFollow {
		t.Error("RobotsNoFollow = true, want false (noindex alone doesn't imply nofollow)")
	}
}

func TestParse_RobotsMeta_NoneMeansBoth(t *testing.T) {
	doc := `<html><head><meta name="robots" content="none"></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if !p.RobotsNoIndex || !p.RobotsNoFollow {
		t.Errorf("RobotsNoIndex=%v RobotsNoFollow=%v, want both true for content=\"none\"", p.RobotsNoIndex, p.RobotsNoFollow)
	}
}

func TestParse_RobotsMeta_AbsentLeavesBothFalse(t *testing.T) {
	doc := `<html><head><title>No robots meta</title></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.RobotsNoIndex || p.RobotsNoFollow {
		t.Errorf("RobotsNoIndex=%v RobotsNoFollow=%v, want both false with no robots meta tag", p.RobotsNoIndex, p.RobotsNoFollow)
	}
}

func TestParse_SimHash_NearDuplicatesAreClose(t *testing.T) {
	const shared = `<p>the quarterly earnings report released this morning showed the
company beat analyst expectations on both revenue and profit margins
the stock price rallied in early trading as investors reacted
positively to the strong guidance provided by the chief financial
officer during the call analysts noted that the growth was broad
based across all major product lines and geographic regions</p>`

	docA := "<html><body>" + shared + "<p>published 2024-01-01 10:00am</p></body></html>"
	docB := "<html><body>" + shared + "<p>published 2024-01-01 11:30am</p></body></html>"

	pa, err := Parse([]byte(docA), "https://example.com/a", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	pb, err := Parse([]byte(docB), "https://example.com/b", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}

	if pa.SimHash == 0 || pb.SimHash == 0 {
		t.Fatal("SimHash should be a non-zero fingerprint for non-empty text")
	}
	if d := simhash.HammingDistance(pa.SimHash, pb.SimHash); d > 3 {
		t.Errorf("Hamming distance = %d, want <= 3 for near-duplicate pages", d)
	}
}

func TestParseRobotsDirectives_UnrecognizedTokensIgnored(t *testing.T) {
	noindex, nofollow := ParseRobotsDirectives("noarchive, max-snippet:-1")
	if noindex || nofollow {
		t.Errorf("noindex=%v nofollow=%v, want both false for unrecognized directives", noindex, nofollow)
	}
}

func TestParse_InvalidJSONLDIsSkipped(t *testing.T) {
	doc := `<html><head><script type="application/ld+json">{not valid json</script></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(p.JSONLD) != 0 {
		t.Errorf("JSONLD = %v, want empty (invalid block should be dropped)", p.JSONLD)
	}
}

func TestParse_MetaDescription_FallsBackToOpenGraph(t *testing.T) {
	doc := `<html><head><title>T</title>
<meta property="og:description" content="  OG snippet   text  ">
</head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.MetaDescription != "OG snippet text" {
		t.Errorf("MetaDescription = %q, want %q", p.MetaDescription, "OG snippet text")
	}
}

func TestParse_MetaDescription_PrefersNameDescription(t *testing.T) {
	doc := `<html><head><title>T</title>
<meta name="description" content="Plain description">
<meta property="og:description" content="OG description">
</head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.MetaDescription != "Plain description" {
		t.Errorf("MetaDescription = %q, want %q", p.MetaDescription, "Plain description")
	}
}

func TestParse_Headings_CapturedInDocumentOrder(t *testing.T) {
	doc := `<html><head><title>T</title></head><body>
<h1>Main Title</h1>
<p>intro</p>
<h2>Section One</h2>
<h3>Sub Section</h3>
</body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	want := []struct {
		Level int
		Text  string
	}{
		{1, "Main Title"},
		{2, "Section One"},
		{3, "Sub Section"},
	}
	if len(p.Headings) != len(want) {
		t.Fatalf("Headings = %+v, want %d entries", p.Headings, len(want))
	}
	for i, w := range want {
		if p.Headings[i].Level != w.Level || p.Headings[i].Text != w.Text {
			t.Errorf("Headings[%d] = %+v, want {%d %q}", i, p.Headings[i], w.Level, w.Text)
		}
	}
}

func TestParse_Country_JSONLDAddressWinsOverCcTLD(t *testing.T) {
	doc := `<html><head><title>T</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","address":{"@type":"PostalAddress","addressCountry":"Nepal"}}
</script>
</head><body></body></html>`

	// Host ccTLD alone would say India; the explicit JSON-LD address should
	// win.
	p, err := Parse([]byte(doc), "https://example.co.in/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Country != "NP" {
		t.Errorf("Country = %q, want %q", p.Country, "NP")
	}
}

func TestParse_Country_FallsBackToCcTLD(t *testing.T) {
	doc := `<html><head><title>T</title></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com.np/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Country != "NP" {
		t.Errorf("Country = %q, want %q (ccTLD fallback)", p.Country, "NP")
	}
}

func TestParse_Country_UndetectedIsEmpty(t *testing.T) {
	doc := `<html><head><title>T</title></head><body></body></html>`

	p, err := Parse([]byte(doc), "https://example.com/", "")
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if p.Country != "" {
		t.Errorf("Country = %q, want empty (no signal on a plain .com page)", p.Country)
	}
}
