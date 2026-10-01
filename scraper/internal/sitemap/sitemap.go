// Package sitemap parses sitemap.xml documents: both a plain urlset (a
// list of page URLs) and a sitemapindex (a list of other sitemap URLs to
// fetch and parse in turn) -- the two document shapes defined by the
// sitemaps.org protocol.
package sitemap

import "encoding/xml"

// doc matches either document shape. XMLName has no explicit tag, so
// encoding/xml doesn't require the root element's name to match anything in
// particular -- it just records whatever the root was and populates
// whichever nested path (url>loc for a urlset, sitemap>loc for a
// sitemapindex) exists in the document. Exactly one of URLLocs/IndexLocs is
// non-empty for any well-formed sitemap document.
type doc struct {
	XMLName   xml.Name
	URLLocs   []string `xml:"url>loc"`
	IndexLocs []string `xml:"sitemap>loc"`
}

// ParseURLs parses a sitemap.xml document, returning page URLs (from a
// urlset) and/or child sitemap URLs (from a sitemapindex) it declares.
func ParseURLs(body []byte) (pageURLs []string, childSitemaps []string, err error) {
	var d doc
	if err := xml.Unmarshal(body, &d); err != nil {
		return nil, nil, err
	}
	return d.URLLocs, d.IndexLocs, nil
}
