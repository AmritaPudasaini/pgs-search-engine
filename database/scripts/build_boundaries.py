"""Build `data/boundaries/*.geojson.gz` from Open Knowledge Nepal's boundary data.

Run by a maintainer when the source changes, not at deploy time: the output is
committed, so seeding (`seed_boundaries.py`) never needs the network.

Source: https://github.com/openknowledgenp/localboundaries, pinned to `SOURCE_COMMIT`.
License: CC BY 4.0, attribution in `data/boundaries/ATTRIBUTION.md`.

The source keys shapes by name (`DISTRICT`, `GaPa_NaPa`), spelled differently from our
gazetteer and partly pre-rename. This script maps every shape to our codes (P1, D38,
MUN414) and **refuses to write** unless the mapping is exact: every province, district
and local body gets at least one shape, and no shape lands on two of them. Protected
areas (national parks, reserves) are not local bodies and are left out.

Usage:  python scripts/build_boundaries.py
"""

import difflib
import gzip
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

SOURCE_COMMIT = "54f496a289670ab4fd781d8191c12a0f4cad7c15"  # 2026-07-04
SOURCE_URL = (
    "https://raw.githubusercontent.com/openknowledgenp/localboundaries/"
    f"{SOURCE_COMMIT}/public/data/{{level}}/nepal.geojson"
)

DATA = Path(__file__).resolve().parent.parent / "data"
GAZETTEER = DATA / "nepal_geography.json"
OUT = DATA / "boundaries"

# Source district name -> our districts.name_en.
DISTRICT_ALIASES = {
    "ACHHAM": "Acham",
    "CHITAWAN": "Chitwan",
    "KABHREPALANCHOK": "Kavrepalanchok",
    "KAPILBASTU": "Kapilvastu",
    "MAKAWANPUR": "Makwanpur",
    "NAWALPARASI_E": "Nawalpur",  # Nawalparasi (Bardaghat Susta East), Gandaki
    "NAWALPARASI_W": "Parasi",  # Nawalparasi (Bardaghat Susta West), Lumbini
    "PANCHTHAR": "Pachthar",
    "PARBAT": "Parwat",
    "RAMECHHAP": "Ramechap",
    "RUKUM_E": "Eastern Rukum",
    "RUKUM_W": "Western Rukum",
    "TANAHU": "Tanahun",
}

# (source district, source name) -> our local_bodies.name_en, for local bodies the
# source still carries under a pre-rename name. Checked one by one: each is the only
# unmatched local body left in its district, and the rename is on record.
RENAMED = {
    ("SUNSARI", "Barah"): "BarahaKshetra",
    ("KHOTANG", "Diprung"): "Diprung Chuichumma",
    ("UDAYAPUR", "Sunkoshi"): "Limchungbung",
    ("SAPTARI", "Belhi Chapena"): "Rajgadh",
    ("SINDHUPALCHOK", "Lisangkhu Pakhar"): "Lisankhu",
    ("NUWAKOT", "Meghang"): "Myagang",
    ("GORKHA", "Bhimsen"): "Bhimsen Thapa",
    ("KASKI", "Pokhara Lekhnath"): "Pokhara",
    ("MANANG", "Neshyang"): "Manang Ngisyang",
    ("MUSTANG", "Dalome"): "Lo-Ghekar Damodarkunda",
    ("GULMI", "Ruru"): "Rurukshetra",
    ("ROLPA", "Duikholi"): "Pariwartan",
    ("ROLPA", "Sukidaha"): "Sunil Smiriti",
    ("ROLPA", "Suwarnabati"): "GangaDev",
    ("SALYAN", "Dhorchaur"): "Siddha Kumakh",
    ("SALYAN", "Kumakhmalika"): "Kumakh",
    ("JAJARKOT", "Tribeni Nalagad"): "Nalgad",
    ("KALIKOT", "Kalika"): "Shubha Kalika",
    ("BAJURA", "Chhededaha"): "Khaptad Chhededaha",
    ("BAJURA", "Pandav Gupha"): "Jagannath",
    ("BAJHANG", "Kanda"): "Saipal",
    ("DOTI", "Bogtan"): "Bogatan-Phudsil",
    ("DARCHULA", "Byas"): "Vyans",
}

LOCAL_BODY_TYPES = {"Gaunpalika", "Nagarpalika", "Mahanagarpalika", "Upamahanagarpalika"}

