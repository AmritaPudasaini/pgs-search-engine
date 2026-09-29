package sitemap

import (
	"reflect"
	"testing"
)

func TestParseURLs_URLSet(t *testing.T) {
	body := `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>`

	pages, children, err := ParseURLs([]byte(body))
	if err != nil {
		t.Fatalf("ParseURLs: %v", err)
	}
	want := []string{"https://example.com/a", "https://example.com/b"}
	if !reflect.DeepEqual(pages, want) {
		t.Errorf("pages = %v, want %v", pages, want)
	}
	if len(children) != 0 {
		t.Errorf("children = %v, want none (this is a urlset, not a sitemapindex)", children)
	}
}

func TestParseURLs_SitemapIndex(t *testing.T) {
	body := `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-2.xml</loc></sitemap>
</sitemapindex>`

	pages, children, err := ParseURLs([]byte(body))
	if err != nil {
		t.Fatalf("ParseURLs: %v", err)
	}
	if len(pages) != 0 {
		t.Errorf("pages = %v, want none (this is a sitemapindex, not a urlset)", pages)
	}
	want := []string{"https://example.com/sitemap-1.xml", "https://example.com/sitemap-2.xml"}
	if !reflect.DeepEqual(children, want) {
		t.Errorf("children = %v, want %v", children, want)
	}
}

func TestParseURLs_InvalidXML(t *testing.T) {
	if _, _, err := ParseURLs([]byte("not xml at all")); err == nil {
		t.Error("expected an error for invalid XML, got nil")
	}
}

// TestParseURLs_UnrelatedXMLRootYieldsEmptyNotError proves DiscoverSitemapURLs'
// best-effort contract holds at this layer too: doc.XMLName has no fixed
// tag, so well-formed XML with a root element that isn't <urlset> or
// <sitemapindex> (e.g. a site misconfigured to serve an RSS feed, or any
// other XML document, at /sitemap.xml) must decode without error and yield
// no URLs -- not an error a caller would have to special-case.
func TestParseURLs_UnrelatedXMLRootYieldsEmptyNotError(t *testing.T) {
	body := `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Not a sitemap</title></channel></rss>`

	pages, children, err := ParseURLs([]byte(body))
	if err != nil {
		t.Fatalf("ParseURLs: %v, want nil (unrelated XML root should degrade to empty, not error)", err)
	}
	if len(pages) != 0 {
		t.Errorf("pages = %v, want none", pages)
	}
	if len(children) != 0 {
		t.Errorf("children = %v, want none", children)
	}
}

// TestParseURLs_EmptyURLSetYieldsEmptyNotError covers the degenerate but
// well-formed case: an empty <urlset/> with no <url> children at all.
func TestParseURLs_EmptyURLSetYieldsEmptyNotError(t *testing.T) {
	body := `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>`

	pages, children, err := ParseURLs([]byte(body))
	if err != nil {
		t.Fatalf("ParseURLs: %v, want nil", err)
	}
	if len(pages) != 0 || len(children) != 0 {
		t.Errorf("pages = %v, children = %v, want both empty", pages, children)
	}
}
