package parser

import (
	"bytes"
	"net/url"
	"strings"

	"golang.org/x/net/html"
	"golang.org/x/net/html/charset"

	"search-engine-scraper/internal/model"
	"search-engine-scraper/internal/normalize"
)

const (
	maxOutlineNodes = 400
	maxRecordLinks  = 5000
	maxRecordImages = 1000
	maxListSamples  = 3
	outlineLabelLen = 80
)

var outlineTags = map[string]bool{
	"header": true, "nav": true, "main": true, "article": true, "section": true,
	"aside": true, "footer": true, "form": true, "table": true, "ul": true,
	"ol": true, "dl": true, "figure": true, "dialog": true, "details": true,
	"h1": true, "h2": true, "h3": true, "h4": true, "h5": true, "h6": true,
}

// BuildPageRecord extracts the full structural capture of a page: every
// meta and link tag, the tag histogram and DOM depth, a structural outline,
// all links/images/media/scripts/forms/tables/lists. Fields that come from
// the semantic parse (title, text, headings, links, JSON-LD, ...) are copied
// from parsed. The caller fills in fetch metadata (URL, status, hashes,
// storage keys).
func BuildPageRecord(body []byte, baseURL, contentType string, parsed *Parsed) (*model.PageRecord, error) {
	base, err := url.Parse(baseURL)
	if err != nil {
		return nil, err
	}
	r, err := charset.NewReader(bytes.NewReader(body), contentType)
	if err != nil {
		r = bytes.NewReader(body)
	}
	doc, err := html.Parse(r)
	if err != nil {
		return nil, err
	}

	rec := &model.PageRecord{
		TagCounts:   map[string]int{},
		OpenGraph:   map[string]string{},
		TwitterCard: map[string]string{},
	}
	if parsed != nil {
		rec.Title = parsed.Title
		rec.Description = parsed.MetaDescription
		rec.OpenGraph = parsed.OpenGraph
		rec.JSONLD = parsed.JSONLD
		rec.Headings = parsed.Headings
		rec.ContactInfo = parsed.ContactInfo
		rec.SocialLinks = parsed.SocialLinks
		rec.Text = parsed.Text
		rec.SimHash = parsed.SimHash
		rec.Country = parsed.Country
		rec.Geo = parsed.Geo
		rec.CanonicalURL = parsed.CanonicalURL
	}

	baseHost := strings.ToLower(base.Hostname())
	seenImg := map[string]bool{}
	seenLink := map[string]bool{}

	var walk func(n *html.Node, depth int)
	walk = func(n *html.Node, depth int) {
		if n.Type == html.DoctypeNode {
			rec.Doctype = n.Data
			return
		}
		if n.Type != html.ElementNode {
			for c := n.FirstChild; c != nil; c = c.NextSibling {
				walk(c, depth)
			}
			return
		}
		tag := n.Data
		rec.NodeCount++
		rec.TagCounts[tag]++
		if depth > rec.DOMDepth {
			rec.DOMDepth = depth
		}

		if outlineTags[tag] && len(rec.Outline) < maxOutlineNodes {
			node := model.OutlineNode{Tag: tag, Depth: depth, ID: attrValue(n, "id"), Role: attrValue(n, "role")}
			if cls := strings.Fields(attrValue(n, "class")); len(cls) > 0 {
				node.Classes = cls
			}
			if label := attrValue(n, "aria-label"); label != "" {
				node.Label = label
			} else if strings.HasPrefix(tag, "h") && len(tag) == 2 {
				node.Label = truncate(collapseWhitespace(nodeText(n)), outlineLabelLen)
			}
			rec.Outline = append(rec.Outline, node)
		}

		switch tag {
		case "html":
			rec.Lang = attrValue(n, "lang")
		case "meta":
			mt := model.MetaTag{
				Name: attrValue(n, "name"), Property: attrValue(n, "property"),
				HTTPEquiv: attrValue(n, "http-equiv"), Charset: attrValue(n, "charset"),
				Content: attrValue(n, "content"),
			}
			rec.MetaTags = append(rec.MetaTags, mt)
			if mt.Charset != "" {
				rec.Charset = mt.Charset
			}
			if strings.EqualFold(mt.Name, "viewport") {
				rec.Viewport = mt.Content
			}
			if strings.HasPrefix(strings.ToLower(mt.Name), "twitter:") {
				rec.TwitterCard[mt.Name] = mt.Content
			}
		case "link":
			lt := model.LinkTag{
				Rel: attrValue(n, "rel"), Type: attrValue(n, "type"),
				Hreflang: attrValue(n, "hreflang"), Sizes: attrValue(n, "sizes"), Media: attrValue(n, "media"),
			}
			if href := attrValue(n, "href"); href != "" {
				if abs, ok := normalize.Resolve(base, href); ok {
					lt.Href = abs
				} else {
					lt.Href = href
				}
			}
			rec.LinkTags = append(rec.LinkTags, lt)
			if hasRelToken(lt.Rel, "stylesheet") && lt.Href != "" {
				rec.Stylesheets = append(rec.Stylesheets, lt.Href)
			}
		case "a":
			href := attrValue(n, "href")
			if href == "" || len(rec.Links) >= maxRecordLinks {
				break
			}
			abs, ok := normalize.Resolve(base, href)
			if !ok || seenLink[abs] {
				break
			}
			seenLink[abs] = true
			u, _ := url.Parse(abs)
			internal := u != nil && (strings.EqualFold(u.Hostname(), baseHost) || strings.HasSuffix(strings.ToLower(u.Hostname()), "."+baseHost))
			rec.Links = append(rec.Links, model.PageLink{
				Href: abs, Text: truncate(collapseWhitespace(nodeText(n)), 200), Title: attrValue(n, "title"),
				Rel: attrValue(n, "rel"), Target: attrValue(n, "target"), Internal: internal,
			})
		case "img":
			src := attrValue(n, "src")
			if src == "" {
				src = attrValue(n, "data-src")
			}
			if src == "" || len(rec.Images) >= maxRecordImages {
				break
			}
			abs, ok := normalize.Resolve(base, src)
			if !ok || seenImg[abs] {
				break
			}
			seenImg[abs] = true
			rec.Images = append(rec.Images, model.PageImage{
				Src: abs, Alt: attrValue(n, "alt"), Title: attrValue(n, "title"),
				Width: attrValue(n, "width"), Height: attrValue(n, "height"),
			})
		case "video", "audio", "source":
			if src := attrValue(n, "src"); src != "" {
				if abs, ok := normalize.Resolve(base, src); ok {
					if tag == "audio" || (tag == "source" && n.Parent != nil && n.Parent.Data == "audio") {
						rec.Audio = append(rec.Audio, abs)
					} else {
						rec.Videos = append(rec.Videos, abs)
					}
				}
			}
		case "iframe":
			if src := attrValue(n, "src"); src != "" {
				if abs, ok := normalize.Resolve(base, src); ok {
					rec.Iframes = append(rec.Iframes, abs)
				}
			}
		case "script":
			sc := model.PageScript{Type: attrValue(n, "type"), Async: hasAttr(n, "async"), Defer: hasAttr(n, "defer")}
			if src := attrValue(n, "src"); src != "" {
				if abs, ok := normalize.Resolve(base, src); ok {
					sc.Src = abs
				} else {
					sc.Src = src
				}
			} else {
				sc.Inline = true
				if n.FirstChild != nil {
					sc.Bytes = len(n.FirstChild.Data)
				}
			}
			rec.Scripts = append(rec.Scripts, sc)
		case "form":
			f := model.PageForm{Action: attrValue(n, "action"), Method: strings.ToLower(attrValue(n, "method")), ID: attrValue(n, "id")}
			collectFields(n, &f)
			rec.Forms = append(rec.Forms, f)
		case "table":
			rec.Tables = append(rec.Tables, summarizeTable(n))
		case "ul", "ol", "dl":
			rec.Lists = append(rec.Lists, summarizeList(n))
		case "nav":
			if strings.Contains(strings.ToLower(attrValue(n, "aria-label")), "breadcrumb") {
				rec.Breadcrumbs = collectLinkTexts(n)
			}
		}
		if cls := strings.ToLower(attrValue(n, "class")); len(rec.Breadcrumbs) == 0 && strings.Contains(cls, "breadcrumb") {
			rec.Breadcrumbs = collectLinkTexts(n)
		}

		for c := n.FirstChild; c != nil; c = c.NextSibling {
			walk(c, depth+1)
		}
	}
	walk(doc, 0)

	words := len(strings.Fields(rec.Text))
	rec.WordCount = words
	rec.TextLength = len([]rune(rec.Text))
	return rec, nil
}

