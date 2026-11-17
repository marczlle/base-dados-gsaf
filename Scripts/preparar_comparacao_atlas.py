"""Export per-date sufficient statistics for the two cohorts in the Atlas."""

import argparse
import gzip
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from data_paths import ATLAS, CLIMATE, COAST, LUNAR, PANEL, ROOT, project_path, version_dir
from preparar_analise_atlas import CLIMATE_FIELDS, csv_rows, sha


EPOCH = date(1970, 1, 1)
METRICS = (*CLIMATE_FIELDS, "moon_illumination")
COHORTS = ("without", "with", "exact")
DIST = ROOT / "sites" / "atlas-costeiro" / "dist" / "data"


def ordinal(day):
    return (day - EPOCH).days


@dataclass
class Scope:
    start: int
    stop: int

    def __post_init__(self):
        length = self.stop - self.start
        self.samples = np.zeros((len(COHORTS), length), dtype=np.int32)
        self.counts = np.zeros((len(COHORTS), length, len(METRICS)), dtype=np.int32)
        self.sums = np.zeros(self.counts.shape, dtype=np.float64)

    def add(self, first, values, valid, cohorts):
        span = slice(first - self.start, first - self.start + len(values))
        for i, selected in enumerate(cohorts):
            included = selected[:, None] & valid
            self.samples[i, span] += selected
            self.counts[i, span] += included
            self.sums[i, span] += np.where(included, values, 0)

    def export(self):
        series = {}
        for i, key in enumerate(COHORTS):
            offsets = np.flatnonzero(self.samples[i])
            stats = self.counts[i, offsets].tolist()
            sums = np.round(self.sums[i, offsets], 4).tolist()
            series[key] = [[self.start + d, n, *metric_count, *metric_sum]
                           for d, n, metric_count, metric_sum in zip(offsets.tolist(), self.samples[i, offsets].tolist(), stats, sums)]
        return series


def country_dates(spatial, events, countries):
    country_by_event = {event["id"]: countries.index(event["country"]) for event in events}
    grouped = defaultdict(dict)
    for row in csv_rows(spatial):
        if row["scale_km"] != "25" or row["status"] != "assigned":
            continue
        country = str(country_by_event[row["event_id"]])
        all_days, exact_days = grouped[row["segment_id"]].setdefault(country, (set(), set()))
        day = ordinal(date.fromisoformat(row["date"]))
        all_days.add(day)
        if row["date_status"] == "exact":
            exact_days.add(day)
    return grouped


def panel_bounds(file):
    groups = []
    for i in range(file.num_row_groups):
        group = file.metadata.row_group(i)
        segment = group.column(0).statistics
        dates = group.column(1).statistics
        if segment.min != segment.max or (dates.max - dates.min).days + 1 != group.num_rows:
            raise ValueError("Parquet esperado com um grupo por segmento e janela diária contínua")
        groups.append((segment.min, ordinal(dates.min), ordinal(dates.max) + 1))
    return groups


