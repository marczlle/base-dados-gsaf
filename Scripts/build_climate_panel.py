"""Extract hourly ERA5 from an immutable Icechunk snapshot and aggregate by local day."""

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import lru_cache
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import icechunk
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import zarr
from timezonefinder import TimezoneFinder

from data_paths import CLIMATE, COAST, PANEL, SOURCES, project_path, version_dir
from segment_coast import CoastPath


EPOCH = date(1940, 1, 1)
SNAPSHOT = "VKGPX45BPEQJMVZZXZEG"
BUCKET = "earthmover-icechunk-era5"
PREFIX = "icechunkV2"
GROUP = "single/temporal"
VARIABLES = ("t2m", "tp", "u10", "v10")
FIELDS = ("temperature_2m_mean", "precipitation_sum", "wind_speed_10m_mean", "wind_speed_10m_max",
          "wind_direction_10m_dominant", "wind_direction_sin", "wind_direction_cos",
          "precipitation_previous_3d", "precipitation_previous_7d")
SCHEMA = pa.schema([("segment_id", pa.string()), ("date", pa.date32()), ("timezone", pa.string()),
                    *((name, pa.float32()) for name in FIELDS)])
RULES = [
    "Células ERA5 de 0,25° mais próximas do início, centro geodésico e fim de cada trecho. Cada célula distinta tem o mesmo peso.",
    "Fuso IANA encontrado no centro, com busca de terra próxima quando o centro está no mar; último recurso é o fuso náutico.",
    "Temperatura em °C, chuva total em mm e vento em km/h. Calcular médias horárias espaciais antes dos resumos diários.",
    "Velocidade vem de √(u² + v²) em cada célula. Direção meteorológica vem do vetor médio diário, com seno e cosseno derivados.",
    "A chuva etiquetada em t abrange a hora anterior. Atribuí-la pelo ponto médio do intervalo, inclusive em fusos fracionários.",
    "Calcular chuva antecedente usando apenas os 3 ou 7 dias anteriores, com janela completa.",
    "Campos ficam nulos quando faltam horas para a agregação. Horas nunca são preenchidas artificialmente.",
]


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def panel_windows(path, ids, start, end):
    dataset = pq.ParquetFile(path)
    windows = {}
    for index in range(dataset.num_row_groups):
        group = dataset.read_row_group(index, columns=["segment_id", "date"])
        segment, days = group["segment_id"][0].as_py(), group["date"]
        if ids and segment not in ids:
            continue
        first, last = days[0].as_py(), days[-1].as_py()
        first = max(first, start) if start else first
        last = min(last, end) if end else last
        if first <= last:
            windows[segment] = (first, last)
    if not windows or (ids and set(windows) != set(ids)):
        raise ValueError(f"Segmentos sem datas no recorte: {set(ids) - windows.keys()}")
    return windows


def coastal_timezone(finder, lon, lat):
    at_center = finder.timezone_at(lng=lon, lat=lat)
    if at_center and not at_center.startswith("Etc/GMT"):
        return at_center, "center"
    for km in (1, 3, 8, 15):
        offsets = np.linspace(0, math.tau, 16, endpoint=False)
        zones = Counter()
        for angle in offsets:
            lng = (lon + km * math.sin(angle) / (111.2 * max(0.05, math.cos(math.radians(lat)))) + 180) % 360 - 180
            y = max(-90, min(90, lat + km * math.cos(angle) / 111.2))
            zone = finder.timezone_at_land(lng=lng, lat=y)
            if zone:
                zones[zone] += 1
        if zones:
            return zones.most_common(1)[0][0], "nearby_land"
    return at_center or "UTC", "nautical"


def map_segments(geometry, segments, latitudes, longitudes):
    finder = TimezoneFinder(in_memory=True)
    with gzip.open(geometry, "rt", encoding="utf-8") as file:
        features = json.load(file)["features"]
    mappings = {}
    for feature in features:
        segment = feature["id"]
        if segment not in segments:
            continue
        shape = feature["geometry"]
        coordinates = shape["coordinates"]
        if shape["type"] == "MultiLineString":
            coordinates = list(chain.from_iterable(coordinates))
        path = CoastPath(segment, coordinates)
        samples = []
        for name, fraction in (("start", 0), ("center", 0.5), ("end", 1)):
            lon, lat = path.point_at(path.length * fraction)
            y = int(np.argmin(abs(latitudes - lat)))
            x = int(np.argmin(abs((longitudes - lon + 180) % 360 - 180)))
            samples.append((name, lon, lat, y, x))
        zone, method = coastal_timezone(finder, *samples[1][1:3])
        mappings[segment] = (zone, method, samples)
    if set(mappings) != set(segments):
        raise ValueError("Faltam geometrias costeiras de segmentos do painel")
    return mappings


