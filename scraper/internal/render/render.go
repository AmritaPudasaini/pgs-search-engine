// Package render loads pages in a real headless Chrome so client-side
// rendered (JavaScript) sites yield their final DOM instead of an empty app
// shell. Chrome runs as a separate service (chromedp/headless-shell) that
// the crawler connects to over the DevTools protocol.
package render

import (
	"context"
	"fmt"
	"net"
	neturl "net/url"
	"strings"
	"time"

	"github.com/chromedp/cdproto/emulation"
	"github.com/chromedp/chromedp"
)

// Mode says when pages are rendered.
type Mode string

const (
	// ModeOff never renders; only the raw served HTML is used.
	ModeOff Mode = "off"
	// ModeAuto renders only pages that look like a JavaScript app shell
	// (see NeedsRender).
	ModeAuto Mode = "auto"
	// ModeAlways renders every HTML page.
	ModeAlways Mode = "always"
)

// ParseMode validates a --render flag value.
func ParseMode(s string) (Mode, error) {
	switch m := Mode(strings.ToLower(strings.TrimSpace(s))); m {
	case ModeOff, ModeAuto, ModeAlways:
		return m, nil
	case "":
		return ModeOff, nil
	default:
		return "", fmt.Errorf("unknown render mode %q: must be off, auto or always", s)
	}
}

// Renderer returns a page's DOM after JavaScript has run.
type Renderer interface {
	// Render loads url and returns the rendered outer HTML and the final URL
	// the browser ended on.
	Render(ctx context.Context, url string) (html, finalURL string, err error)
}

// Chrome renders through a remote headless Chrome's DevTools endpoint.
type Chrome struct {
	alloc   context.Context
	cancel  context.CancelFunc
	sem     chan struct{}
	timeout time.Duration
	settle  time.Duration
	ua      string
}

// NewChrome connects to the DevTools websocket (e.g. ws://chrome:9222).
// maxConcurrent bounds simultaneous tabs; timeout bounds one render.
func NewChrome(devtoolsURL, userAgent string, maxConcurrent int, timeout time.Duration) *Chrome {
	if maxConcurrent < 1 {
		maxConcurrent = 4
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	alloc, cancel := chromedp.NewRemoteAllocator(context.Background(), resolveHost(devtoolsURL))
	return &Chrome{
		alloc: alloc, cancel: cancel,
		sem: make(chan struct{}, maxConcurrent), timeout: timeout,
		settle: 1500 * time.Millisecond, ua: userAgent,
	}
}

// Close drops the connection to Chrome.
func (c *Chrome) Close() { c.cancel() }

// Render implements Renderer. It waits for the document body, gives scripts
// a short settle window to populate the DOM, then returns the full HTML.
func (c *Chrome) Render(ctx context.Context, url string) (string, string, error) {
	select {
	case c.sem <- struct{}{}:
		defer func() { <-c.sem }()
	case <-ctx.Done():
		return "", "", ctx.Err()
	}

	tabCtx, cancelTab := chromedp.NewContext(c.alloc)
	defer cancelTab()
	tabCtx, cancelTimeout := context.WithTimeout(tabCtx, c.timeout)
	defer cancelTimeout()
	// Stop if the caller's context is cancelled too.
	go func() {
		select {
		case <-ctx.Done():
			cancelTimeout()
		case <-tabCtx.Done():
		}
	}()

	var out, final string
	var actions []chromedp.Action
	if c.ua != "" {
		ua := c.ua
		actions = append(actions, chromedp.ActionFunc(func(ctx context.Context) error {
			return emulation.SetUserAgentOverride(ua).Do(ctx)
		}))
	}
	actions = append(actions,
		chromedp.Navigate(url),
		chromedp.WaitReady("body", chromedp.ByQuery),
		chromedp.Sleep(c.settle),
		chromedp.Location(&final),
		chromedp.OuterHTML("html", &out, chromedp.ByQuery),
	)
	if err := chromedp.Run(tabCtx, actions...); err != nil {
		return "", "", fmt.Errorf("render %s: %w", url, err)
	}
	return out, final, nil
}

var shellMarkers = []string{
	`id="root"`, `id='root'`, `id="app"`, `id='app'`, `id="__next"`, `id="__nuxt"`,
	`ng-version`, `data-reactroot`, `<app-root`, `id="svelte"`,
}

var noscriptHints = []string{
	"enable javascript", "requires javascript", "javascript is required",
	"javascript must be enabled", "you need to enable javascript", "turn on javascript",
}

// NeedsRender decides whether a fetched page is a JavaScript app shell that
// would give the wrong content without rendering. parsedTextLen is the
// visible text length the static parse found; html is the raw body.
// It returns a short reason, or "" when the static HTML is enough.
func NeedsRender(html string, parsedTextLen int) string {
	lower := strings.ToLower(html)
	for _, h := range noscriptHints {
		if strings.Contains(lower, h) && parsedTextLen < 1500 {
			return "noscript asks to enable javascript"
		}
	}
	if parsedTextLen < 250 {
		for _, m := range shellMarkers {
			if strings.Contains(lower, m) {
				return "empty app shell (" + strings.Trim(m, `="' <`) + ")"
			}
		}
		if strings.Count(lower, "<script") >= 3 {
			return "little text, script-heavy page"
		}
	}
	return ""
}

// resolveHost swaps a hostname in the DevTools URL for its IP address.
// Chrome's DevTools HTTP endpoint rejects any Host header that is neither
// localhost nor an IP ("Host header is specified and is not an IP address
// or localhost"), which a compose/Kubernetes service name would trip.
func resolveHost(raw string) string {
	u, err := neturl.Parse(raw)
	if err != nil || u.Hostname() == "" || net.ParseIP(u.Hostname()) != nil || u.Hostname() == "localhost" {
		return raw
	}
	addrs, err := net.LookupHost(u.Hostname())
	if err != nil || len(addrs) == 0 {
		return raw
	}
	host := addrs[0]
	if strings.Contains(host, ":") {
		host = "[" + host + "]"
	}
	if port := u.Port(); port != "" {
		host += ":" + port
	}
	u.Host = host
	return u.String()
}
