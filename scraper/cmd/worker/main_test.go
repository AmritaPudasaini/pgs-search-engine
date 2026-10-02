package main

import "testing"

func TestOrdinalFromHostname(t *testing.T) {
	cases := []struct {
		host   string
		shards int
		want   int
	}{
		{"worker-0", 4, 0},
		{"worker-3", 4, 3},
		{"worker-6", 4, 2}, // wraps modulo shards
		{"worker-12", 5, 2},
		{"worker", 4, -1},
		{"worker-", 4, -1},
		{"worker-1", 0, -1},
	}
	for _, c := range cases {
		if got := ordinalFromHostname(c.host, c.shards); got != c.want {
			t.Errorf("ordinalFromHostname(%q, %d) = %d, want %d", c.host, c.shards, got, c.want)
		}
	}
}
