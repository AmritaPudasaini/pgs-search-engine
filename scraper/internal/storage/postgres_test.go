package storage

import (
	"reflect"
	"testing"
)

// TestNonNilStrings guards a real bug found by running a live crawl against
// Postgres: a nil Go slice sent to pgx for a TEXT[] parameter becomes SQL
// NULL, which violates documents' NOT NULL DEFAULT '{}' array columns
// (links, json_ld, anchor_texts) whenever a page has none of that content --
// an ordinary, common case, not an edge case.
func TestNonNilStrings(t *testing.T) {
	if got := nonNilStrings(nil); !reflect.DeepEqual(got, []string{}) {
		t.Errorf("nonNilStrings(nil) = %#v, want []string{}", got)
	}
	if got := nonNilStrings([]string{}); !reflect.DeepEqual(got, []string{}) {
		t.Errorf("nonNilStrings([]string{}) = %#v, want []string{}", got)
	}
	want := []string{"a", "b"}
	if got := nonNilStrings(want); !reflect.DeepEqual(got, want) {
		t.Errorf("nonNilStrings(%#v) = %#v, want unchanged", want, got)
	}
}
