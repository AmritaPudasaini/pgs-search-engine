"""Build data/domains.json: the websites to crawl, as rows of the `domains` table.

Sources:
  - scraper/configs/seeds.example.txt -- the Nepal seed list (`[category priority]`
    sections of https URLs);
  - data/nepal_geography.json -- the 753 local bodies (metropolitan cities,
    municipalities, rural municipalities) and their official websites.

Each website appears once, keyed by its host without `www.` (the convention of
`pgs_db.repositories.reference.site_host`, which `link_domains_to_local_bodies` also
uses). A website that is a local body's own site, or a subdomain of it, carries that
local body's code (`local_body_code`, e.g. MUN414), which seed_domains.py resolves to
`domains.local_body_id`: the domain's geolocation (province, district, municipality).
Local bodies whose website is not in the seed list are added, so every local
government site is crawled and geo-linked. Other websites have no geolocation
(`local_body_code` null).

The output is committed, so seeding never depends on the scraper's files. Re-run this
only to rebuild it from updated sources:

    python scripts/build_domains.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT.parent / "scraper" / "configs" / "seeds.example.txt"
GEOGRAPHY = ROOT / "data" / "nepal_geography.json"
OUTPUT = ROOT / "data" / "domains.json"

# Seed-list section -> domains.category (pgs_db.enums.DomainCategory).
CATEGORY = {
    "major-public": "GOVERNMENT",
    "courts": "GOVERNMENT",
    "government": "GOVERNMENT",
    "military": "GOVERNMENT",
    "finance": "FINANCE",
    "media-news": "NEWS",
    "education": "EDUCATION",
    "non-profit": "NGO",
    "commercial": "COMMERCIAL",
    "business": "COMMERCIAL",
    "network": "OTHER",
    "information": "OTHER",
    "professional": "OTHER",
    "personal": "OTHER",
}

LOCAL_BODY_LABEL = {
    "METROPOLITAN_CITY": "Metropolitan City",
    "SUB_METROPOLITAN_CITY": "Sub-Metropolitan City",
    "MUNICIPALITY": "Municipality",
    "RURAL_MUNICIPALITY": "Rural Municipality",
}


def site_host(url_or_host: str) -> str:
    value = url_or_host.strip().lower()
    host = urlsplit(value if "//" in value else f"//{value}").hostname or ""
    return host.removeprefix("www.")


def priority(seed_priority: int) -> str:
    """The seed list's 20..160 scale -> domains.priority (LOW / NORMAL / HIGH)."""
    if seed_priority >= 140:
        return "HIGH"
    if seed_priority >= 50:
        return "NORMAL"
    return "LOW"


def read_seeds() -> list[tuple[str, str, int]]:
    """(host, section, seed priority) per seed URL, in file order (highest first)."""
    seeds, section, prio = [], None, 0
    for line in SEEDS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        header = re.fullmatch(r"\[(\S+) (\d+)\]", line)
        if header:
            section, prio = header.group(1), int(header.group(2))
        elif line.startswith(("https://", "http://")):
            if section not in CATEGORY:
                raise ValueError(f"seed {line!r} is in an unknown section [{section}]")
            seeds.append((site_host(line), section, prio))
    return seeds


def build() -> list[dict]:
    geography = json.loads(GEOGRAPHY.read_text(encoding="utf-8"))
    local_bodies = {
        site_host(lb["website"]): lb for lb in geography["local_bodies"] if lb.get("website")
    }

    def local_body_of(host: str) -> dict | None:
        if host in local_bodies:
            return local_bodies[host]
        return next((lb for site, lb in local_bodies.items() if host.endswith("." + site)), None)

    def website_name(host: str, lb: dict | None) -> str | None:
        if lb is None:
            return None
        name = f"{lb['name_en']} {LOCAL_BODY_LABEL[lb['type']]}"
        return name if host == site_host(lb["website"]) else f"{name} ({host})"

    rows: dict[str, dict] = {}
    # The seed list is ordered by priority, so the first occurrence of a host (with or
    # without www.) keeps its highest section.
    for host, section, prio in read_seeds():
        if host in rows:
            continue
        lb = local_body_of(host)
        rows[host] = {
            "domain": host,
            "website_name": website_name(host, lb),
            "category": "GOVERNMENT" if lb else CATEGORY[section],
            "status": "PENDING",
            "priority": "HIGH" if lb else priority(prio),
            "rate_limit_per_sec": 1,
            "local_body_code": lb["code"] if lb else None,
        }
    for host, lb in local_bodies.items():
        rows.setdefault(
            host,
            {
                "domain": host,
                "website_name": website_name(host, lb),
                "category": "GOVERNMENT",
                "status": "PENDING",
                "priority": "HIGH",
                "rate_limit_per_sec": 1,
                "local_body_code": lb["code"],
            },
        )
    return sorted(rows.values(), key=lambda r: r["domain"])


def main() -> None:
    rows = build()
    payload = {
        "_source": (
            "scraper/configs/seeds.example.txt + the local-body websites of "
            "data/nepal_geography.json; built by scripts/build_domains.py"
        ),
        "_note": (
            "Rows of the domains table. local_body_code (a local_bodies.code) is resolved to "
            "local_body_id when seeded; it is the domain's geolocation, null for websites that "
            "are not a local government's."
        ),
        "domains": rows,
    }
    # One domain per line, so a rebuild's diff shows exactly which websites changed.
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    OUTPUT.write_text(
        "{\n"
        f' "_source": {json.dumps(payload["_source"])},\n'
        f' "_note": {json.dumps(payload["_note"])},\n'
        ' "domains": [\n  ' + ",\n  ".join(lines) + "\n ]\n}\n",
        encoding="utf-8",
    )
    linked = sum(1 for r in rows if r["local_body_code"])
    print(f"wrote {OUTPUT}: {len(rows)} domains, {linked} linked to a local body")


if __name__ == "__main__":
    main()
