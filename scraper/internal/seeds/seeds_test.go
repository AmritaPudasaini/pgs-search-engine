package seeds

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestParseFile(t *testing.T) {
	content := `# comment
[news]
https://news-a.example
https://news-b.example

[tech]
https://tech-a.example

https://tech-b.example
`
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := ParseFile(path)
	if err != nil {
		t.Fatal(err)
	}

	want := []Seed{
		{URL: "https://news-a.example", Category: "news"},
		{URL: "https://news-b.example", Category: "news"},
		{URL: "https://tech-a.example", Category: "tech"},
		{URL: "https://tech-b.example", Category: "tech"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ParseFile = %+v, want %+v", got, want)
	}
}

func TestParseFilePriority(t *testing.T) {
	content := `[news 5]
https://news-a.example
https://news-b.example 20

[tech]
https://tech-a.example
`
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := ParseFile(path)
	if err != nil {
		t.Fatal(err)
	}

	want := []Seed{
		{URL: "https://news-a.example", Category: "news", Priority: 5},
		{URL: "https://news-b.example", Category: "news", Priority: 20},
		{URL: "https://tech-a.example", Category: "tech", Priority: DefaultPriority},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ParseFile = %+v, want %+v", got, want)
	}
}

func TestParseFileInvalidPriority(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte("https://a.example not-a-number\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := ParseFile(path); err == nil {
		t.Fatal("expected error for invalid priority")
	}
}

func TestParseFileInvalidCategoryPriority(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte("[tech not-a-number]\nhttps://a.example\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := ParseFile(path); err == nil {
		t.Fatal("expected error for invalid category priority")
	}
}

// TestParseFileMalformedSectionHeader_MissingClosingBracket proves a
// mistyped category header -- "[tech" without the closing "]" -- is
// rejected with a clear error rather than silently becoming a seed whose
// URL is the literal string "[tech" (which downstream, normalize.Canonical
// and the fetcher would each fail on in less obvious ways much later).
func TestParseFileMalformedSectionHeader_MissingClosingBracket(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte("[tech\nhttps://a.example\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := ParseFile(path); err == nil {
		t.Fatal("expected error for a category header missing its closing ']'")
	}
}

// TestParseFileDuplicateURLs_PassesThroughUndeduped documents (and locks
// in) that ParseFile intentionally does not deduplicate URLs -- even the
// exact same URL repeated verbatim comes back as two Seed entries.
// Deduplication is the crawl workflow's job (its `seen` map, keyed by
// normalize.Canonical), not the seed-file parser's: a URL repeated across
// two categories, for instance, is meaningful input (which category "wins"
// is decided by crawl order, not by this parser silently dropping one).
func TestParseFileDuplicateURLs_PassesThroughUndeduped(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	content := `[news]
https://a.example
https://a.example

[tech]
https://a.example
`
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := ParseFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Fatalf("ParseFile returned %d seeds, want 3 (duplicates are not deduplicated here)", len(got))
	}
	if got[0].Category != "news" || got[1].Category != "news" || got[2].Category != "tech" {
		t.Errorf("ParseFile = %+v, want the third occurrence under category %q", got, "tech")
	}
}

func TestParseFileUncategorized(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte("https://a.example\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := ParseFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Category != DefaultCategory {
		t.Fatalf("expected default category, got %+v", got)
	}
}

func TestParseFileEmpty(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "seeds.txt")
	if err := os.WriteFile(path, []byte("# only comments\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	if _, err := ParseFile(path); err == nil {
		t.Fatal("expected error for a seeds file with no URLs")
	}
}
