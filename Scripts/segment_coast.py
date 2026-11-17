"""Etapa 2: segmentar a costa Natural Earth e vincular eventos GSAF.

Dependências: numpy, scipy, shapely >= 2, pyshp. Os ZIPs originais Natural Earth
ficam em Data/fontes/natural_earth. O manifesto identifica as entradas usadas.
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import NamedTuple

import numpy as np
import shapefile
from scipy.spatial import cKDTree
from shapely import MultiLineString, Point, Polygon, box, line_merge
from shapely.geometry import shape
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from data_paths import ATLAS, CLEAN, COAST, SOURCES, project_path, version_dir

NATURAL_EARTH = SOURCES / "natural_earth"
R = 6371.0088  # raio terrestre médio, km
SCALES = (10, 25, 50)
MIN_DAYS = 10
MAX_BASE = 4
COUNTRY_TOLERANCE_KM = 10
DEFAULT_MAX_DISTANCE_KM = 25
DEFAULT_EXTENDED_DISTANCE_KM = 75
ADMIN1 = ("natural_earth_admin1_states_provinces_10m", "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip", "5.1.1")
ASSETS = {
    "coast": ("natural_earth_coastline_10m", "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_coastline.zip", "4.1.0"),
    "islands": ("natural_earth_minor_islands_coastline_10m", "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_minor_islands_coastline.zip", "4.1.0"),
    "countries": ("natural_earth_admin0_map_units_10m", "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_map_units.zip", "5.1.1"),
}

COUNTRY_ALIASES = {
    "ANDAMAN / NICOBAR ISLANDAS": ("INDIA",),
    "ANTIGUA": ("ANTIGUA AND BARBUDA",),
    "AZORES": ("PORTUGAL",),
    "BRITISH ISLES": ("UNITED KINGDOM", "IRELAND", "ISLE OF MAN"),
    "CAPE VERDE": ("CABO VERDE",),
    "DIEGO GARCIA": ("BRITISH INDIAN OCEAN TERRITORY",),
    "EGYPT / ISRAEL": ("EGYPT", "ISRAEL"),
    "IRAN / IRAQ": ("IRAN", "IRAQ"),
    "JOHNSTON ISLAND": ("JOHNSTON ATOLL",),
    "MICRONESIA": ("FEDERATED STATES OF MICRONESIA", "MICRONESIA"),
    "NETHERLANDS ANTILLES": ("CURACAO", "BONAIRE", "SINT MAARTEN", "SABA", "SINT EUSTATIUS"),
    "NEW GUINEA": ("PAPUA NEW GUINEA", "INDONESIA"),
    "PALESTINIAN TERRITORIES": ("PALESTINE", "GAZA"),
    "SAINT KITTS AND NEVIS": ("SAINT KITTS AND NEVIS", "ST KITTS AND NEVIS"),
    "SAINT MARTIN": ("SAINT MARTIN", "ST MARTIN"),
    "SOLOMON ISLANDS / VANUATU": ("SOLOMON ISLANDS", "VANUATU"),
    "ST HELENA, BRITISH OVERSEAS TERRITORY": ("SAINT HELENA", "ST HELENA", "ASCENSION"),
    "TURKEY": ("TURKEY", "TURKIYE"),
    "US VIRGIN ISLANDS": ("US VIRGIN ISLANDS", "UNITED STATES VIRGIN ISLANDS", "VIRGIN ISLANDS U S"),
    "USA": ("USA", "UNITED STATES OF AMERICA", "UNITED STATES"),
}

# These aliases only apply when the record itself names the territory as its
# state/region. They cannot authorize, for example, a California row in Guam.
US_INSULAR_SOURCE = "https://www.doi.gov/oia/islands/politicatypes"
US_PACIFIC_SOURCE = "https://www.fws.gov/national-monument/pacific-islands-heritage-marine"
TERRITORIES = {
    ("USA", "PUERTO RICO"): ("PUERTO RICO", US_INSULAR_SOURCE),
    ("USA", "GUAM"): ("GUAM", US_INSULAR_SOURCE),
    ("USA", "US VIRGIN ISLANDS"): ("UNITED STATES VIRGIN ISLANDS", US_INSULAR_SOURCE),
    ("USA", "VIRGIN ISLANDS"): ("UNITED STATES VIRGIN ISLANDS", US_INSULAR_SOURCE),
    ("USA", "PALMYRA ATOLL"): ("PALMYRA ATOLL", US_PACIFIC_SOURCE),
    ("USA", "JOHNSTON ATOLL"): ("JOHNSTON ATOLL", US_INSULAR_SOURCE),
    ("USA", "MIDWAY ATOLL"): ("MIDWAY ATOLL", US_INSULAR_SOURCE),
    ("USA", "WAKE ISLAND"): ("WAKE ATOLL", US_PACIFIC_SOURCE),
    ("AUSTRALIA", "TERRITORY OF COCOS KEELING ISLANDS"): (
        "CCK", "https://www.ga.gov.au/scientific-topics/national-location-information/geography/external-territories"),
}

COASTAL_WORDS = frozenset("BEACH BEACHES PRAIA PLAYA PLAGE SPIAGGIA STRAND REEF REEFS RECIFE ATOLL CAY KEY ISLET COAST SHORE BAY CAPE HEADLAND POINT WHARF PIER HARBOR HARBOUR INLET LAGOON ARCHIPELAGO ISLAND ISLANDS ISLA ISOLA ILHA".split())
GENERIC_WORDS = COASTAL_WORDS | frozenset("NORTH SOUTH EAST WEST NORTHERN SOUTHERN EASTERN WESTERN NEAR OFF OF THE ON AT AND DE DA DO DEL LAS LOS UNKNOWN UNSPECIFIED OPEN SEA OCEAN CENTRAL INNER OUTER SMALL BIG MOUTH RIVER KM MI MILE MILES A AN LA EL".split())
NON_COASTAL = re.compile(r"\b(?:WATER PARK|WATERPARK|AQUARIUM|SHARK TANK|SWIMMING POOL|INLAND|FRESH WATER|FRESHWATER|LAKE|WRECK|FISHING VESSEL)\b")
RIVER = re.compile(r"\b(?:RIVER|RIO|RIVIERE)\b")
RIVER_OUTLET = re.compile(r"\b(?:MOUTH|ESTUARY|ESTUARIO|FOZ|EMBOUCHURE)\b")
ISLAND_WORDS = frozenset("ISLAND ISLANDS ISLET ATOLL CAY ARCHIPELAGO ISLA ISOLA ILHA".split())


class Assignment(NamedTuple):
    coast: str | None
    along: float | None
    snap: tuple | None
    distance: float | None
    status: str
    detail: str
    method: str | None = None
    source: str | None = None
    note: str | None = None


def read_ne(path):
    with zipfile.ZipFile(path) as archive:
        stem = next(n[:-4] for n in archive.namelist() if n.endswith(".shp"))
        return shapefile.Reader(**{
            ext: io.BytesIO(archive.read(stem + "." + ext))
            for ext in ("shp", "shx", "dbf")
        }, encoding="utf-8")


def unit(lon_lat):
    ll = np.radians(lon_lat)
    lon, lat = ll[..., 0], ll[..., 1]
    return np.stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=-1)


def lon_lat(v):
    x, y, z = v
    return (math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y))))


def km(a, b):
    return 2 * R * np.arcsin(np.minimum(1, np.linalg.norm(a - b, axis=-1) / 2))


def interpolate(a, b, fraction, angle):
    if angle < 1e-12:
        return a
    return (math.sin((1 - fraction) * angle) * a + math.sin(fraction * angle) * b) / math.sin(angle)


def canonical(coords):
    pts = tuple((float(x), float(y)) for x, y in coords)
    if pts[0] != pts[-1]:
        return min(pts, pts[::-1])
    ring = pts[:-1]
    start = min(range(len(ring)), key=ring.__getitem__)
    ring = ring[start:] + ring[:start]
    return min(ring + ring[:1], ring[:1] + ring[:0:-1] + ring[:1])


def coastline(paths):
    lines = []
    for path in paths:
        for record in read_ne(path).iterShapes():
            starts = list(record.parts) + [len(record.points)]
            for begin, end in zip(starts, starts[1:]):
                coords = record.points[begin:end]
                if len(coords) >= 2:
                    # Duplicated vertices don't contribute to coastline length.
                    coords = [p for i, p in enumerate(coords) if i == 0 or p != coords[i - 1]]
                    if len(coords) >= 2:
                        lines.append(coords)
    merged = line_merge(MultiLineString(lines))
    paths = sorted({canonical(line.coords) for line in merged.geoms if line.length > 0})
    return [CoastPath(f"C{i:05d}", path) for i, path in enumerate(paths, 1)]


class CoastPath:
    def __init__(self, coast_id, coordinates):
        self.id = coast_id
        self.closed = coordinates[0] == coordinates[-1]
        original = np.asarray(coordinates)
        vec = unit(original)
        dist = km(vec[:-1], vec[1:])
        # Bound the nearest-index search for any very sparse source edge.
        dense = [coordinates[0]]
        for i, d in enumerate(dist):
            if d <= 1e-8:
                continue
            pieces = math.ceil(d / 8)
            for k in range(1, pieces):
                dense.append(lon_lat(interpolate(vec[i], vec[i + 1], k / pieces, d / R)))
            dense.append(coordinates[i + 1])
        self.coordinates = np.asarray(dense)
        self.vec = unit(self.coordinates)
        self.edges = km(self.vec[:-1], self.vec[1:])
        self.cumulative = np.r_[0, np.cumsum(self.edges)]
        self.length = float(self.cumulative[-1])

    def point_at(self, distance):
        if distance <= 0:
            return self.coordinates[0].tolist()
        if distance >= self.length:
            return self.coordinates[-1].tolist()
        i = int(np.searchsorted(self.cumulative, distance, side="right") - 1)
        return list(lon_lat(interpolate(self.vec[i], self.vec[i + 1],
                                        (distance - self.cumulative[i]) / self.edges[i], self.edges[i] / R)))

    def cut(self, scale):
        results = []
        for i in range(math.ceil(self.length / scale)):
            start, end = scale * i, min(scale * (i + 1), self.length)
            middle = self.coordinates[np.searchsorted(self.cumulative, start, side="right"):
                                      np.searchsorted(self.cumulative, end, side="left")].tolist()
            coords = [self.point_at(start), *middle, self.point_at(end)]
            # Keep tiny islands visible in high zoom, even if endpoints round to the same point.
            coords = [[round(x, 6), round(y, 6)] for x, y in coords]
            results.append({
                "id": f"{self.id}-{scale}-{i + 1:04d}", "coordinates": coords,
                "length_km": round(end - start, 4), "coast_id": self.id,
                "event_count": 0, "positive_days": 0, "region_id": None, "model_eligible": False,
            })
        return results


class CoastIndex:
    def __init__(self, paths):
        self.paths = paths
        self.a = np.concatenate([p.vec[:-1] for p in paths])
        self.b = np.concatenate([p.vec[1:] for p in paths])
        normals = np.cross(self.a, self.b)
        self.normal = normals / np.linalg.norm(normals, axis=1)[:, None]
        self.start_tangent = np.cross(self.normal, self.a)
        self.end_tangent = np.cross(self.b, self.normal)
        mid = self.a + self.b
        self.tree = cKDTree(mid / np.linalg.norm(mid, axis=1)[:, None])
        self.path_indices = np.repeat(np.arange(len(paths)), [len(p.edges) for p in paths])
        self.cumulative = np.concatenate([p.cumulative[:-1] for p in paths])
        self.max_half_edge = max(float(max(p.edges)) for p in paths) / 2

    def foot(self, point, indices):
        a, b, n = self.a[indices], self.b[indices], self.normal[indices]
        perpendicular = point - (n @ point)[:, None] * n
        lengths = np.linalg.norm(perpendicular, axis=1)
        near = perpendicular / np.maximum(lengths[:, None], 1e-15)
        in_arc = ((near * self.start_tangent[indices]).sum(axis=1) >= -1e-12) & (
            (near * self.end_tangent[indices]).sum(axis=1) >= -1e-12) & (lengths > 1e-15)
        endpoints = np.where(((a - b) @ point >= 0)[:, None], a, b)
        selected = np.where(in_arc[:, None], near, endpoints)
        distances = km(point, selected)
        i = int(np.argmin(distances))
        return int(indices[i]), selected[i], float(distances[i])

    def nearest(self, longitude, latitude):
        point = unit(np.array([longitude, latitude]))
        _, initial = self.tree.query(point)
        _, _, bound = self.foot(point, [initial])
        # Every closer arc has its midpoint inside this spherical search radius.
        radius = 2 * math.sin(min(math.pi, (bound + self.max_half_edge) / R) / 2) + 1e-12
        choices = sorted(self.tree.query_ball_point(point, radius))
        edge, projected, distance = self.foot(point, choices)
        path = self.paths[self.path_indices[edge]]
        along = min(path.length, float(self.cumulative[edge] + km(self.a[edge], projected)))
        return path, along, lon_lat(projected), distance


def norm_label(label):
    text = unicodedata.normalize("NFKD", str(label).upper())
    return " ".join(re.findall(r"[A-Z0-9]+", "".join(c for c in text if not unicodedata.combining(c))))


def known_country_aliases(label):
    label = norm_label(label)
    return {norm_label(name) for name in next((names for key, names in COUNTRY_ALIASES.items()
                                              if norm_label(key) == label), (label,))} - {""}


class StateCheck:
    """Approximate corroboration; missing historical labels are not mismatches."""

    def __init__(self, archive):
        self.units = defaultdict(list)
        for row in read_ne(archive).iterShapeRecords():
            data = row.record.as_dict()
            countries = {norm_label(data.get(key, "")) for key in ("admin", "geonunit", "adm0_a3", "gu_a3")}
            names = {norm_label(data.get(key, "")) for key in ("name", "name_en", "name_es", "name_pt", "woe_name")}
            names.update(norm_label(name) for name in str(data.get("name_alt", "")).split("|"))
            geom = shape(row.shape.__geo_interface__)
            for country in countries - {"", "99"}:
                for name in names - {"", "99"}:
                    self.units[(country, name)].append(geom)

    def check(self, country, state, snapped):
        name = norm_label(state)
        if not name:
            return None
        stripped = re.sub(r"\s+(?:PROVINCE|PREFECTURE|STATE|REGION)$", "", name)
        matches = [g for alias in known_country_aliases(country) for variant in {name, stripped}
                   for g in self.units.get((alias, variant), ())]
        if not matches:
            return None
        lon, lat = snapped
        for shift in (0, -360, 360) if abs(lon) > 179.5 else (0,):
            point = Point(lon + shift, lat)
            for geom in matches:
                closest = nearest_points(point, geom)[1]
                if km(unit([lon, lat]), unit([closest.x, closest.y])) <= COUNTRY_TOLERANCE_KM:
                    return True
        return False


def read_reviewed(path):
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            key = tuple(norm_label(row[name]) for name in ("country", "state", "location"))
            if key in result or not all(key) or not row["source_url"].startswith("https://"):
                raise ValueError(f"Entrada revisada inválida/duplicada: {key}")
            row["max_distance_km"] = float(row["max_distance_km"])
            if not 0 < row["max_distance_km"] <= DEFAULT_MAX_DISTANCE_KM:
                raise ValueError(f"Limite inválido para topônimo revisado: {key}")
            result[key] = row
    return result


def stated_distance_above(label, maximum):
    for raw, units in re.findall(r"\b(\d+(?:[.,]\d+)?)\s*(NAUTICAL MILES?|NM|MILES?|MI|KILOMET(?:ER|RE)S?|KM)\b", label.upper()):
        factor = 1.852 if units.startswith("NAUTICAL") or units == "NM" else 1.609344 if units.startswith("MI") else 1
        if float(raw.replace(",", ".")) * factor > maximum:
            return True
    return False


def point_key(event):
    return (round(event["lon"], 4), round(event["lat"], 4))


def locality_key(event):
    # Common suffixes such as ', DUVAL COUNTY' do not make a different locality.
    return norm_label(event["location"].split(",", 1)[0])


def extension_evidence(event, path, shared_points, maximum):
    place = norm_label(event["location"])
    tokens = set(place.split())
    context = f"{norm_label(event['state'])} {place}"
    if not place or not (tokens & COASTAL_WORDS) or not (tokens - GENERIC_WORDS):
        return "extended_requires_named_coastal_locality"
    if place in (norm_label(event["state"]), norm_label(event["country"])):
        return "extended_requires_named_coastal_locality"
    if NON_COASTAL.search(context) or (RIVER.search(place) and not RIVER_OUTLET.search(place)):
        return "extended_explicit_noncoastal_context"
    if stated_distance_above(f"{event['state']} {event['location']}", maximum):
        return "extended_text_distance_above_limit"
    if len(shared_points[point_key(event)]) > 1:
        return "extended_shared_geocode"
    # Do not replace a named island with an unrelated coast. If the source is
    # already inside the represented island, its shoreline is a valid proxy.
    if tokens & ISLAND_WORDS:
        if not path.closed or path.length > 3500 or np.ptp(path.coordinates[:, 0]) > 180:
            return "extended_island_unverified"
        if not Polygon(path.coordinates).covers(Point(event["lon"], event["lat"])):
            return "extended_island_unverified"
    return None


class CountryCheck:
    def __init__(self, archive):
        self.polygons = []
        self.keys = []
        self.known = set()
        for row in read_ne(archive).iterShapeRecords():
            record = row.record.as_dict()
            names = {norm_label(record.get(field, "")) for field in (
                "ADMIN", "GEOUNIT", "SUBUNIT", "NAME", "NAME_LONG", "NAME_EN", "BRK_NAME",
                "ISO_A3", "ADM0_A3", "GU_A3", "SU_A3",
            )} - {"", "99", "NONE"}
            self.known.update(names)
            geom = shape(row.shape.__geo_interface__)
            for polygon in geom.geoms if geom.geom_type == "MultiPolygon" else [geom]:
                self.polygons.append(polygon)
                self.keys.append(names)
        self.tree = STRtree(self.polygons)

    def check(self, label, longitude, latitude, snapped):
        aliases = known_country_aliases(label) & self.known
        if not aliases:
            return "country_unverified", "country_not_mapped" if label else "country_missing"
        lon, lat = snapped
        # One conservative envelope for the near-shore polygon test at any latitude.
        pad_y = COUNTRY_TOLERANCE_KM / 110
        pad_x = pad_y / max(0.01, math.cos(math.radians(abs(lat) + pad_y)))
        for shift in (0, -360, 360) if abs(lon) >= 180 - pad_x else (0,):
            x = lon + shift
            point = Point(x, lat)
            ids = self.tree.query(box(x - pad_x, lat - pad_y, x + pad_x, lat + pad_y))
            for i in ids:
                if not aliases.intersection(self.keys[i]):
                    continue
                polygon = self.polygons[i]
                near = nearest_points(point, polygon)[1]
                if km(unit([lon, lat]), unit([near.x, near.y])) <= COUNTRY_TOLERANCE_KM:
                    return "assigned", "country_near_snap"
        # The original point is useful when the nearest coastline is across a border/strait.
        original = Point(longitude, latitude)
        expected_land = any(aliases.intersection(self.keys[i]) for i in self.tree.query(original, predicate="within"))
        return "country_mismatch", "snap_outside_expected_country" if expected_land else "point_and_snap_outside_expected_country"


def read_events(path):
    with path.open(encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    events = []
    for row in rows:
        approx = int(row["date_is_approximate"])
        date.fromisoformat(row["date"])
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                lat = lon = None
        except (ValueError, TypeError):
            lat = lon = None
        events.append({
            "id": row["record_id"], "date": row["date"], "country": row["country"],
            "state": row["state"], "location": row["location"], "lat": lat, "lon": lon,
            "approximate": approx, "date_status": "reported_date" if approx else "exact",
        })
    assert len({r["id"] for r in events}) == len(events), "IDs de eventos repetidos"
    return events


def classify(events, index, country_check, limit, extended_limit, state_check, reviewed):
    result = []
    shared_points = defaultdict(set)
    for event in events:
        if event["lat"] is not None:
            shared_points[point_key(event)].add((norm_label(event["country"]), norm_label(event["state"]), locality_key(event)))
    for event in events:
        if event["lat"] is None:
            result.append(Assignment(None, None, None, None, "no_coordinates", "coordinate_pair_missing_or_invalid"))
            continue
        path, along, snap, distance = index.nearest(event["lon"], event["lat"])
        common = (path.id, along, snap, distance)
        key = tuple(norm_label(event[name]) for name in ("country", "state", "location"))
        if (review := reviewed.get(key)) and path.id == review["coast_id"] and distance <= min(limit, review["max_distance_km"]):
            result.append(Assignment(*common, "assigned", "reviewed_named_coast", "reviewed_toponym", review["source_url"], review["note"]))
            continue
        if distance > extended_limit:
            result.append(Assignment(*common, "outside_distance", "distance_above_extended_limit"))
            continue
        territory = TERRITORIES.get(key[:2])
        expected = territory[0] if territory else event["country"]
        status, detail = country_check.check(expected, event["lon"], event["lat"], snap)
        if distance <= limit:
            if territory and status == "assigned":
                if stated_distance_above(event["location"], extended_limit) or NON_COASTAL.search(norm_label(event["location"])):
                    result.append(Assignment(*common, "outside_distance", "territory_explicit_nonlocal_context"))
                    continue
                result.append(Assignment(*common, "assigned", "named_territory_near_snap", "reviewed_toponym", territory[1],
                                         "O território nomeado no registro coincide com a costa cartografada."))
            else:
                result.append(Assignment(*common, status, detail, "direct_geocode" if status == "assigned" else None))
            continue
        if status != "assigned":
            result.append(Assignment(*common, status, detail))
            continue
        reason = extension_evidence(event, path, shared_points, extended_limit)
        compatible_state = state_check.check(expected, event["state"], snap) if state_check and not territory else None
        if compatible_state is False:
            reason = "extended_state_mismatch"
        if reason:
            result.append(Assignment(*common, "outside_distance", reason))
            continue
        detail = "extended_named_coast_country_state" if compatible_state else "extended_named_coast_country"
        result.append(Assignment(*common, "assigned", detail, "extended_geocode", territory[1] if territory else None,
                                 "Associação provisória a partir do topônimo costeiro e da proximidade do geocódigo; a distância não localiza o incidente."))
    return result


def adaptive(path_segments, event_days, event_counts, closed=False):
    """Deterministic disjoint runs; existing qualifying base segments are reserved."""
    n = len(path_segments)
    active = {i for i, segment in enumerate(path_segments) if event_counts[segment["id"]]}
    protected = {i for i in active if len(event_days[path_segments[i]["id"]]) >= MIN_DAYS}
    used = set(protected)
    regions = [(i,) for i in sorted(protected)]
    candidates = []
    # Enumerating from active endpoints avoids traversing large empty stretches.
    for begin in sorted(active - protected):
        for count in range(2, min(MAX_BASE, n) + 1):
            if not closed and begin + count > n:
                break
            span = tuple((begin + offset) % n for offset in range(count))
            if span[-1] not in active or protected.intersection(span):
                continue
            days = set().union(*(event_days[path_segments[i]["id"]] for i in span))
            candidates.append((span, len(days)))
    # Minimize the number of segments merged for qualified runs; then strongest support.
    for span, _ in sorted((x for x in candidates if x[1] >= MIN_DAYS), key=lambda x: (len(x[0]), -x[1], x[0])):
        if not used.intersection(span):
            regions.append(span)
            used.update(span)
    # Sparse runs stay on the map, and neighboring observations are kept together where possible.
    for span, _ in sorted((x for x in candidates if x[1] < MIN_DAYS), key=lambda x: (-x[1], len(x[0]), x[0])):
        if not used.intersection(span):
            regions.append(span)
            used.update(span)
    regions.extend((i,) for i in sorted(active - used))
    return sorted(regions)


def build_scale(paths, events, classified, scale):
    grouped = {path.id: path.cut(scale) for path in paths}
    segments = [segment for sub in grouped.values() for segment in sub]
    links, regions = [], []
    event_days, event_counts = defaultdict(set), Counter()
    for event, assignment in zip(events, classified):
        coast, along, snap, distance, status, detail, method, source, note = assignment
        candidate = None if coast is None else grouped[coast][min(int(along // scale), len(grouped[coast]) - 1)]["id"]
        segment_id = candidate if status == "assigned" else None
        if segment_id:
            event_days[segment_id].add(event["date"])
            event_counts[segment_id] += 1
        links.append({
            "event_id": event["id"], "segment_id": segment_id, "candidate_segment_id": candidate,
            "distance_km": None if distance is None else round(distance, 4), "status": status, "validation": detail,
            "snap_lat": None if snap is None else round(snap[1], 6), "snap_lon": None if snap is None else round(snap[0], 6),
            "assignment_method": method, "assignment_source": source, "assignment_note": note,
            "spatial_is_approximate": 1 if segment_id else None,
        })
    for segment in segments:
        sid = segment["id"]
        segment["event_count"] = event_counts[sid]
        segment["positive_days"] = len(event_days[sid])
    if scale == 25:
        for path in paths:
            sub = grouped[path.id]
            for span in adaptive(sub, event_days, event_counts, path.closed):
                members = [sub[i]["id"] for i in span]
                days = len(set().union(*(event_days[sid] for sid in members)))
                region_id = f"R-{members[0]}"
                row = {"id": region_id, "segment_ids": members, "event_count": sum(event_counts[sid] for sid in members),
                       "positive_days": days, "model_eligible": days >= MIN_DAYS}
                regions.append(row)
                for i in span:
                    sub[i]["region_id"] = region_id
                    sub[i]["model_eligible"] = row["model_eligible"]
    assert sum(x["event_count"] for x in segments) == sum(x["status"] == "assigned" for x in links)
    assert len({x["id"] for x in segments}) == len(segments)
    if scale == 25:
        assert sum(x["event_count"] for x in regions) == sum(event_counts.values())
        members = [sid for x in regions for sid in x["segment_ids"]]
        assert len(set(members)) == len(members)
        assert all(len(x["segment_ids"]) <= MAX_BASE and x["model_eligible"] == (x["positive_days"] >= MIN_DAYS) for x in regions)
    return {"segments": segments, "links": links, "regions": regions}


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open("x", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_bytes(path, payload):
    with path.open("xb") as fp:
        fp.write(payload)


def geometry_at_dateline(coords):
    parts = [[coords[0]]]
    for a, b in zip(coords, coords[1:]):
        delta = b[0] - a[0]
        if abs(delta) <= 180:
            parts[-1].append(b)
            continue
        boundary = 180 if a[0] >= 0 else -180
        unwrapped_b = b[0] + 360 * (1 if boundary > 0 else -1)
        fraction = (boundary - a[0]) / (unwrapped_b - a[0]) if unwrapped_b != a[0] else 0
        lat = round(a[1] + fraction * (b[1] - a[1]), 6)
        parts[-1].append([boundary, lat])
        parts.append([[-boundary, lat], b])
    parts = [p for p in parts if any(q != p[0] for q in p[1:])]
    if not parts:
        raise ValueError(f"Geometria costeira degenerada: {coords}")
    return {"type": "LineString", "coordinates": parts[0]} if len(parts) == 1 else {"type": "MultiLineString", "coordinates": parts}


def feature(row):
    return {"type": "Feature", "id": row["id"], "properties": {k: v for k, v in row.items() if k != "coordinates"},
            "geometry": geometry_at_dateline(row["coordinates"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=version_dir(CLEAN, "v003") / "gsaf_eventos_modelagem_v003.csv")
    parser.add_argument("--version", default="v005")
    parser.add_argument("--source-version", default="v004")
    parser.add_argument("--max-distance-km", type=float, default=DEFAULT_MAX_DISTANCE_KM)
    parser.add_argument("--extended-distance-km", type=float, default=DEFAULT_EXTENDED_DISTANCE_KM)
    parser.add_argument("--admin1", type=Path, default=NATURAL_EARTH / f"{ADMIN1[0]}_v005.zip")
    parser.add_argument("--reviewed", type=Path, default=SOURCES / "gsaf_toponimos_revisados_v005.csv")
    parser.add_argument("--previous", type=Path, default=version_dir(COAST, "v004") / "gsaf_eventos_segmentos_v004.csv")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]{3,}", args.version) or not re.fullmatch(r"v[0-9]{3,}", args.source_version):
        parser.error("use versões como v004")
    if not 0 < args.max_distance_km <= args.extended_distance_km <= 200:
        parser.error("use 0 < distância padrão <= distância estendida <= 200 km")
    ver = args.version
    coast_dir = version_dir(COAST, ver)
    atlas_dir = version_dir(ATLAS, ver)
    sources = {kind: NATURAL_EARTH / f"{value[0]}_{args.source_version}.zip" for kind, value in ASSETS.items()}
    expected = [f"atlas_indice_{ver}.json", f"gsaf_eventos_segmentos_{ver}.csv", f"gsaf_regioes_adaptativas_{ver}.csv",
                f"gsaf_segmentacao_relatorio_{ver}.md", f"gsaf_segmentacao_manifesto_{ver}.json",
                f"gsaf_segmentacao_transicoes_{ver}.csv"]
    expected += [f"{base}_{scale}km_{ver}.{ext}" for scale in SCALES for base, ext in (
        ("atlas_segmentos", "json"), ("gsaf_segmentos", "geojson.gz"))]
    products = {name: (atlas_dir if name.startswith("atlas_") else coast_dir) / name for name in expected}
    if collision := [project_path(path) for path in products.values() if path.exists()]:
        raise FileExistsError(f"A execução nunca sobrescreve versões: {collision}")
    events = read_events(args.input)
    paths = coastline([sources["coast"], sources["islands"]])
    print(f"{len(paths):,} cadeias costeiras; {sum(p.length for p in paths):,.0f} km", flush=True)
    reviewed = read_reviewed(args.reviewed)
    if invalid := {r["coast_id"] for r in reviewed.values()} - {p.id for p in paths}:
        raise ValueError(f"Cadeias revisadas não encontradas na geometria: {sorted(invalid)}")
    classified = classify(events, CoastIndex(paths), CountryCheck(sources["countries"]), args.max_distance_km,
                          args.extended_distance_km, StateCheck(args.admin1), reviewed)
    statuses = Counter(row.status for row in classified)
    methods = Counter(row.method for row in classified if row.method)
    with args.previous.open(encoding="utf-8-sig", newline="") as fp:
        old = {r["event_id"]: r for r in csv.DictReader(fp) if r["scale_km"] == "25"}
    transitions = []
    for event, row in zip(events, classified):
        before = old.get(event["id"], {})
        transitions.append({"event_id": event["id"], "country": event["country"], "state": event["state"],
                            "location": event["location"], "old_status": before.get("status"),
                            "old_validation": before.get("validation"), "new_status": row.status,
                            "new_validation": row.detail, "assignment_method": row.method,
                            "distance_km": None if row.distance is None else round(row.distance, 4),
                            "assignment_source": row.source, "assignment_note": row.note})
    gained = sum(r["old_status"] not in (None, "assigned") and r["new_status"] == "assigned" for r in transitions)
    lost = sum(r["old_status"] == "assigned" and r["new_status"] != "assigned" for r in transitions)
    print(dict(statuses), flush=True)
    coast_dir.mkdir(parents=True, exist_ok=True)
    atlas_dir.mkdir(parents=True, exist_ok=True)
    max_counts = {limit: sum(row[3] is not None and row[3] <= limit for row in classified) for limit in (10, 25, 50)}
    all_links, files, scale_stats = [], {}, {}
    source_ref = [{"file": p.name, "path": project_path(p), "sha256": sha(p), "url": ASSETS[key][1], "source_version": ASSETS[key][2]}
                  for key, p in sources.items()]
    source_ref += [{"file": args.admin1.name, "path": project_path(args.admin1), "sha256": sha(args.admin1), "url": ADMIN1[1], "source_version": ADMIN1[2]},
                   {"file": args.reviewed.name, "path": project_path(args.reviewed), "sha256": sha(args.reviewed)},
                   {"file": args.previous.name, "path": project_path(args.previous), "sha256": sha(args.previous), "role": "baseline_comparison"}]
    for scale in SCALES:
        result = build_scale(paths, events, classified, scale)
        features = [feature(row) for row in result["segments"]]
        path = coast_dir / f"gsaf_segmentos_{scale}km_{ver}.geojson.gz"
        write_bytes(path, gzip.compress(json_bytes({"type": "FeatureCollection", "features": features}), compresslevel=5, mtime=0))
        file = f"atlas_segmentos_{scale}km_{ver}.json"
        write_bytes(atlas_dir / file, json_bytes(result))
        files[str(scale)] = file
        scale_stats[scale] = {"segments": len(result["segments"]), "active_segments": sum(row["event_count"] > 0 for row in result["segments"])}
        if scale == 25:
            regions = result["regions"]
            write_csv(coast_dir / f"gsaf_regioes_adaptativas_{ver}.csv", [{**r, "segment_ids": ";".join(r["segment_ids"])} for r in regions])
        all_links += [{"scale_km": scale, "date": event["date"], "date_status": event["date_status"],
                       "date_is_approximate": event["approximate"], **link,
                       "original_lat": event["lat"], "original_lon": event["lon"]}
                      for event, link in zip(events, result["links"])]
        print(f"{scale} km: {scale_stats[scale]}", flush=True)
    write_csv(coast_dir / f"gsaf_eventos_segmentos_{ver}.csv", all_links)
    write_csv(coast_dir / f"gsaf_segmentacao_transicoes_{ver}.csv", transitions)
    write_bytes(atlas_dir / f"atlas_indice_{ver}.json", json_bytes({
        "version": ver, "years": [int(min(e["date"] for e in events)[:4]), int(max(e["date"] for e in events)[:4])],
        "events": events, "scales": list(SCALES), "files": files, "source": "Natural Earth 1:10m", "max_distance_km": args.max_distance_km,
        "extended_distance_km": args.extended_distance_km, "status_counts": statuses, "scale_stats": scale_stats,
        "assignment_method_counts": methods,
    }))
    rules = {
        "max_distance_km": args.max_distance_km, "country_tolerance_km": COUNTRY_TOLERANCE_KM,
        "geodesy": "great-circle arcs on sphere with mean radius 6371.0088 km",
        "segment_sizes_km": SCALES, "adaptive_max_segments": MAX_BASE, "adaptive_min_distinct_days": MIN_DAYS,
        "adaptive_only_scale_km": 25, "country_unverified": "review_only",
        "country_aliases": COUNTRY_ALIASES, "limit_sensitivity_without_country_check": max_counts,
        "extended_distance_km": args.extended_distance_km,
        "extension": "Named coastal locality, compatible country and mapped state if available; block explicit noncoastal or remote context, shared geocodes and unverified island proxies.",
        "reviewed_toponyms": args.reviewed.name,
        "territory_aliases": [{"country": key[0], "state": key[1], "map_label": value[0], "url": value[1]} for key, value in TERRITORIES.items()],
        "spatial_is_approximate": "All assigned locations derive from approximate geocodes; distance_km is geocode to selected shoreline.",
    }
    regions_eligible = sum(row["model_eligible"] for row in regions)
    eligible_events = sum(row["event_count"] for row in regions if row["model_eligible"])
    text = [f"# Segmentação costeira — {ver}", "", f"Data de execução: {args.as_of:%d/%m/%Y}.", "",
            "Fontes: [linhas costeiras e ilhas menores Natural Earth](https://www.naturalearthdata.com/downloads/10m-physical-vectors/) "
            "e [unidades cartográficas administrativas](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-details/), "
            "todas na escala 1:10 milhões. A fonte inclui costa oceânica, não margens interiores de lagos e rios. "
            "Fronteiras administrativas atuais de facto são um controle aproximado; não reconstituem territórios históricos.", "",
            f"Foram preservados os {len(events)} eventos da fonte, dos quais {sum(e['approximate'] for e in events)} têm data Reported. "
            "Cada evento recebe uma linha por escala no CSV de correspondência. Candidatos rejeitados permanecem rastreáveis.", "",
            "| Resultado | Eventos por escala |", "| --- | ---: |"]
    text += [f"| `{s}` | {statuses[s]} |" for s in ("assigned", "no_coordinates", "outside_distance", "country_mismatch", "country_unverified")]
    text += ["", "| Método de atribuição | Eventos por escala |", "| --- | ---: |"]
    text += [f"| `{s}` | {methods[s]} |" for s in ("direct_geocode", "reviewed_toponym", "extended_geocode")]
    text += ["", f"Comparação com `{args.previous.name}`: {gained} recuperados e {lost} antes atribuídos agora em revisão.",
             f"A trilha por evento está em `gsaf_segmentacao_transicoes_{ver}.csv`. ",
             "Farallon: a linha costeira contém um trecho insular, mas o mapa administrativo omite as ilhas. "
             "Os vínculos do arquipélago usam a geometria disponível como referência; a ilha norte não recebe uma coordenada inventada. "
             "O [U.S. Fish & Wildlife Service](https://www.fws.gov/refuge/farallon-islands/about-us) confirma o arquipélago na Califórnia.", ""]
    text += ["", "| Escala | Segmentos | Com evento atribuído |", "| --- | ---: | ---: |"]
    text += [f"| {s} km | {v['segments']} | {v['active_segments']} |" for s, v in scale_stats.items()]
    text += ["", f"Regiões adaptativas: {len(regions)} com pelo menos um evento; {regions_eligible} atendem ao mínimo de "
             f"{MIN_DAYS} datas positivas distintas, reunindo {eligible_events} eventos. "
             f"Até {MAX_BASE} segmentos adjacentes de 25 km são unidos na mesma cadeia costeira; não se unem ilhas separadas. "
             "Trechos já elegíveis são preservados. As regiões esparsas ficam no atlas, fora do recorte principal pelo critério de frequência.", "",
             f"O ponto mais próximo é calculado sobre a linha, por distância de círculo máximo. O vínculo padrão admite até {args.max_distance_km:g} km. "
             f"O ponto costeiro precisa estar até {COUNTRY_TOLERANCE_KM} km do país/território informado, quando mapeado. "
             "Topônimos e territórios revisados têm fonte documentada e critérios locais próprios. "
             f"O vínculo provisório admite até {args.extended_distance_km:g} km quando o topônimo tem indício costeiro específico "
             "e o país e o estado cartografado (quando reconhecido) são compatíveis. "
             "Nessa extensão, proxies compartilhados por nomes distintos, contextos artificiais/interiores, afastamento explícito "
             "acima do limite e nomes de ilha sem correspondência geométrica continuam em revisão. "
             "Localidade vazia ainda permite o vínculo padrão. As coordenadas originais não mudam, e a distância mede "
             "a separação entre o geocódigo aproximado e o trecho, não entre o incidente real e a costa.", "",
             "Sensibilidade apenas à distância, antes da validação de país: " + ", ".join(f"{n} eventos até {d} km" for d, n in max_counts.items()) + ".", "",
             "Os CSVs e os GeoJSON compactados são produtos da etapa espacial. O painel de treinamento por segmento e dia, "
             "com dias negativos e enriquecimento, ainda não é produzido aqui. O atlas é para inspeção e pesquisa, sem estimar risco.", ""]
    write_bytes(coast_dir / f"gsaf_segmentacao_relatorio_{ver}.md", "\n".join(text).encode())
    manifest = {"version": ver, "as_of": str(args.as_of), "sources": [{"file": args.input.name, "path": project_path(args.input), "sha256": sha(args.input)}] + source_ref,
                "script_sha256": sha(Path(__file__)), "rules": rules, "events": len(events), "status_counts": statuses,
                "scales": scale_stats, "assignment_method_counts": methods, "gained_assignments": gained, "lost_assignments": lost,
                "chains": len(paths), "adaptive_regions": len(regions), "eligible_regions": regions_eligible,
                "events_in_eligible_regions": eligible_events, "products": [{"file": name, "path": project_path(path), "sha256": sha(path), "bytes": path.stat().st_size}
                    for name, path in products.items() if not name.startswith("gsaf_segmentacao_manifesto_")]}
    write_bytes(coast_dir / f"gsaf_segmentacao_manifesto_{ver}.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    print(json.dumps({k: v for k, v in manifest.items() if k in ("status_counts", "assignment_method_counts", "gained_assignments", "lost_assignments", "scales", "adaptive_regions", "eligible_regions", "events_in_eligible_regions")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