def daily_values(utc, raw, zone, first, last):
    """raw is cell × hour × variable, in ERA5 units."""
    days = pd.date_range(first - timedelta(days=7), last, freq="D")
    local = utc.tz_convert(zone).tz_localize(None).normalize()
    rain_local = (utc - pd.Timedelta(minutes=30)).tz_convert(zone).tz_localize(None).normalize()
    temp, rain, u, v = raw.transpose(2, 0, 1)
    speed = np.hypot(u, v).mean(axis=0) * 3.6
    instant = pd.DataFrame({"temp": temp.mean(axis=0) - 273.15, "speed": speed,
                            "u": u.mean(axis=0), "v": v.mean(axis=0)}, index=local)
    stats = instant.groupby(level=0).agg(["mean", "max", "count", "size"]).reindex(days)
    temperature = stats["temp"]["mean"].where(stats["temp"]["count"] == stats["temp"]["size"])
    wind = stats["speed"].where(stats["speed"]["count"] == stats["speed"]["size"], axis=0)
    u_mean, v_mean = stats["u"]["mean"], stats["v"]["mean"]
    direction = np.arctan2(-u_mean, -v_mean).where(wind["mean"].notna() & (np.hypot(u_mean, v_mean) > 1e-6))
    accum = pd.Series(np.maximum(rain, 0).mean(axis=0) * 1000, index=rain_local).groupby(level=0)
    total = accum.sum().where(accum.count() == accum.size()).reindex(days)
    return pd.DataFrame(dict(zip(FIELDS, [temperature, total, wind["mean"], wind["max"],
                                          np.degrees(direction) % 360, np.sin(direction), np.cos(direction),
                                          total.shift().rolling(3).sum(), total.shift().rolling(7).sum()])), index=days).iloc[7:]


