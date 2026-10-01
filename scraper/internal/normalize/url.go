// Package normalize provides URL normalization and resolution helpers used
// to dedupe the crawl frontier and keep link graphs consistent.
package normalize

import (
	"net/url"
	"sort"
	"strings"
)

// Resolve turns a possibly-relative href found on base into an absolute URL.
// Returns ok=false for hrefs that aren't crawlable (mailto:, javascript:, #anchors, etc).
func Resolve(base *url.URL, href string) (string, bool) {
	href = strings.TrimSpace(href)
	if href == "" || strings.HasPrefix(href, "#") {
		return "", false
	}
	switch {
	case strings.HasPrefix(href, "mailto:"),
		strings.HasPrefix(href, "tel:"),
		strings.HasPrefix(href, "javascript:"),
		strings.HasPrefix(href, "data:"):
		return "", false
	}
	ref, err := url.Parse(href)
	if err != nil {
		return "", false
	}
	resolved := base.ResolveReference(ref)
	if resolved.Scheme != "http" && resolved.Scheme != "https" {
		return "", false
	}
	return Canonical(resolved.String()), true
}

// Canonical produces a stable dedupe key for a URL: lowercases host, strips
// the fragment, drops default ports, sorts query params, and removes a
// trailing slash on the path (except root).
func Canonical(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	u.Fragment = ""
	u.Host = strings.ToLower(u.Host)
	u.Host = strings.TrimSuffix(u.Host, ":80")
	u.Host = strings.TrimSuffix(u.Host, ":443")

	if u.Path == "" {
		u.Path = "/"
	}
	if len(u.Path) > 1 && strings.HasSuffix(u.Path, "/") {
		u.Path = strings.TrimSuffix(u.Path, "/")
	}

	if q := u.Query(); len(q) > 0 {
		keys := make([]string, 0, len(q))
		for k := range q {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		vals := url.Values{}
		for _, k := range keys {
			vals[k] = q[k]
		}
		u.RawQuery = vals.Encode()
	}

	return u.String()
}

// SameHost reports whether two absolute URLs share a host (used for
// same-domain crawl scoping).
func SameHost(a, b string) bool {
	ua, err1 := url.Parse(a)
	ub, err2 := url.Parse(b)
	if err1 != nil || err2 != nil {
		return false
	}
	return strings.EqualFold(ua.Hostname(), ub.Hostname())
}

// Hostname extracts the lowercase hostname from a URL, or "" if it can't be
// parsed. Used to scope a discovered link back to the seed it descended
// from, so a multi-seed crawl can keep each seed's branch on-site
// independently rather than comparing every link against a single seed.
func Hostname(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return ""
	}
	return strings.ToLower(u.Hostname())
}
