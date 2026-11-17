"""Export the event-level climate and lunar subset for the static Atlas."""

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from data_paths import ATLAS, CLIMATE, COAST, LUNAR, ROOT, project_path, version_dir


CLIMATE_FIELDS = ("temperature_2m_mean", "precipitation_sum", "wind_speed_10m_mean", "wind_speed_10m_max",
                  "precipitation_previous_3d", "precipitation_previous_7d")
FIELDS = ("date", "country", "moon_phase", "moon_illumination", *CLIMATE_FIELDS, "reported")
PHASES = ("new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous", "full_moon", "waning_gibbous",
          "last_quarter", "waning_crescent")


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def climate_subset(path, requested):
    result = {}
    file = pq.ParquetFile(path)
    for index in range(file.num_row_groups):
        group = file.read_row_group(index, columns=["segment_id", "date", *CLIMATE_FIELDS])
        segment = group["segment_id"][0].as_py()
        if segment not in requested:
            continue
        allowed = pa.array(sorted(requested[segment]), type=pa.date32())
        values = group.filter(pc.is_in(group["date"], value_set=allowed)).to_pylist()
        for row in values:
            result[segment, row["date"].isoformat()] = [round(row[field], 3) if row[field] is not None else None
                                                        for field in CLIMATE_FIELDS]
    if len(result) != sum(map(len, requested.values())):
        raise ValueError("Dias positivos sem correspondência no arquivo de clima")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--spatial", default="v005")
    parser.add_argument("--climate", default="v008")
    parser.add_argument("--lunar", default="v009")
    args = parser.parse_args()
    if any(not re.fullmatch(r"v\d{3,}", ver) for ver in (args.version, args.spatial, args.climate, args.lunar)):
        parser.error("Use versões vNNN")

    index = version_dir(ATLAS, args.spatial) / f"atlas_indice_{args.spatial}.json"
    spatial = version_dir(COAST, args.spatial) / f"gsaf_eventos_segmentos_{args.spatial}.csv"
    climate = version_dir(CLIMATE, args.climate) / f"gsaf_clima_diario_25km_{args.climate}.parquet"
    lunar = version_dir(LUNAR, args.lunar) / f"gsaf_calendario_lunar_{args.lunar}.csv"
    output = version_dir(ATLAS, args.version)
    asset = output / f"atlas_analise_{args.version}.json"
    manifest = output / f"atlas_analise_manifesto_{args.version}.json"
    dist = ROOT / "sites" / "atlas-costeiro" / "dist" / "data" / asset.name
    if any(path.exists() for path in (asset, dist, manifest)):
        raise FileExistsError(f"Dados do atlas {args.version} já existem")

    events = json.loads(index.read_bytes())["events"]
    links = {row["event_id"]: row for row in csv_rows(spatial) if row["scale_km"] == "25"}
    if len(events) != len(links) or {event["id"] for event in events} != set(links):
        raise ValueError("Os IDs do índice diferem da correspondência espacial")
    requested = defaultdict(set)
    for record in links.values():
        if record["status"] == "assigned":
            requested[record["segment_id"]].add(date.fromisoformat(record["date"]))
    weather = climate_subset(climate, requested)
    moon = {row["date"]: (PHASES.index(row["moon_phase"]), round(float(row["moon_illumination"]) * 100, 3))
            for row in csv_rows(lunar)}
    countries = sorted({row["country"] for row in events})
    country_index = {label: idx for idx, label in enumerate(countries)}
    entries = []
    for row in sorted(events, key=lambda event: (event["date"], event["id"])):
        day = row["date"]
        link = links[row["id"]]
        if (link["date"], link["date_status"]) != (day, row["date_status"]):
            raise ValueError(f"Inconsistência na data de {row['id']}")
        entries.append([day, country_index[row["country"]], *moon.get(day, (None, None)),
                        *weather.get((link["segment_id"], day), [None] * len(CLIMATE_FIELDS)), row["approximate"]])
    counts = {field: sum(entry[index] is not None for entry in entries)
              for index, field in enumerate(FIELDS) if field in (*CLIMATE_FIELDS, "moon_illumination")}
    data = {"version": args.version, "fields": FIELDS, "countries": countries, "events": entries,
            "sources": {"spatial": args.spatial, "climate": args.climate, "lunar": args.lunar}}
    output.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with asset.open("xb") as stream:
        stream.write(payload)
    with dist.open("xb") as stream:
        stream.write(payload)
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump({"version": args.version, "events": len(entries), "coverage": counts,
                   "sources": [{"path": project_path(path), "sha256": sha(path)} for path in (index, spatial, climate, lunar)],
                   "script": {"path": project_path(Path(__file__)), "sha256": sha(Path(__file__))},
                   "product": {"file": asset.name, "bytes": len(payload), "sha256": sha(asset)},
                   "rules": ["Uma linha por evento elegível no atlas. Média sobre ocorrências, mantendo múltiplas por dia.",
                             "Clima ERA5 pelo trecho 25 km atribuído e a data local. Campos ausentes ficam nulos.",
                             "Lua pela data na v009, iluminação reexpressa em percentual.",
                             "Dados públicos incluem data, país/área e variáveis ambientais."],
                   }, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"events": len(entries), "coverage": counts, "bytes": len(payload)}))


if __name__ == "__main__":
    main()
