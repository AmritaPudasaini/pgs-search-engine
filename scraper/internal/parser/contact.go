package parser

import (
	"net/url"
	"regexp"
	"strings"

	"golang.org/x/net/html"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

var (
	emailPattern = regexp.MustCompile(`(?i)[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}`)
	phonePattern = regexp.MustCompile(`(?:\+?\d[\d\s().-]{6,}\d)`)
)

func extractContactData(doc *html.Node, links []string) (model.ContactInfo, []string) {
	var info model.ContactInfo
	emails := make(map[string]bool)
	phones := make(map[string]bool)
	addresses := make(map[string]bool)

	addEmail := func(value string) {
		value = strings.ToLower(strings.TrimSpace(value))
		if emailPattern.MatchString(value) && !emails[value] {
			emails[value] = true
			info.Emails = append(info.Emails, value)
		}
	}
	addPhone := func(value string) {
		value = collapseWhitespace(strings.TrimSpace(value))
		if digitCount(value) >= 7 && !phones[value] {
			phones[value] = true
			info.Phones = append(info.Phones, value)
		}
	}

	var walk func(*html.Node)
	walk = func(n *html.Node) {
		if n.Type == html.ElementNode {
			switch n.Data {
			case "a":
				href := attrValue(n, "href")
				lower := strings.ToLower(href)
				switch {
				case strings.HasPrefix(lower, "mailto:"):
					value := strings.TrimSpace(href[len("mailto:"):])
					if i := strings.IndexByte(value, '?'); i >= 0 {
						value = value[:i]
					}
					addEmail(value)
				case strings.HasPrefix(lower, "tel:"):
					addPhone(strings.TrimSpace(href[len("tel:"):]))
				}
			case "address":
				address := collapseWhitespace(nodeText(n))
				if address != "" && !addresses[address] {
					addresses[address] = true
					if info.Address == "" {
						info.Address = address
					}
				}
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			walk(c)
		}
	}
	walk(doc)

	plainText := collapseWhitespace(nodeText(doc))
	for _, email := range emailPattern.FindAllString(plainText, -1) {
		addEmail(email)
	}
	for _, phone := range phonePattern.FindAllString(plainText, -1) {
		addPhone(phone)
	}

	var social []string
	seenSocial := make(map[string]bool)
	for _, link := range links {
		u, err := url.Parse(link)
		if err != nil || !isSocialHost(u.Hostname()) || seenSocial[link] {
			continue
		}
		seenSocial[link] = true
		social = append(social, link)
	}
	return info, social
}

func digitCount(value string) int {
	count := 0
	for _, r := range value {
		if r >= '0' && r <= '9' {
			count++
		}
	}
	return count
}

func isSocialHost(host string) bool {
	host = strings.ToLower(strings.TrimPrefix(host, "www."))
	for _, domain := range []string{
		"facebook.com", "fb.com", "twitter.com", "x.com",
		"linkedin.com", "youtube.com", "youtu.be",
	} {
		if host == domain || strings.HasSuffix(host, "."+domain) {
			return true
		}
	}
	return false
}
