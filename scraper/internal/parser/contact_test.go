package parser

import "testing"

func TestParseForDomainClassifiesLinksAndExtractsMetadata(t *testing.T) {
	doc := `<html><head>
<title>Ministry</title>
<meta name="description" content="Official ministry page">
<meta name="keywords" content=" Nepal, government, Nepal ">
<meta property="og:title" content="Ministry OG">
<meta property="og:image" content="https://cdn.example/image.jpg">
</head><body>
<a href="/about">About</a>
<a href="https://office.example.gov.np/team">Team</a>
<a href="https://nepal.gov.np">Portal</a>
<a href="mailto:Info@Example.Gov.Np">Email</a>
<a href="tel:+977-1-4200000">Call</a>
<a href="https://facebook.com/example">Facebook</a>
<address>Singha Durbar, Kathmandu</address>
<img src="/logo.png"><video src="/intro.mp4"></video>
</body></html>`

	p, err := ParseForDomain([]byte(doc), "https://example.gov.np/", "text/html", "example.gov.np")
	if err != nil {
		t.Fatalf("ParseForDomain: %v", err)
	}
	if len(p.InternalLinks) != 2 {
		t.Fatalf("InternalLinks = %v, want base domain and subdomain links", p.InternalLinks)
	}
	if len(p.ExternalLinks) != 2 {
		t.Fatalf("ExternalLinks = %v, want portal and social links", p.ExternalLinks)
	}
	if len(p.MetaKeywords) != 2 || p.MetaKeywords[0] != "Nepal" || p.MetaKeywords[1] != "government" {
		t.Fatalf("MetaKeywords = %v", p.MetaKeywords)
	}
	if p.OpenGraph["og:title"] != "Ministry OG" || p.OpenGraph["og:image"] == "" {
		t.Fatalf("OpenGraph = %v", p.OpenGraph)
	}
	if len(p.ContactInfo.Emails) != 1 || p.ContactInfo.Emails[0] != "info@example.gov.np" {
		t.Fatalf("emails = %v", p.ContactInfo.Emails)
	}
	if len(p.ContactInfo.Phones) == 0 || p.ContactInfo.Address != "Singha Durbar, Kathmandu" {
		t.Fatalf("contact = %+v", p.ContactInfo)
	}
	if len(p.SocialLinks) != 1 || len(p.ImageLinks) != 1 || len(p.VideoLinks) != 1 {
		t.Fatalf("social=%v images=%v videos=%v", p.SocialLinks, p.ImageLinks, p.VideoLinks)
	}
}

func TestClassifyLinksRejectsLookalikeDomains(t *testing.T) {
	internal, external := ClassifyLinks([]string{
		"https://service.example.gov.np/a",
		"https://example.gov.np.evil.test/b",
	}, "example.gov.np")
	if len(internal) != 1 || len(external) != 1 {
		t.Fatalf("internal=%v external=%v", internal, external)
	}
}