# Spelling variants only (Tribeni/Triveni, Illam/Ilam). Every fuzzy match is printed
# for review; renames go in RENAMED instead.
FUZZY_CUTOFF = 0.75


def _key(name: str | None) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _fetch(level: str) -> dict[str, Any]:
    with urllib.request.urlopen(SOURCE_URL.format(level=level), timeout=120) as response:
        return json.load(response)


def _round(coords: Any) -> Any:
    """6 decimal places is ~0.1 m: far below the source's accuracy, and half the size."""
    if isinstance(coords, float):
        return round(coords, 6)
    return [_round(c) for c in coords]


def _feature(code: str, geometry: dict[str, Any]) -> dict[str, Any]:
    geometry = {"type": geometry["type"], "coordinates": _round(geometry["coordinates"])}
    return {"type": "Feature", "properties": {"code": code}, "geometry": geometry}


def _write(name: str, features: list[dict[str, Any]]) -> None:
    body = {"type": "FeatureCollection", "source_commit": SOURCE_COMMIT, "features": features}
    path = OUT / f"{name}.geojson.gz"
    # mtime=0 keeps the file byte-identical across rebuilds of the same source.
    with gzip.GzipFile(path, "wb", mtime=0) as out:
        out.write(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    print(f"wrote {path.name}: {len(features)} features")


def main() -> None:
    gazetteer = json.loads(GAZETTEER.read_text(encoding="utf-8"))
    district_code = {_key(d["name_en"]): d["code"] for d in gazetteer["districts"]}
    bodies_by_district: dict[str, dict[str, str]] = {}
    for lb in gazetteer["local_bodies"]:
        bodies_by_district.setdefault(lb["district_code"], {})[_key(lb["name_en"])] = lb["code"]

    provinces = [
        _feature(f"P{f['properties']['PROVINCE']}", f["geometry"])
        for f in _fetch("province")["features"]
    ]

    districts = []
    for f in _fetch("district")["features"]:
        source = f["properties"]["DISTRICT"]
        districts.append(
            _feature(district_code[_key(DISTRICT_ALIASES.get(source, source))], f["geometry"])
        )

    local_bodies = []
    source_names: dict[str, set[tuple[str, str]]] = {}
    for f in _fetch("local-level")["features"]:
        props = f["properties"]
        if props["Type_GN"] not in LOCAL_BODY_TYPES:
            continue  # national parks, reserves: not local bodies
        source_district, source_name = props["DISTRICT"], props["GaPa_NaPa"]
        d_code = district_code[_key(DISTRICT_ALIASES.get(source_district, source_district))]
        candidates = bodies_by_district[d_code]
        name = RENAMED.get((source_district, source_name), source_name)
        code = candidates.get(_key(name))
        if code is None:
            close = difflib.get_close_matches(_key(name), list(candidates), 1, FUZZY_CUTOFF)
            if not close:
                raise SystemExit(f"no local body for {source_district} / {source_name!r}")
            code = candidates[close[0]]
            print(f"  fuzzy: {source_district} / {source_name!r} -> {code}")
        local_bodies.append(_feature(code, f["geometry"]))
        source_names.setdefault(code, set()).add((source_district, source_name))

    _check("provinces", provinces, {p["code"] for p in gazetteer["provinces"]}, one_each=True)
    _check("districts", districts, {d["code"] for d in gazetteer["districts"]}, one_each=True)
    # A local body may be several shapes (an exclave, split in the source under the
    # same name); seeding unions them. Two *different* source names on one code would
    # mean two local bodies were merged by a bad match.
    _check("local bodies", local_bodies, {lb["code"] for lb in gazetteer["local_bodies"]})
    merged = {code: sorted(names) for code, names in source_names.items() if len(names) > 1}
    if merged:
        raise SystemExit(f"different source local bodies matched one code: {merged}")

    OUT.mkdir(exist_ok=True)
    _write("provinces", provinces)
    _write("districts", districts)
    _write("local_bodies", local_bodies)


def _check(label: str, features: list[dict[str, Any]], expected: set[str], *,
           one_each: bool = False) -> None:
    codes = [f["properties"]["code"] for f in features]
    missing, unknown = expected - set(codes), set(codes) - expected
    if missing or unknown:
        raise SystemExit(f"{label}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    if one_each and len(codes) != len(set(codes)):
        raise SystemExit(f"{label}: some code has more than one shape")


if __name__ == "__main__":
    main()
