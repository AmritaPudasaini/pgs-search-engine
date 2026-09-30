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
