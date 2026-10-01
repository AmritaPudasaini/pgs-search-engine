"""Render docs/erd.md to pgs_search_engine_full_erd.png.

docs/erd.md is the source of truth: its per-layer Mermaid blocks are merged into one
diagram, coloured by layer, and rendered with the Mermaid CLI (needs Node; npx fetches
@mermaid-js/mermaid-cli on first run).

    python scripts/render_erd.py
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "erd.md"
OUTPUT = ROOT / "pgs_search_engine_full_erd.png"

LAYER_COLOURS = {
    "Reference": "#e3f1e8,stroke:#2e6b4a",
    "Bronze": "#fbeee0,stroke:#a0561c",
    "Silver": "#eceff4,stroke:#5b6678",
    "Gold": "#fbf4dc,stroke:#a87b0c",
}


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    lines = [
        "---",
        "title: PGS Search Engine ER diagram"
        " (green Reference, orange Bronze, grey Silver, gold Gold)",
        "---",
        "erDiagram",
    ]
    # Each "## Layer" heading and the first mermaid block under it; (?!^## ) stops a
    # heading without a diagram from swallowing the next section's block.
    blocks = re.findall(
        r"^## (\w+)[^\n]*\n(?:(?!^## ).)*?```mermaid\n(.*?)```", text, re.S | re.M
    )
    for heading, block in blocks:
        body = block.split("\n", 1)[1]  # drop the block's own "erDiagram" line
        lines.append(body)
        entities = re.findall(r"^    (\w+) \{", body, re.M)
        colour = LAYER_COLOURS.get(heading)
        if colour and entities:
            lines.append(f"    classDef layer_{heading.lower()} fill:{colour}")
            lines.append(f"    class {','.join(entities)} layer_{heading.lower()}")

    with tempfile.TemporaryDirectory() as tmp:
        mmd = Path(tmp) / "erd.mmd"
        mmd.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run(
            f'npx -y @mermaid-js/mermaid-cli -i "{mmd}" -o "{OUTPUT}" -b white -s 3',
            shell=True,
            check=True,
        )
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
