# Whole-domain crawling, JavaScript rendering and structured pages

## Crawl every page of each domain

```bash
# from the repository root
docker compose --profile scraper-sharded up -d --build   # stack + Chrome + shard workers
```

Airflow's `scraper_crawl_schedule` DAG starts this crawl every 30 minutes for every
website in the `domains` table (limits: `SCRAPER_MAX_DEPTH`,
`SCRAPER_MAX_PAGES_PER_DOMAIN`, `SCRAPER_CONCURRENT_DOMAINS` in `.env`; set
`SCRAPER_TASK_QUEUE_SHARDS=3` for the sharded workers). By hand,
from the host: `go run ./cmd/scraper --seeds-file=configs/seeds.example.txt
--whole-domain --max-depth=8 --max-pages=2000 --max-concurrent-domains=20
--task-queue-shards=3`.

`--whole-domain` starts a `CrawlDomainsWorkflow` that runs one child
`CrawlWorkflow` per host. Each child follows links and the sitemap across its
whole host (same-host only) up to the per-domain budget, with its own frontier
and history, so a large site never crowds out others. In this mode:

- `--max-pages` is the page budget of **each** domain, `--max-depth` how many
  link hops from the seed to follow.
- `--max-concurrent-domains` domains are crawled at the same time.
- `--country-filter` defaults to empty (store every page).

## JavaScript (client-rendered) pages

Workers take `--render=off|auto|always` and `--chrome-url` (the compose stack
runs `chromedp/headless-shell` as `chrome`). With `auto`, a page whose static
HTML is an empty app shell (`<div id="root">`, "enable JavaScript", script-heavy
with almost no text) is loaded in Chrome and its resulting DOM is parsed, so
text and links come from what a visitor sees. `always` renders every page. If
Chrome fails, the static HTML is used and the error is recorded.

## What is stored in S3

| Key | Content |
| --- | --- |
| `html/<host>/<hash>.html` | raw HTML exactly as served |
| `html/<host>/rendered-<hash>.html` | DOM after JavaScript ran (rendered pages only) |
| `pages/<host>/<hash>.json` | full structured record (`model.PageRecord`) |
| `<run_id>/<host>/<url-hash>.json`, `latest/...` | slim document used by the API and, per site, by ETL |
| `<run_id>/_run.json` | run manifest |

When a domain's crawl finishes, the worker publishes one `site_crawl_completed`
event to the Kafka topic `scraped_files_topic` (`--kafka-brokers`,
`--kafka-topic`), keyed by the host and naming `<run_id>/<host>/` as the site's
documents prefix. That event, not individual pages, is what starts the ETL.

A `PageRecord` holds: title, description, lang, charset, viewport, doctype; every
`<meta>` and `<link>` tag; Open Graph and Twitter card; JSON-LD; the heading
outline; a structural outline (header/nav/main/article/section/aside/footer/
form/table/lists with depth, id, classes); tag histogram, DOM depth and node
count; every link (text, rel, target, internal/external), image (alt, size),
video, audio, iframe, script, stylesheet; forms and their fields; tables
(caption, headers, rows, cols); lists; breadcrumbs; contact info and social
links; full text, word count, simhash, country, geo, robots directives, and
the keys of the raw and rendered HTML.

## Limits to know about

- A domain's carried state (frontier + seen set) rides through Temporal
  Continue-As-New; keep `--max-pages` per domain in the low thousands.
- Crawling 12,000 domains completely is a long job; scale shard workers and
  `--max-concurrent-domains` together, and mind per-site politeness
  (`--max-concurrent-per-host`, robots.txt `Crawl-delay` are honored).
