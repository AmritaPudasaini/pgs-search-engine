package render

import "testing"

func TestParseMode(t *testing.T) {
	for in, want := range map[string]Mode{"": ModeOff, "off": ModeOff, "AUTO": ModeAuto, " always ": ModeAlways} {
		got, err := ParseMode(in)
		if err != nil || got != want {
			t.Errorf("ParseMode(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	if _, err := ParseMode("sometimes"); err == nil {
		t.Error("want error for unknown mode")
	}
}

func TestNeedsRender(t *testing.T) {
	cases := []struct {
		name string
		html string
		text int
		want bool
	}{
		{"react shell", `<html><body><div id="root"></div><script src=a.js></script></body></html>`, 0, true},
		{"next shell", `<body><div id="__next"></div>`, 20, true},
		{"noscript hint", `<body><noscript>You need to enable JavaScript to run this app.</noscript></body>`, 10, true},
		{"script heavy empty", `<body><script></script><script></script><script></script></body>`, 5, true},
		{"normal article", `<body><div id="root"><p>lots of real prose</p></div></body>`, 4000, false},
		{"static page", `<body><h1>Hello</h1><p>text</p></body>`, 40, false},
	}
	for _, c := range cases {
		if got := NeedsRender(c.html, c.text) != ""; got != c.want {
			t.Errorf("%s: NeedsRender = %v, want %v", c.name, got, c.want)
		}
	}
}
