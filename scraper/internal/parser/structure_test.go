package parser

import "testing"

const structureFixture = `<!doctype html><html lang="ne"><head>
<meta charset="utf-8"><title>Ward Office</title>
<meta name="viewport" content="width=device-width">
<meta name="description" content="Official ward office">
<meta property="og:title" content="Ward">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="/ward"><link rel="stylesheet" href="/s.css">
<script src="/app.js" defer></script><script>var x=1;</script>
</head><body>
<header><nav aria-label="breadcrumb"><a href="/">Home</a><a href="/ward">Ward</a></nav></header>
<main><article><h1>Welcome</h1><h2>Services</h2><p>Hello <a href="/contact" rel="nofollow">contact us</a>
<a href="https://other.org/x">out</a></p>
<img src="/a.png" alt="logo" width="10"><ul><li>One</li><li>Two</li></ul>
<table><caption>Fees</caption><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
<form action="/send" method="POST" id="f"><input name="q" type="text" required><button>Go</button></form>
<iframe src="https://maps.example/x"></iframe></article></main><footer>f</footer></body></html>`

func TestBuildPageRecord_CapturesStructure(t *testing.T) {
	body := []byte(structureFixture)
	parsed, err := Parse(body, "https://ward.gov.np/", "text/html")
	if err != nil {
		t.Fatal(err)
	}
	r, err := BuildPageRecord(body, "https://ward.gov.np/", "text/html", parsed)
	if err != nil {
		t.Fatal(err)
	}
	if r.Lang != "ne" || r.Title != "Ward Office" || r.Charset != "utf-8" || r.Viewport == "" || r.Doctype != "html" {
		t.Errorf("head fields wrong: lang=%q title=%q charset=%q viewport=%q doctype=%q", r.Lang, r.Title, r.Charset, r.Viewport, r.Doctype)
	}
	if len(r.MetaTags) < 5 || r.TwitterCard["twitter:card"] != "summary" || r.OpenGraph["og:title"] != "Ward" {
		t.Errorf("meta tags not captured: %d tags, twitter=%v og=%v", len(r.MetaTags), r.TwitterCard, r.OpenGraph)
	}
	if len(r.LinkTags) != 2 || len(r.Stylesheets) != 1 {
		t.Errorf("link tags = %d stylesheets = %d", len(r.LinkTags), len(r.Stylesheets))
	}
	if r.TagCounts["a"] != 4 || r.TagCounts["h1"] != 1 || r.DOMDepth < 4 || r.NodeCount < 20 {
		t.Errorf("tag histogram off: a=%d h1=%d depth=%d nodes=%d", r.TagCounts["a"], r.TagCounts["h1"], r.DOMDepth, r.NodeCount)
	}
	tags := map[string]bool{}
	for _, o := range r.Outline {
		tags[o.Tag] = true
	}
	for _, want := range []string{"header", "nav", "main", "article", "footer", "h1", "h2", "form", "table", "ul"} {
		if !tags[want] {
			t.Errorf("outline missing %s", want)
		}
	}
	var internal, external int
	for _, l := range r.Links {
		if l.Internal {
			internal++
		} else {
			external++
		}
	}
	if internal != 3 || external != 1 {
		t.Errorf("links internal=%d external=%d, want 3/1", internal, external)
	}
	if len(r.Images) != 1 || r.Images[0].Alt != "logo" || len(r.Iframes) != 1 {
		t.Errorf("media wrong: images=%v iframes=%v", r.Images, r.Iframes)
	}
	if len(r.Scripts) != 2 || r.Scripts[0].Src != "https://ward.gov.np/app.js" || !r.Scripts[0].Defer || !r.Scripts[1].Inline {
		t.Errorf("scripts wrong: %+v", r.Scripts)
	}
	if len(r.Forms) != 1 || r.Forms[0].Method != "post" || len(r.Forms[0].Fields) != 2 || !r.Forms[0].Fields[0].Required {
		t.Errorf("forms wrong: %+v", r.Forms)
	}
	if len(r.Tables) != 1 || r.Tables[0].Rows != 2 || r.Tables[0].Cols != 2 || r.Tables[0].Caption != "Fees" {
		t.Errorf("tables wrong: %+v", r.Tables)
	}
	if len(r.Lists) != 1 || r.Lists[0].Items != 2 {
		t.Errorf("lists wrong: %+v", r.Lists)
	}
	if len(r.Breadcrumbs) != 2 || r.WordCount == 0 || r.TextLength == 0 || len(r.Headings) != 2 {
		t.Errorf("breadcrumbs=%v words=%d headings=%d", r.Breadcrumbs, r.WordCount, len(r.Headings))
	}
}
