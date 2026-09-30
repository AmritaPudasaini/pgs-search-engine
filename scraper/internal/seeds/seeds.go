// Package seeds parses a seed-list file: one or more categories of starting
// URLs for a crawl, so a single run can cover many unrelated sites (e.g.
// "news", "sports", "tech") the way a real search engine's crawler is
// seeded, instead of one `--seeds` flag pointed at a single site.
package seeds

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// DefaultCategory is used for URLs that appear before any [category] header
// (or in a file that never declares one).
const DefaultCategory = "uncategorized"

// DefaultPriority is used for a category or URL that doesn't specify one.
// Higher values are crawled first -- see ParseFile.
const DefaultPriority = 0

// Seed is one starting URL tagged with the category it belongs to and the
// priority it should be crawled at.
type Seed struct {
	URL      string
	Category string
	// Priority controls crawl order among queued URLs: higher values are
	// fetched before lower ones. Every link discovered from this seed
	// inherits its priority, so a high-priority seed's whole branch is
	// favored over a low-priority one's, not just the seed page itself.
	Priority int
}

// ParseFile reads a seed-list file in this format:
//
//	# comments and blank lines are ignored
//	[news]
//	https://example-news.com
//	https://another-news-site.com
//
//	[tech 10]
//	https://example-tech.com
//	https://breaking-tech.com 20
//
// A `[category]` line starts a new category; every non-empty, non-comment
// line after it (until the next `[category]` line) is a seed URL in that
// category. URLs given before any `[category]` line fall under
// DefaultCategory.
//
// A category header may carry a second, whitespace-separated field giving
// the default priority for every seed under it (`[tech 10]`); omitted, it
// resets to DefaultPriority for that category. A seed line may itself carry
// a second field overriding that default just for that one URL
// (`https://breaking-tech.com 20`). Higher priority values are crawled
// first; see workflows.FrontierItem for how this is applied during a crawl.
func ParseFile(path string) ([]Seed, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open seeds file: %w", err)
	}
	defer f.Close()

	var out []Seed
	category := DefaultCategory
	categoryPriority := DefaultPriority

	scanner := bufio.NewScanner(f)
	lineNo := 0
	for scanner.Scan() {
		lineNo++
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			fields := strings.Fields(line[1 : len(line)-1])
			category = DefaultCategory
			categoryPriority = DefaultPriority
			if len(fields) > 0 && fields[0] != "" {
				category = fields[0]
			}
			if len(fields) > 1 {
				p, err := strconv.Atoi(fields[1])
				if err != nil {
					return nil, fmt.Errorf("seeds file %s line %d: invalid category priority %q: %w", path, lineNo, fields[1], err)
				}
				categoryPriority = p
			}
			continue
		}
		fields := strings.Fields(line)
		priority := categoryPriority
		if len(fields) > 1 {
			p, err := strconv.Atoi(fields[1])
			if err != nil {
				return nil, fmt.Errorf("seeds file %s line %d: invalid priority %q: %w", path, lineNo, fields[1], err)
			}
			priority = p
		}
		out = append(out, Seed{URL: fields[0], Category: category, Priority: priority})
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read seeds file: %w", err)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("seeds file %s contains no URLs", path)
	}
	return out, nil
}