def read_block(arrays, block, cells, cache, chunk_size):
    time_block, y_block, x_block = block
    dt, dy, dx = chunk_size
    cell_tag = hashlib.sha256(repr(cells).encode()).hexdigest()[:16]
    target = cache / f"{time_block}_{y_block}_{x_block}_{cell_tag}.npy"
    if target.is_file():
        return target
    ti, yi, xi = time_block * dt, y_block * dy, x_block * dx
    ys, xs = np.asarray(cells).T
    for attempt in range(3):
        try:
            values = np.stack([array[ti:ti+dt, yi:yi+dy, xi:xi+dx][:, ys-yi, xs-xi].T for array in arrays], axis=-1)
            break
        except (OSError, RuntimeError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    with NamedTemporaryFile(dir=cache, suffix=".tmp", delete=False) as file:
        pending = Path(file.name)
        np.save(file, values, allow_pickle=False)
    try:
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return target


def extract(root, windows, mappings, cache_dir, workers, temp, version):
    arrays = [root[key] for key in VARIABLES]
    chunk_size = dt, dy, dx = arrays[0].chunks
    if any(array.chunks != chunk_size or array.shape != arrays[0].shape for array in arrays):
        raise ValueError("Grade ou blocos ERA5 incompatíveis entre variáveis")
    source_hours = arrays[0].shape[0]
    blocks, requests = defaultdict(set), {}
    for segment, (first, last) in sorted(windows.items()):
        grid = sorted({(y, x) for _, _, _, y, x in mappings[segment][2]})
        start = (first - EPOCH).days * 24 - 8 * 24
        stop = (last - EPOCH).days * 24 + 2 * 24
        chunks = range(max(0, start) // dt, (min(stop, source_hours) - 1) // dt + 1)
        requests[segment] = (start, stop, grid, chunks)
        for y, x in grid:
            for index in chunks:
                blocks[index, y // dy, x // dx].add((y, x))
    blocks = {key: sorted(cells) for key, cells in blocks.items()}
    print(f"ERA5: {len(windows)} trechos, {len(blocks)} blocos de 4 variáveis.", flush=True)
    cached_files = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda pair: read_block(arrays, *pair, cache_dir, chunk_size), blocks.items())
        for number, (key, path) in enumerate(zip(blocks, results), 1):
            cached_files[key] = path
            if number % 100 == 0 or number == len(blocks):
                print(f"ERA5: {number}/{len(blocks)} blocos lidos.", flush=True)

    @lru_cache(maxsize=24)
    def from_cache(key):
        return np.load(cached_files[key], mmap_mode="r", allow_pickle=False)

    statistics = Counter()
    path = temp / f"gsaf_clima_diario_25km_{version}.parquet"
    with pq.ParquetWriter(path, SCHEMA, compression="zstd") as writer:
        for segment, (start, stop, grid, chunks) in requests.items():
            raw = np.full((len(grid), stop - start, len(VARIABLES)), np.nan, dtype=np.float32)
            for ci, (y, x) in enumerate(grid):
                for index in chunks:
                    key = (index, y // dy, x // dx)
                    block_start = index * dt
                    a, b = max(block_start, start), min(block_start + dt, stop, source_hours)
                    raw[ci, a-start:b-start] = from_cache(key)[blocks[key].index((y, x)), a-block_start:b-block_start]
            utc = pd.date_range(pd.Timestamp(EPOCH, tz="UTC") + pd.Timedelta(hours=start), periods=stop-start, freq="h")
            zone = mappings[segment][0]
            daily = daily_values(utc, raw, zone, *windows[segment])
            n = len(daily)
            writer.write_batch(pa.RecordBatch.from_arrays([
                pa.repeat(pa.scalar(segment), n), pa.array(daily.index.date, type=pa.date32()), pa.repeat(pa.scalar(zone), n),
                *(pa.array(daily[field], type=pa.float32(), from_pandas=True) for field in FIELDS),
            ], schema=SCHEMA))
            statistics["rows"] += n
            statistics.update({field: int(daily[field].isna().sum()) for field in FIELDS})
    if pq.read_metadata(path).num_rows != sum((last - first).days + 1 for first, last in windows.values()):
        raise RuntimeError("Contagem diária não coincide com o painel de entrada")
    return path, statistics, len(blocks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--panel-version", default="v006")
    parser.add_argument("--coast-version", default="v005")
    parser.add_argument("--snapshot", default=SNAPSHOT)
    parser.add_argument("--segment", action="append", default=[])
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not all(re.fullmatch(r"v\d{3,}", ver) for ver in (args.version, args.panel_version, args.coast_version)):
        parser.error("Use versões vNNN")
    if not re.fullmatch(r"[A-Z0-9]{20}", args.snapshot) or args.workers < 1:
        parser.error("Snapshot ou número de workers inválido")

    panel = version_dir(PANEL, args.panel_version) / f"gsaf_painel_diario_25km_{args.panel_version}.parquet"
    geometry = version_dir(COAST, args.coast_version) / f"gsaf_segmentos_25km_{args.coast_version}.geojson.gz"
    output = version_dir(CLIMATE, args.version)
    if output.exists():
        raise FileExistsError(f"Versão de saída já existe: {output}")
    repo = icechunk.Repository.open(icechunk.s3_storage(bucket=BUCKET, prefix=PREFIX, region="us-east-1", anonymous=True))
    session = repo.readonly_session(snapshot_id=args.snapshot)
    root = zarr.open_group(session.store, path=GROUP, mode="r", use_consolidated=False)
    utc_axis = root["valid_time"][:]
    if not np.array_equal(utc_axis, np.arange(len(utc_axis))) or not root["valid_time"].attrs["units"].startswith("hours since 1940-01-01"):
        raise ValueError("Eixo de horas do ERA5 inesperado")
    latitudes, longitudes = root["latitude"][:], root["longitude"][:]
    windows = panel_windows(panel, args.segment, args.start, args.end)
    mappings = map_segments(geometry, windows, latitudes, longitudes)
    cache = SOURCES / "era5" / ".cache" / args.snapshot
    cache.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".era5_") as directory:
        temp = Path(directory)
        climate, stats, block_count = extract(root, windows, mappings, cache, args.workers, temp, args.version)
        grid_path = temp / f"gsaf_clima_grade_25km_{args.version}.csv"
        with grid_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["segment_id", "timezone", "timezone_method", "point", "point_lat", "point_lon", "era5_lat", "era5_lon"])
            for segment, (zone, method, points) in sorted(mappings.items()):
                for name, lon, lat, y, x in points:
                    writer.writerow([segment, zone, method, name, round(lat, 6), round(lon, 6), float(latitudes[y]),
                                     float((longitudes[x] + 180) % 360 - 180)])
        report = temp / f"gsaf_clima_25km_relatorio_{args.version}.md"
        lines = [f"# Clima ERA5 de 25 km — {args.version}", "", f"Trechos processados: {len(windows)}. Linhas: {stats['rows']}.",
                 f"Arquivo horário replicado pela Earthmover. Snapshot Icechunk `{args.snapshot}`. Blocos: {block_count}.",
                 "", "## Regras", "", *(f"- {rule}" for rule in RULES), "", "## Valores ausentes", "",
                 "| Campo | Linhas sem valor |", "| --- | ---: |", *(f"| `{field}` | {stats[field]} |" for field in FIELDS), ""]
        report.write_text("\n".join(lines), encoding="utf-8")
        manifest = temp / f"gsaf_clima_25km_manifesto_{args.version}.json"
        manifest.write_text(json.dumps({"version": args.version, "snapshot": args.snapshot, "bucket": BUCKET,
            "prefix": PREFIX, "group": GROUP, "variables": VARIABLES, "segments": len(windows), "counts": dict(stats),
            "date_range": [str(min(first for first, _ in windows.values())), str(max(last for _, last in windows.values()))],
            "source_utc_hour_range": [0, int(utc_axis[-1])], "blocks": block_count, "rules": RULES,
            "inputs": [{"path": project_path(path), "sha256": sha(path)} for path in (geometry, panel, Path(__file__))],
            "products": [{"file": path.name, "sha256": sha(path)} for path in (climate, grid_path, report)]},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output.mkdir()
        published = []
        try:
            for product in (climate, grid_path, report, manifest):
                destination = output / product.name
                os.link(product, destination)
                published.append(destination)
        except BaseException:
            for path in published:
                path.unlink()
            output.rmdir()
            raise
    print(f"Clima publicado em {output}.", flush=True)


if __name__ == "__main__":
    main()