func hasAttr(n *html.Node, key string) bool {
	for _, a := range n.Attr {
		if strings.EqualFold(a.Key, key) {
			return true
		}
	}
	return false
}

func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func collectFields(n *html.Node, f *model.PageForm) {
	for c := n.FirstChild; c != nil; c = c.NextSibling {
		if c.Type == html.ElementNode {
			switch c.Data {
			case "input", "select", "textarea", "button":
				f.Fields = append(f.Fields, model.FormField{
					Tag: c.Data, Name: attrValue(c, "name"), Type: attrValue(c, "type"),
					Placeholder: attrValue(c, "placeholder"), Required: hasAttr(c, "required"),
				})
			}
		}
		collectFields(c, f)
	}
}

func summarizeTable(t *html.Node) model.PageTable {
	var tb model.PageTable
	var walk func(n *html.Node)
	walk = func(n *html.Node) {
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			if c.Type == html.ElementNode {
				switch c.Data {
				case "caption":
					tb.Caption = collapseWhitespace(nodeText(c))
				case "th":
					if tb.Rows <= 1 {
						tb.Headers = append(tb.Headers, collapseWhitespace(nodeText(c)))
					}
				case "tr":
					tb.Rows++
					cols := 0
					for cc := c.FirstChild; cc != nil; cc = cc.NextSibling {
						if cc.Type == html.ElementNode && (cc.Data == "td" || cc.Data == "th") {
							cols++
						}
					}
					if cols > tb.Cols {
						tb.Cols = cols
					}
				}
			}
			if c.Type == html.ElementNode && c.Data != "table" {
				walk(c)
			}
		}
	}
	walk(t)
	return tb
}

func summarizeList(l *html.Node) model.PageList {
	pl := model.PageList{Kind: l.Data}
	for c := l.FirstChild; c != nil; c = c.NextSibling {
		if c.Type == html.ElementNode && (c.Data == "li" || c.Data == "dt") {
			pl.Items++
			if len(pl.First) < maxListSamples {
				pl.First = append(pl.First, truncate(collapseWhitespace(nodeText(c)), outlineLabelLen))
			}
		}
	}
	return pl
}

func collectLinkTexts(n *html.Node) []string {
	var out []string
	var walk func(*html.Node)
	walk = func(x *html.Node) {
		if x.Type == html.ElementNode && x.Data == "a" {
			if t := collapseWhitespace(nodeText(x)); t != "" {
				out = append(out, t)
			}
		}
		for c := x.FirstChild; c != nil; c = c.NextSibling {
			walk(c)
		}
	}
	walk(n)
	return out
}
