package normalize

import (
	"net/url"
	"testing"
)

func TestCanonical(t *testing.T) {
	cases := map[string]string{
		"https://Example.com":           "https://example.com/",
		"https://example.com/":          "https://example.com/",
		"https://example.com":           "https://example.com/",
		"https://example.com:443/a/":    "https://example.com/a",
		"https://example.com/a?b=2&a=1": "https://example.com/a?a=1&b=2",
		"https://example.com/page#frag": "https://example.com/page",
	}
	for in, want := range cases {
		if got := Canonical(in); got != want {
			t.Errorf("Canonical(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestResolve(t *testing.T) {
	base := mustParse(t, "https://example.com/dir/page.html")

	if _, ok := Resolve(base, "#top"); ok {
		t.Error("expected fragment-only href to be rejected")
	}
	if _, ok := Resolve(base, "mailto:a@b.com"); ok {
		t.Error("expected mailto href to be rejected")
	}
	got, ok := Resolve(base, "../other")
	if !ok {
		t.Fatal("expected relative href to resolve")
	}
	want := "https://example.com/other"
	if got != want {
		t.Errorf("Resolve = %q, want %q", got, want)
	}
}

func TestSameHost(t *testing.T) {
	if !SameHost("https://example.com/a", "https://EXAMPLE.com/b") {
		t.Error("expected case-insensitive host match")
	}
	if SameHost("https://example.com", "https://other.com") {
		t.Error("expected different hosts to not match")
	}
}

func mustParse(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return u
}
