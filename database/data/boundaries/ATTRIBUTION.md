# Boundary data attribution

`provinces.geojson.gz`, `districts.geojson.gz` and `local_bodies.geojson.gz` are derived
from **Local Boundaries** by [Open Knowledge Nepal](https://oknp.org), published at
<https://localboundries.oknp.org> and <https://github.com/openknowledgenp/localboundaries>,
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Source commit: `54f496a289670ab4fd781d8191c12a0f4cad7c15` (2026-07-04).

Changes made by `scripts/build_boundaries.py`:

- each shape's name attributes replaced by this project's code (`P4`, `D38`, `MUN414`);
- protected areas (national parks, wildlife and hunting reserves) left out;
- coordinates rounded to 6 decimal places.

Any page or app that shows these boundaries must credit Open Knowledge Nepal, e.g.
"Boundaries © Open Knowledge Nepal, CC BY 4.0".
