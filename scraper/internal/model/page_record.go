package model

import "time"

// PageRecord is the complete structured capture of one crawled page, stored
// as its own S3 object (pages/<host>/<hash>.json) next to the page's raw
// HTML. It keeps everything extractable from the markup -- every meta and
// link tag, the heading outline, the page's structural skeleton, forms,
// tables, media and scripts -- so downstream consumers never need to
// re-fetch or re-parse the HTML to get at a detail.
type PageRecord struct {
	URL           string    `json:"url"`
	NormalizedURL string    `json:"normalized_url"`
	FinalURL      string    `json:"final_url,omitempty"`
	CanonicalURL  string    `json:"canonical_url,omitempty"`
	Host          string    `json:"host"`
	Depth         int       `json:"depth"`
	StatusCode    int       `json:"status_code"`
	ContentType   string    `json:"content_type"`
	ContentHash   string    `json:"content_hash"`
	FetchedAt     time.Time `json:"fetched_at"`

	// HTMLKey is the S3 key (relative to any configured prefix) of the
	// page's raw HTML as served. RenderedHTMLKey is set when the page was
	// also rendered in a headless browser, and holds the DOM after
	// JavaScript ran; Rendered reports whether that happened.
	HTMLKey         string `json:"html_key,omitempty"`
	RenderedHTMLKey string `json:"rendered_html_key,omitempty"`
	Rendered        bool   `json:"rendered"`
	// RenderReason says why rendering was used ("always", or what the
	// auto-detector saw, e.g. "empty app shell").
	RenderReason string `json:"render_reason,omitempty"`

	Lang        string `json:"lang,omitempty"`
	Title       string `json:"title"`
	Description string `json:"description,omitempty"`
	Charset     string `json:"charset,omitempty"`
	Viewport    string `json:"viewport,omitempty"`
	Doctype     string `json:"doctype,omitempty"`

	MetaTags    []MetaTag         `json:"meta_tags,omitempty"`
	LinkTags    []LinkTag         `json:"link_tags,omitempty"`
	OpenGraph   map[string]string `json:"open_graph,omitempty"`
	TwitterCard map[string]string `json:"twitter_card,omitempty"`
	JSONLD      []string          `json:"json_ld,omitempty"`

	Headings []Heading `json:"headings,omitempty"`
	// Outline is the page's structural skeleton: landmark and sectioning
	// elements (header, nav, main, article, section, aside, footer, form,
	// table, ...) in document order, with their depth, id and classes.
	Outline []OutlineNode `json:"outline,omitempty"`
	// TagCounts is how many times each HTML tag occurs on the page.
	TagCounts map[string]int `json:"tag_counts"`
	DOMDepth  int            `json:"dom_depth"`
	NodeCount int            `json:"node_count"`

	Links       []PageLink   `json:"links,omitempty"`
	Images      []PageImage  `json:"images,omitempty"`
	Videos      []string     `json:"videos,omitempty"`
	Audio       []string     `json:"audio,omitempty"`
	Iframes     []string     `json:"iframes,omitempty"`
	Scripts     []PageScript `json:"scripts,omitempty"`
	Stylesheets []string     `json:"stylesheets,omitempty"`
	Forms       []PageForm   `json:"forms,omitempty"`
	Tables      []PageTable  `json:"tables,omitempty"`
	Lists       []PageList   `json:"lists,omitempty"`
	Breadcrumbs []string     `json:"breadcrumbs,omitempty"`

	ContactInfo ContactInfo `json:"contact_info"`
	SocialLinks []string    `json:"social_links,omitempty"`

	Text       string    `json:"text"`
	TextLength int       `json:"text_length"`
	WordCount  int       `json:"word_count"`
	SimHash    uint64    `json:"sim_hash,omitempty"`
	Country    string    `json:"country,omitempty"`
	Geo        *GeoPoint `json:"geo,omitempty"`

	NoIndex  bool `json:"noindex"`
	NoFollow bool `json:"nofollow"`
}

// MetaTag is one <meta> element, with whichever identifying attribute it
// used (name, property, http-equiv or charset).
type MetaTag struct {
	Name      string `json:"name,omitempty"`
	Property  string `json:"property,omitempty"`
	HTTPEquiv string `json:"http_equiv,omitempty"`
	Charset   string `json:"charset,omitempty"`
	Content   string `json:"content,omitempty"`
}

// LinkTag is one <link> element (canonical, alternate, icon, stylesheet, ...).
type LinkTag struct {
	Rel      string `json:"rel"`
	Href     string `json:"href,omitempty"`
	Type     string `json:"type,omitempty"`
	Hreflang string `json:"hreflang,omitempty"`
	Sizes    string `json:"sizes,omitempty"`
	Media    string `json:"media,omitempty"`
}

// OutlineNode is one structural element in Page.Outline.
type OutlineNode struct {
	Tag     string   `json:"tag"`
	Depth   int      `json:"depth"`
	ID      string   `json:"id,omitempty"`
	Classes []string `json:"classes,omitempty"`
	Role    string   `json:"role,omitempty"`
	Label   string   `json:"label,omitempty"`
}

// PageLink is one <a href> with everything about it.
type PageLink struct {
	Href     string `json:"href"`
	Text     string `json:"text,omitempty"`
	Title    string `json:"title,omitempty"`
	Rel      string `json:"rel,omitempty"`
	Target   string `json:"target,omitempty"`
	Internal bool   `json:"internal"`
}

// PageImage is one <img>.
type PageImage struct {
	Src    string `json:"src"`
	Alt    string `json:"alt,omitempty"`
	Title  string `json:"title,omitempty"`
	Width  string `json:"width,omitempty"`
	Height string `json:"height,omitempty"`
}

// PageScript is one <script>; Inline scripts carry only their byte length.
type PageScript struct {
	Src    string `json:"src,omitempty"`
	Type   string `json:"type,omitempty"`
	Async  bool   `json:"async,omitempty"`
	Defer  bool   `json:"defer,omitempty"`
	Inline bool   `json:"inline,omitempty"`
	Bytes  int    `json:"bytes,omitempty"`
}

// PageForm is one <form> and its fields.
type PageForm struct {
	Action string      `json:"action,omitempty"`
	Method string      `json:"method,omitempty"`
	ID     string      `json:"id,omitempty"`
	Fields []FormField `json:"fields,omitempty"`
}

// FormField is one input/select/textarea/button inside a form.
type FormField struct {
	Tag         string `json:"tag"`
	Name        string `json:"name,omitempty"`
	Type        string `json:"type,omitempty"`
	Placeholder string `json:"placeholder,omitempty"`
	Required    bool   `json:"required,omitempty"`
}

// PageTable summarizes one <table>.
type PageTable struct {
	Caption string   `json:"caption,omitempty"`
	Headers []string `json:"headers,omitempty"`
	Rows    int      `json:"rows"`
	Cols    int      `json:"cols"`
}

// PageList summarizes one <ul>/<ol>/<dl>.
type PageList struct {
	Kind  string   `json:"kind"`
	Items int      `json:"items"`
	First []string `json:"first,omitempty"`
}