def aggregate(panel_path, climate_path, lunar, groups):
    panel = pq.ParquetFile(panel_path)
    climate = pq.ParquetFile(climate_path)
    bounds = panel_bounds(panel)
    if panel_bounds(climate) != bounds or {segment for segment, _, _ in bounds} != set(groups):
        raise ValueError("Trechos ou datas divergem entre painel, clima e correspondências espaciais")
    limits = defaultdict(list)
    for segment, first, stop in bounds:
        for country in ("all", *groups[segment]):
            limits[country].append((first, stop))
    scopes = {key: Scope(min(x[0] for x in windows), max(x[1] for x in windows)) for key, windows in limits.items()}
    moon_first = scopes["all"].start
    moon_values = np.full(scopes["all"].stop - moon_first, np.nan)
    for row in csv_rows(lunar):
        day = ordinal(date.fromisoformat(row["date"]))
        if moon_first <= day < scopes["all"].stop:
            moon_values[day - moon_first] = float(row["moon_illumination"]) * 100
    for index, (segment, first, stop) in enumerate(bounds):
        labels = panel.read_row_group(index, columns=["date", "attack", "attack_count", "reported_attack_count"])
        weather = climate.read_row_group(index, columns=["date", *CLIMATE_FIELDS])
        if not labels["date"].equals(weather["date"]):
            raise ValueError(f"Datas divergentes em {segment}")
        days = labels["date"].cast(pa.int32()).to_numpy()
        moon = moon_values[days - moon_first]
        if not np.isfinite(moon).all():
            raise ValueError(f"Dia do painel sem iluminação lunar em {segment}")
        values = np.column_stack([*(weather[field].to_numpy() for field in CLIMATE_FIELDS), moon])
        valid = np.isfinite(values)
        attack = labels["attack"].to_numpy() == 1
        exact = labels["attack_count"].to_numpy() > labels["reported_attack_count"].to_numpy()
        scopes["all"].add(first, values, valid, (~attack, attack, exact))
        for country, (attack_days, exact_days) in groups[segment].items():
            country_attack = np.isin(days, list(attack_days))
            country_exact = np.isin(days, list(exact_days))
            if np.any(country_attack & ~attack) or np.any(country_exact & ~exact):
                raise ValueError(f"Data positiva de país ausente do painel em {segment}")
            scopes[country].add(first, values, valid, (~attack, country_attack, country_exact))
    return scopes


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--event-version", default="v010")
    args = parser.parse_args()
    if any(not re.fullmatch(r"v[0-9]{3,}", version) for version in (args.version, args.event_version)):
        parser.error("Use versões vNNN")
    event_asset = version_dir(ATLAS, args.event_version) / f"atlas_analise_{args.event_version}.json"
    event_data = json.loads(event_asset.read_bytes())
    spatial_version, climate_version, lunar_version = (event_data["sources"][key] for key in ("spatial", "climate", "lunar"))
    panel_path = version_dir(PANEL, "v006") / "gsaf_painel_diario_25km_v006.parquet"
    climate_path = version_dir(CLIMATE, climate_version) / f"gsaf_clima_diario_25km_{climate_version}.parquet"
    lunar_path = version_dir(LUNAR, lunar_version) / f"gsaf_calendario_lunar_{lunar_version}.csv"
    spatial_path = version_dir(COAST, spatial_version) / f"gsaf_eventos_segmentos_{spatial_version}.csv"
    atlas_index = version_dir(ATLAS, spatial_version) / f"atlas_indice_{spatial_version}.json"
    output = version_dir(ATLAS, args.version)
    bundle = f"comparacao_{args.version}"
    index_name = f"atlas_comparacao_{args.version}.json"
    if output.exists() or (DIST / bundle).exists() or (DIST / index_name).exists():
        raise FileExistsError(f"Já existem produtos da versão {args.version}")
    events = json.loads(atlas_index.read_bytes())["events"]
    groups = country_dates(spatial_path, events, event_data["countries"])
    scopes = aggregate(panel_path, climate_path, lunar_path, groups)
    files = {key: f"{bundle}/{key}.json.gz" for key in scopes}
    with TemporaryDirectory(dir=output.parent, prefix=".comparacao_") as location:
        stage = Path(location) / "data"
        (stage / bundle).mkdir(parents=True)
        stats = {}
        for key, scope in scopes.items():
            path = stage / files[key]
            path.write_bytes(gzip.compress(json_bytes(scope.export()), compresslevel=6, mtime=0))
            stats[key] = dict(zip(COHORTS, scope.samples.sum(axis=1).tolist()))
        (stage / index_name).write_bytes(json_bytes({"version": args.version, "events_version": args.event_version,
            "countries": event_data["countries"], "fields": METRICS, "files": files}))
        sources = (event_asset, spatial_path, atlas_index, panel_path, climate_path, lunar_path, Path(__file__))
        manifest = {"version": args.version, "dates_epoch": EPOCH.isoformat(), "cohorts": stats,
                    "inputs": [{"path": project_path(path), "sha256": sha(path)} for path in sources],
                    "products": [{"file": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}
                                 for path in sorted(stage.rglob("*")) if path.is_file()],
                    "rules": ["Uma observação por trecho de 25 km e data em cada série.",
                              "Sem registro exige attack=0 na v006, inclusive com o filtro de datas exatas ligado.",
                              "País/área seleciona trechos com algum ataque atribuído ao rótulo. Um trecho pode aparecer em mais de um país/área.",
                              "A série positiva do país usa só datas com ataque atribuído ao país; a série global conta cada trecho-dia uma vez.",
                              "As médias no site usam somas e contagens de valores disponíveis por dia para agregar qualquer intervalo."]}
        (stage / f"atlas_comparacao_manifesto_{args.version}.json").write_bytes(json_bytes(manifest))
        shutil.copytree(stage, output)
        shutil.copytree(stage / bundle, DIST / bundle)
        shutil.copyfile(stage / index_name, DIST / index_name)
    print(json.dumps({"scopes": len(scopes), "global": stats["all"], "files": len(files),
                      "bytes": sum(entry["bytes"] for entry in manifest["products"])}))


if __name__ == "__main__":
    main()
