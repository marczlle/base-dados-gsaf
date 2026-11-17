"""Etapa 1 do TCC: limpeza auditável, offline, com CSVs versionados.

Python >= 3.10, somente biblioteca padrão. Execute da raiz do projeto:
    python scripts/clean_data.py --as-of 2026-10-23
"""
from __future__ import annotations

import argparse
import calendar
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from data_paths import CLEAN, DATA, ROOT, project_path, version_dir

ELIGIBLE_DATE_STATUSES = {"exact", "reported_date"}
MISSING = {"", "unknown", "nan", "none", "null", "n/a", "na", "not stated", "?"}
DERIVED = ["temperature_2m_mean", "precipitation_sum", "wind_speed_10m_max",
           "wind_direction_10m_dominant", "moon_illumination", "moon_phase"]
GEO = ["Country", "State", "Location"]
RAW_FIELDS = ["Year", "Month", "Day", *GEO, "extracted_lat", "extracted_lon", *DERIVED]
COUNTRY_ALIASES = {
    "COLUMBIA": "COLOMBIA", "MALDIVE ISLANDS": "MALDIVES",
    "REUNION ISLAND": "REUNION", "TURKS & CAICOS": "TURKS AND CAICOS ISLANDS",
    "TURKS AND CAICOS": "TURKS AND CAICOS ISLANDS",
    "TRINIDAD & TOBAGO": "TRINIDAD AND TOBAGO", "TRINIDAD": "TRINIDAD AND TOBAGO",
    "TOBAGO": "TRINIDAD AND TOBAGO", "UNITED ARAB EMIRATES (UAE)": "UNITED ARAB EMIRATES",
    "FEDERATED STATES OF MICRONESIA": "MICRONESIA", "WESTERN SAMOA": "SAMOA",
    "ST KITTS / NEVIS": "SAINT KITTS AND NEVIS", "NEVIS": "SAINT KITTS AND NEVIS",
    "ST MARTIN": "SAINT MARTIN", "ST. MARTIN": "SAINT MARTIN",
    "ST. MAARTIN": "SINT MAARTEN", "ENGLAND": "UNITED KINGDOM",
    "SCOTLAND": "UNITED KINGDOM", "HAWAII": "USA", "CANARY ISLANDS": "SPAIN",
    "OKINAWA": "JAPAN", "JAVA": "INDONESIA", "GRAND CAYMAN": "CAYMAN ISLANDS",
    "NEW BRITAIN": "PAPUA NEW GUINEA", "ADMIRALTY ISLANDS": "PAPUA NEW GUINEA",
}
STATE_ALIASES = {
    "AUSTRALIA": {"NSW": "NEW SOUTH WALES", "WA": "WESTERN AUSTRALIA",
                  "WESTERM AUSTRALIA": "WESTERN AUSTRALIA", "NEW SOUTH ALES": "NEW SOUTH WALES"},
    "SOUTH AFRICA": {"KZN": "KWAZULU-NATAL", "KNZ": "KWAZULU-NATAL",
                     "EASTEN CAPE PROVINCE": "EASTERN CAPE PROVINCE"},
    "BRAZIL": {"RIO GRANDE DE NORTE": "RIO GRANDE DO NORTE",
               "SANTA CATARINA STATE": "SANTA CATARINA", "SÃO PAULO.": "SÃO PAULO",
               "RECIFE": "PERNAMBUCO"},
    "MEXICO": {"GUERRO": "GUERRERO", "GUERRRERO": "GUERRERO",
               "QUINTA ROO": "QUINTANA ROO", "QUNTANA ROO": "QUINTANA ROO"},
    "MOZAMBIQUE": {"INHAMBE PROVINCE": "INHAMBANE PROVINCE", "BAY OF MAPUTU": "BAY OF MAPUTO"},
    "USA": {"FLORIA": "FLORIDA", "NOIRTH CAROLINA": "NORTH CAROLINA", "MAUI": "HAWAII"},
    "CANADA": {"BRITISH COLOMBIA": "BRITISH COLUMBIA"},
    "BAHAMAS": {"NEW PROVIDENCE ISOAD": "NEW PROVIDENCE ISLAND",
                "LUCAYAN LUCAYAN ARCHIPELAGO": "LUCAYAN ARCHIPELAGO"},
    "FIJI": {"VITA LEVU": "VITI LEVU", "VITU LEVU": "VITI LEVU"},
    "COSTA RICA": {"GUANACOSTE": "GUANACASTE"},
    "FRENCH POLYNESIA": {"TUAMOTOS": "TUAMOTU ISLANDS", "TUAMOTUS": "TUAMOTU ISLANDS"},
    "NEW CALEDONIA": {"GRAND TERRE": "GRANDE TERRE"},
    "NEW ZEALAND": {"COOK ISLANS": "COOK ISLANDS"},
    "NAMIBIA": {"ERONOGO REGION": "ERONGO REGION"},
    "SAMOA": {"UPOLO": "UPOLU ISLAND"},
    "SPAIN": {"CATALUNYA": "CATALONIA"},
    "REUNION": {"SAINT LEU": "SAINT-LEU", "SAINT-BENOIT": "SAINT-BENOÎT"},
}
MONTHS = {}
for number in range(1, 13):
    for name in (calendar.month_name[number], calendar.month_abbr[number]):
        MONTHS[name.casefold()] = number
for number, names in enumerate([
    ("janeiro", "jan"), ("fevereiro", "fev"), ("março", "marco", "mar"),
    ("abril", "abr"), ("maio", "mai"), ("junho", "jun"), ("julho", "jul"),
    ("agosto", "ago"), ("setembro", "set", "sept"), ("outubro", "out"),
    ("novembro", "nov"), ("dezembro", "dez"),
], 1):
    MONTHS.update({name: number for name in names})


def compact(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(str.maketrans({
        "’": "'", "‘": "'", "`": "'", "–": "-", "—": "-", "\u200b": "",
    }))
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s*,\s*", ", ", value)
    return "" if value.casefold() in MISSING else value


def integer(value: str) -> int | None:
    value = compact(value)
    if not value:
        return None
    try:
        number = Decimal(value)
        if number.is_finite() and number == number.to_integral_value():
            return int(number)
    except InvalidOperation:
        pass
    return None


def month_number(value: str) -> int | None:
    value = compact(value).casefold().rstrip(".")
    number = integer(value)
    return number if number is not None and 1 <= number <= 12 else MONTHS.get(value)


def geography(row: dict) -> dict:
    result = {field: compact(row[field]).upper() for field in GEO}
    result["Country"] = COUNTRY_ALIASES.get(result["Country"], result["Country"])
    # A designação de território no original resolve este rótulo genérico.
    if result["Country"] == "BRITISH OVERSEAS TERRITORY" and result["State"] == "TURKS AND CAICOS":
        result["Country"] = "TURKS AND CAICOS ISLANDS"
    aliases = STATE_ALIASES.get(result["Country"], {})
    result["State"] = aliases.get(result["State"], result["State"])
    return result


def coordinate(value: str, limit: int) -> tuple[str, str]:
    # A vírgula aqui é decimal, não pontuação de um topônimo.
    value = unicodedata.normalize("NFKC", value).strip()
    if value.casefold() in MISSING:
        return "", "missing"
    if "," in value:
        if "." in value or value.count(",") != 1:
            return "", "invalid_format"
        value = value.replace(",", ".")
    try:
        number = Decimal(value)
    except InvalidOperation:
        return "", "invalid_format"
    if not number.is_finite():
        return "", "non_finite"
    if abs(number) > limit:
        return "", "out_of_range"
    normalized = format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else format(number, "f")
    return ("0" if number == 0 else normalized), "valid"


def safe_date(year: int | None, month: int | None, day: int | None) -> date | None:
    try:
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def source_date(value: str, year: int) -> dict:
    """Não escolhe uma convenção de barra quando DD/MM e MM/DD são possíveis."""
    text = compact(value).casefold()
    reported = "reported" in text
    if reported:
        text = re.sub(r"reported", "", text).strip()
    text = re.sub(r"\.[a-z]$", "", text).strip(" .`'-")
    result = {"status": "unparsed", "dates": [], "year": year, "month": None}
    if re.search(r"\bto\b|\bearly\b|\blate\b|\bcirca\b|\bbefore\b|\bafter\b|weekend", text) or re.search(r"\d(?:st|nd|rd|th)?\s*[-&]\s*\d", text) and not re.match(r"\d{4}-\d{2}-\d{2}$", text):
        result["status"] = "range_or_approximate"
        return result
    if re.fullmatch(r"\d{4}", text):
        result.update(status="year_only", year=int(text))
        return result
    match = re.fullmatch(r"([a-z]+)[ -]+(\d{4})", text)
    if match and month_number(match[1]):
        result.update(status="month_only", year=int(match[2]), month=month_number(match[1]))
        return result
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        a, b, stated_year = map(int, match.groups())
        possibilities = sorted({d for d in [safe_date(stated_year, a, b), safe_date(stated_year, b, a)] if d})
        result.update(dates=possibilities, year=stated_year,
                      status="ambiguous_numeric" if len(possibilities) > 1 else "exact" if possibilities else "invalid")
    else:
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            y, m, d = map(int, match.groups())
        else:
            match = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?[ -]+([a-zç]+)(?:[ -]+(\d{2,4}))?", text)
            if not match:
                result["status"] = "reported_date" if reported else result["status"]
                return result
            d, m = int(match[1]), month_number(match[2])
            stated_year = match[3]
            y = year if not stated_year else int(stated_year)
            if stated_year and len(stated_year) == 2:
                y = year if year % 100 == y else y
        parsed = safe_date(y, m, d)
        result.update(dates=[parsed] if parsed else [], year=y, month=m,
                      status="exact" if parsed else "invalid")
    if result["year"] != year:
        result["status"] = "year_conflict"
    elif reported and result["status"] == "exact":
        result["status"] = "reported_date"
    return result


def linkage_key(row: dict) -> tuple:
    values = [str(integer(row["Year"]))]
    for field in ["Country", "State", "Location", "Time", "Activity"]:
        value = compact(row.get(field, "")).casefold()
        if field == "Time" and value.isdigit():
            value = str(int(value))
        values.append(value)
    return tuple(values)


def link_sources(row: dict, candidates: list[dict]) -> list[dict]:
    y, m, d = integer(row["Year"]), month_number(row["Month"]), integer(row["Day"])
    proposed = safe_date(y, m, d)
    matches = []
    for candidate in candidates:
        parsed = candidate["_parsed"]
        if proposed and proposed in parsed["dates"]:
            matches.append(candidate)
        elif not proposed and parsed["year"] == y and (
            parsed["month"] == m or any(item.month == m for item in parsed["dates"])
        ):
            matches.append(candidate)
    # Só usa o fallback se todas as candidatas têm a mesma data textual.
    return matches or (candidates if len({r["Date"] for r in candidates}) == 1 else [])


def classify_date(row: dict, candidates: list[dict], as_of: date) -> tuple[str, str]:
    y, m, d = integer(row["Year"]), month_number(row["Month"]), integer(row["Day"])
    proposed = safe_date(y, m, d)
    if not y or not m:
        return "invalid_year_or_month", ""
    if not compact(row["Day"]):
        return "day_unknown", ""
    if not proposed:
        return "invalid_calendar_date", ""
    if proposed > as_of:
        return "future_date", ""
    if not candidates:
        return "source_association_unresolved", ""
    statuses = {r["_parsed"]["status"] for r in candidates}
    if len(statuses) != 1:
        return "source_association_ambiguous", ""
    status = next(iter(statuses))
    if status not in ELIGIBLE_DATE_STATUSES:
        return status, ""
    if any(len(r["_parsed"]["dates"]) != 1 for r in candidates):
        return "source_association_ambiguous", ""
    if any(proposed not in r["_parsed"]["dates"] for r in candidates):
        return "source_date_conflict", ""
    return status, proposed.isoformat()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locate_input(root: Path = ROOT) -> Path:
    """Localiza a fonte arquivada sem depender de mudanças de pasta do projeto."""
    candidates = list(root.rglob("GSAF_clima_lua.csv"))
    if len(candidates) != 1:
        raise ValueError(f"Encontradas {len(candidates)} fontes GSAF_clima_lua.csv. Informe --input explicitamente.")
    return candidates[0]


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if not fields or len(set(fields)) != len(fields):
            raise ValueError(f"Cabeçalho ausente ou repetido: {path}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Quantidade de campos inconsistente: {path}")
    return fields, rows


def remove_confirmed_duplicates(rows: list[dict], source_fields: list[str]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["_signature"]].append(row)
    evidence = []
    for signature, members in groups.items():
        if len(members) < 2:
            continue
        candidates = {r["_row"]: r for row in members for r in row["_sources"]}
        unique_sources = {tuple(r[field] for field in source_fields) for r in candidates.values()}
        # Não é suficiente haver o mesmo Case Number: vítimas podem ser distintas.
        confirmed = bool(candidates) and len(unique_sources) < len(members) and (
            len(unique_sources) == 1 or len(candidates) == len(members)
        )
        removals = len(members) - len(unique_sources) if confirmed else 0
        assessment = "confirmed_source_duplicate" if confirmed else "distinct_source_records" if len(unique_sources) >= len(members) else "unresolved"
        group_id = "dup_" + signature[:12]
        for member in members:
            member["duplicate_group_id"] = group_id
            member["duplicate_assessment"] = assessment
        for member in members[-removals:] if removals else []:
            member["duplicate_removed"] = 1
        evidence.append({
            "duplicate_group_id": group_id, "assessment": assessment,
            "input_count": len(members), "removed_count": removals,
            "source_records_distinct": len(unique_sources),
            "source_csv_records": ";".join(str(r["source_csv_record"]) for r in members),
            "legacy_csv_records": ";".join(map(str, sorted(candidates))),
            "legacy_case_numbers": ";".join(sorted({compact(r.get("Case Number.1", "")) for r in candidates.values()} - {""})),
            "legacy_names": ";".join(sorted({compact(r.get("Name", "")) for r in candidates.values()} - {""})),
        })
    return evidence


def prepare(fields: list[str], source_rows: list[dict], legacy_fields: list[str], legacy_rows: list[dict], as_of: date):
    legacy_index = defaultdict(list)
    for number, original in enumerate(legacy_rows, 2):
        row = dict(original, _row=number)
        year = integer(row.get("Year", ""))
        row["_parsed"] = source_date(row.get("Date", ""), year) if year and 1 <= year <= 9999 else {"status": "invalid", "dates": [], "year": year, "month": None}
        legacy_index[linkage_key(row)].append(row)
    rows, mappings = [], Counter()
    for number, original in enumerate(source_rows, 2):
        row = dict(original)
        row.update({field + "_raw": original[field] for field in RAW_FIELDS})
        row.update(geography(original))
        for field in GEO:
            mappings[(field, compact(original["Country"]).upper(), original[field], row[field])] += 1
        row["Year"] = integer(original["Year"])
        row["Month"] = month_number(original["Month"])
        row["Day"] = integer(original["Day"])
        mappings[("Month", "", original["Month"], str(row["Month"] or ""))] += 1
        lat, ls = coordinate(original["extracted_lat"], 90)
        lon, os = coordinate(original["extracted_lon"], 180)
        row.update(extracted_lat=lat, extracted_lon=lon)
        row["latitude_status"], row["longitude_status"] = ls, os
        row["coordinate_status"] = "valid_numeric_pair" if ls == os == "valid" else "missing_pair" if ls == os == "missing" else "incomplete_or_invalid_pair"
        row["coordinates_spatially_verified"] = 0
        candidates = link_sources(original, legacy_index[linkage_key(original)])
        row["_sources"] = candidates
        row["legacy_csv_records"] = ";".join(str(c["_row"]) for c in candidates)
        row["legacy_dates"] = " | ".join(sorted({c["Date"] for c in candidates}))
        row["legacy_types"] = " | ".join(sorted({compact(c.get("Type", "")) for c in candidates} - {""}))
        row["date_status"], row["date"] = classify_date(original, candidates, as_of)
        row["date_is_approximate"] = int(row["date_status"] == "reported_date")
        extracted = safe_date(row["Year"], row["Month"], row["Day"])
        row["extracted_date"] = extracted.isoformat() if extracted else ""
        row["year_month"] = f"{row['Year']:04d}-{row['Month']:02d}" if row["Year"] and row["Month"] else ""
        row["record_id"] = f"gsaf_{number:06d}"
        row["source_csv_record"] = number
        row["duplicate_group_id"] = ""
        row["duplicate_assessment"] = "not_repeated"
        row["duplicate_removed"] = 0
        # Comparar ANTES de apagar enriquecimento de datas inelegíveis.
        row["_signature"] = digest([row[field] for field in fields])
        if row["date_status"] not in ELIGIBLE_DATE_STATUSES:
            for field in DERIVED:
                row[field] = ""
        row["legacy_enrichment_status"] = "retained_unverified_point_enrichment" if row["date_status"] in ELIGIBLE_DATE_STATUSES else "cleared_ineligible_date"
        rows.append(row)
    evidence = remove_confirmed_duplicates(rows, legacy_fields)
    for row in rows:
        reasons = []
        if row["duplicate_removed"]:
            reasons.append("confirmed_duplicate")
        if row["date_status"] not in ELIGIBLE_DATE_STATUSES:
            reasons.append(row["date_status"])
        row["eligible_daily_event"] = int(not reasons)
        spatial_reasons = list(reasons)
        if row["coordinate_status"] != "valid_numeric_pair":
            spatial_reasons.append("coordinates_missing_or_invalid")
        if not row["Country"]:
            spatial_reasons.append("country_missing")
        if not row["Location"]:
            spatial_reasons.append("location_missing")
        row["eligible_local_day"] = int(not spatial_reasons)
        row["daily_exclusion_reasons"] = ";".join(reasons)
        row["local_day_exclusion_reasons"] = ";".join(spatial_reasons)
        row["location_id"] = "loc_" + digest([row[field] for field in GEO])[:16] if row["Country"] and row["Location"] else ""
    mapping_rows = [dict(field=f, country_scope=c, original=o, normalized=n, input_count=count)
                    for (f, c, o, n), count in sorted(mappings.items())]
    return rows, evidence, mapping_rows


def local_days(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        if row["eligible_local_day"]:
            groups[(row["location_id"], row["date"])].append(row)
    result = []
    for (location_id, day), members in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        coordinates = {(r["extracted_lat"], r["extracted_lon"]) for r in members}
        lat, lon = next(iter(coordinates)) if len(coordinates) == 1 else ("", "")
        result.append({"location_id": location_id, "date": day, **{field: members[0][field] for field in GEO},
                       "attack": 1, "attack_count": len(members),
                       "exact_attack_count": sum(r["date_status"] == "exact" for r in members),
                       "reported_attack_count": sum(r["date_status"] == "reported_date" for r in members),
                       "has_reported_date": int(any(r["date_status"] == "reported_date" for r in members)),
                       "extracted_lat": lat, "extracted_lon": lon,
                       "coordinate_variants": len(coordinates), "coordinate_conflict": int(len(coordinates) > 1),
                       "coordinates_spatially_verified": 0,
                       "record_ids": ";".join(r["record_id"] for r in members)})
    return result


def model_events(rows: list[dict]) -> list[dict]:
    """Entrada enxuta da etapa espacial. Não exige topônimo nem coordenadas preenchidos."""
    return [{
        "record_id": row["record_id"], "date": row["date"],
        "country": row["Country"], "state": row["State"], "location": row["Location"],
        "latitude": row["extracted_lat"], "longitude": row["extracted_lon"],
        "date_is_approximate": row["date_is_approximate"],
        "coordinate_status": row["coordinate_status"],
        "coordinates_spatially_verified": row["coordinates_spatially_verified"],
        "needs_geocoding": int(row["coordinate_status"] != "valid_numeric_pair"),
    } for row in rows if row["eligible_daily_event"]]


def validate(rows: list[dict], days: list[dict], input_count: int):
    kept = [r for r in rows if not r["duplicate_removed"]]
    eligible = [r for r in kept if r["eligible_daily_event"]]
    assert len(rows) == input_count
    assert len(kept) + sum(r["duplicate_removed"] for r in rows) == input_count
    assert len({r["record_id"] for r in rows}) == input_count
    assert len({(r["location_id"], r["date"]) for r in days}) == len(days)
    assert sum(r["attack_count"] for r in days) == sum(r["eligible_local_day"] for r in rows)
    assert all(r["date"] and date.fromisoformat(r["date"]) == safe_date(r["Year"], r["Month"], r["Day"]) for r in eligible)
    assert all(not r["date"] and all(r[field] == "" for field in DERIVED) for r in kept if r["date_status"] not in ELIGIBLE_DATE_STATUSES)
    assert all(r["attack"] == 1 and r["attack_count"] >= 1 for r in days)
    assert all(r["attack_count"] == r["exact_attack_count"] + r["reported_attack_count"] for r in days)
    assert sum(r["reported_attack_count"] for r in days) == sum(r["eligible_local_day"] and r["date_is_approximate"] for r in rows)
    for row in rows:
        assert all(row[field] == row[field].upper() for field in GEO)
        assert all(row[field + "_raw"] is not None for field in RAW_FIELDS)
        assert row["date_is_approximate"] == int(row["date_status"] == "reported_date")
        if row["eligible_local_day"]:
            assert row["eligible_daily_event"] and row["Location"] and row["Country"]
            assert -90 <= Decimal(row["extracted_lat"]) <= 90
            assert -180 <= Decimal(row["extracted_lon"]) <= 180
    model_rows = model_events(rows)
    assert {r["record_id"] for r in model_rows} == {r["record_id"] for r in eligible}
    assert all(r["date"] for r in model_rows)


REASON_TEXT = {
    "confirmed_duplicate": "Duplicação comprovada por repetição completa no arquivo anterior.",
    "day_unknown": "Dia desconhecido. Nenhum dia foi imputado.",
    "reported_date": "Data de notícia/registro (Reported), sem comprovação do dia do incidente.",
    "ambiguous_numeric": "Data com barras admite DD/MM e MM/DD diferentes. Não foi escolhido um formato.",
    "year_conflict": "Ano explícito da data original diverge da coluna Year.",
    "month_only": "Fonte registra apenas mês/ano, embora a base atual possa conter um dia extraído.",
    "year_only": "Fonte registra apenas ano.",
    "range_or_approximate": "Fonte registra intervalo ou data aproximada.",
    "source_date_conflict": "Dia/mês/ano da base atual divergem da data explícita da fonte.",
    "source_association_unresolved": "Não foi possível associar a data atual à fonte sem ambiguidade.",
    "source_association_ambiguous": "As fontes candidatas discordam sobre a precisão da data.",
    "unparsed": "Formato da data original não reconhecido pelas regras explícitas.",
    "invalid": "Data original inválida.",
    "future_date": "Data posterior à data de referência da execução.",
    "coordinates_missing_or_invalid": "Coordenadas ausentes, incompletas ou inválidas numericamente.",
    "country_missing": "País ausente.", "location_missing": "Localidade ausente.",
}


def report(version: str, rows: list[dict], days: list[dict], evidence: list[dict], mappings: list[dict], metadata: dict) -> str:
    kept = [r for r in rows if not r["duplicate_removed"]]
    exact = [r for r in kept if r["date_status"] == "exact"]
    reported = [r for r in kept if r["date_status"] == "reported_date"]
    eligible = [r for r in kept if r["eligible_daily_event"]]
    quarantined = [r for r in kept if not r["eligible_daily_event"]]
    statuses = Counter(r["date_status"] for r in kept)
    daily_reasons = Counter(reason for r in rows for reason in r["daily_exclusion_reasons"].split(";") if reason)
    spatial_reasons = Counter(reason for r in rows for reason in r["local_day_exclusion_reasons"].split(";") if reason)
    local_excluded = [r for r in eligible if not r["eligible_local_day"]]
    local_reasons = Counter(reason for r in local_excluded for reason in r["local_day_exclusion_reasons"].split(";") if reason)
    spatial_candidates = [r for r in eligible if r["coordinate_status"] == "valid_numeric_pair"]
    recovered_unnamed = sum(not r["Location"] for r in spatial_candidates)
    countries_before = len({r["Country_raw"] for r in rows})
    countries_after = len({r["Country"] for r in kept if r["Country"]})
    lines = [f"# Qualidade e limpeza GSAF — {version}", "",
             f"Data de referência: {metadata['as_of']}. Regras: {metadata['rules_version']}.", "",
             "## Resultado", "", "| Medida | Quantidade |", "| --- | ---: |",
             f"| Registros de entrada | {len(rows)} |",
             f"| Duplicações comprovadas removidas da base limpa | {len(rows) - len(kept)} |",
             f"| Registros preservados na base limpa | {len(kept)} |",
             f"| Registros preservados com data exata | {len(exact)} |",
             f"| Registros Reported aceitos como aproximação | {len(reported)} |",
             f"| Registros elegíveis pela data (exata ou Reported) | {len(eligible)} |",
             f"| Registros preservados na entrada enxuta de modelagem | {len(eligible)} |",
             f"| Destes, com coordenadas numericamente válidas | {len(spatial_candidates)} |",
             f"| Registros com data inelegível, separados | {len(quarantined)} |",
             f"| Datas elegíveis distintas no mundo | {len({r['date'] for r in eligible})} |",
             f"| Registros aptos ao agrupamento por localidade e dia | {sum(r['eligible_local_day'] for r in rows)} |",
             f"| Pares localidade + data positivos | {len(days)} |",
             f"| Pares com mais de um registro | {sum(r['attack_count'] > 1 for r in days)} |",
             f"| Pares com coordenadas divergentes | {sum(r['coordinate_conflict'] for r in days)} |", "",
             "A unidade principal do plano continua sendo **segmento costeiro + data**. Nesta etapa, "
             "o agrupamento por localidade textual é provisório. Não representa a atribuição a segmentos "
             "da etapa 2 nem o painel final de treinamento. Nenhum dia negativo foi criado.", "",
             "## Fontes e rastreabilidade", ""]
    for source in metadata["sources"]:
        lines += [f"- `{source['path']}`: {source['rows']} registros. SHA-256 `{source['sha256']}`."]
    lines += ["", "GSAF_clima_lua.csv, no caminho registrado acima, é a fonte dos valores. O arquivo anterior em Old Data/Md é usado "
              "somente para conferir a precisão das datas e provar duplicações. Não foram acrescentados "
              "ataques antigos. A associação usa ano, país, estado, localidade, horário e atividade, com "
              "confirmação da data quando há várias candidatas. Horários numéricos com zeros à esquerda "
              "são equivalentes apenas nessa associação. Listas de candidatas não são uma atribuição "
              "individual de identidade. Nenhum nome de vítima foi atribuído à base limpa.", "",
              "`source_csv_record` e `legacy_csv_records` contam registros CSV com cabeçalho = 1. "
              "Não são linhas físicas quando um campo contém quebras de linha. `record_id` identifica "
              "o registro da fonte atual e deve ser interpretado junto ao hash dessa fonte.", "",
              "## Qual arquivo usar para modelagem", "",
              f"`gsaf_eventos_modelagem_{version}.csv` é a entrada enxuta da próxima etapa. "
              f"Contém os {len(eligible)} eventos com data elegível, sem excluir registros por nome de "
              "localidade, país ou coordenadas ausentes. Preserva somente `record_id`, `date`, `country`, "
              "`state`, `location`, `latitude`, `longitude`, `date_is_approximate`, `coordinate_status`, "
              "`coordinates_spatially_verified` e `needs_geocoding`. Não contém hora, espécie, tamanho "
              "do tubarão, atividade nem as cópias brutas da auditoria.", "",
              f"São {len(spatial_candidates)} eventos com par de coordenadas numericamente válido e "
              f"{len(eligible) - len(spatial_candidates)} que precisam recuperar coordenadas. "
              f"Entre os primeiros, {recovered_unnamed} não têm nome de localidade e continuam no arquivo. "
              "Coordenadas preenchidas ainda precisam de validação espacial; nenhum ponto foi geocodificado "
              "novamente nesta execução.", "",
              "Esse arquivo ainda é uma tabela de eventos positivos, não a matriz final de treinamento. "
              "O treinamento definido no plano usará uma linha por `segment_id + date`, com `attack` igual "
              "a 0 ou 1, coordenadas do segmento, variáveis meteorológicas padronizadas, lua e sazonalidade. "
              "Faltam a atribuição aos segmentos, a criação do calendário com dias negativos e o "
              "enriquecimento igual para positivos e negativos. O clima e a lua antigos ficam na base "
              "completa para rastreabilidade, sem serem confundidos com os preditores regionais finais. "
              "Nomes, IDs, flags de qualidade e contagens de ataques são contexto/alvo/auditoria, não "
              "entram automaticamente na matriz de preditores.", "",
              "## Como o resumo por localidade reduz o número de linhas", "",
              "A chave do resumo é país + estado + localidade normalizados + data. Ele exige país "
              "e localidade preenchidos e coordenadas numéricas válidas; estado pode faltar. Esses "
              "requisitos textuais pertencem apenas ao resumo provisório, não à entrada enxuta dos segmentos.", "",
              f"Dos {len(eligible)} eventos elegíveis pela data, {len(local_excluded)} não satisfazem "
              "os requisitos do resumo. Os motivos abaixo se sobrepõem:", "",
              "| Motivo entre eventos com data elegível | Registros |", "| --- | ---: |",
              *[f"| {reason} | {local_reasons[reason]} |" for reason in ["location_missing", "coordinates_missing_or_invalid", "country_missing"]], "",
              f"Os {sum(r['eligible_local_day'] for r in rows)} eventos restantes formam {len(days)} "
              f"pares localidade/data. A diferença de {sum(r['eligible_local_day'] for r in rows) - len(days)} "
              "é agregação de múltiplos registros no mesmo local/dia, sem apagar sua contagem: a soma "
              "de `attack_count` reconcilia com todos os eventos representados. Nenhum dos eventos "
              "com data elegível foi apagado da entrada enxuta por causa dessas regras.", "",
              "## Regras aplicadas", "",
              "- Política temporal atualizada por decisão do pesquisador: a data de notícia/registro "
              "(`Reported`) é aceita como aproximação válida do dia do ataque, sob a hipótese de "
              "intervalo pequeno entre incidente e notícia. Esse intervalo não foi medido nesta base. "
              "`date_status=reported_date` e `date_is_approximate=1` preservam a distinção em relação "
              "às datas exatas. Datas com intervalos explícitos, ano conflitante ou ambiguidade continuam "
              "inelegíveis, mesmo quando contêm a palavra Reported.",
              "- País, estado e localidade: Unicode NFKC, espaços e pontuação equivalentes, "
              "maiúsculas com acentos preservados, ausentes em branco. Aliases explícitos e contextualizados "
              "por país corrigem, por exemplo, COLUMBIA, NSW, Westerm Australia, Guerro e Inhambe Province. "
              "As variantes MEXICO, Mexico e MeXICO passam a MEXICO. Não houve agrupamento por semelhança "
              "aproximada nem tradução geral dos topônimos.",
              "- Meses: nomes completos, abreviações e números tornam-se inteiros de 1 a 12. "
              "Ano e dia também são inteiros; ausentes permanecem vazios.",
              "- `date`: ISO 8601 (AAAA-MM-DD), preenchida somente quando os componentes são válidos "
              "e a fonte confirma uma data exata ou uma data Reported aceita como aproximação. "
              "`extracted_date` guarda a reconstrução da base atual, "
              "mesmo quando reprovada. `year_month` é apenas o mês extraído e pode precisar de revisão "
              "quando a fonte é conflitante. Não é uma data mensal validada.",
              "- Datas numéricas ambíguas, intervalos e conflitos ficam separados. Não se "
              "corrigiu dia/mês por ordenação das linhas, nem se substituiu ano errado por suposição.",
              "- Latitude e longitude: decimal com ponto, sinal preservado, zeros válidos, ausência "
              "diferenciada de zero, checagem de finitude e limites ±90/±180. Valores brutos preservados.",
              "- Clima e lua dos registros com data inelegível ficam vazios na base limpa. "
              "Nas datas Reported elegíveis, o enriquecimento antigo é preservado para o dia de registro "
              "usado como aproximação. Os valores anteriores "
              "continuam nas colunas `_raw`, pois os scripts antigos consultavam clima no dia 1 e lua no "
              "dia 15 quando o dia era desconhecido. Não houve recálculo nem consulta a APIs.",
              "- Apenas duplicações comprovadas por registros completos repetidos na fonte anterior "
              "são removidas. Mesmo Case Number ou mesmos atributos ambientais não bastam. Vítimas e "
              "registros distintos no mesmo dia são preservados.",
              "- Os dias positivos usam somente registros retidos com `date_status` igual a `exact` "
              "ou `reported_date`, país e "
              "localidade preenchidos e par de coordenadas numericamente válido. Estado pode faltar. "
              "Cada par localidade normalizada + data aparece uma vez, com `attack=1` e `attack_count`. "
              "Contagens representam registros/vítimas na fonte, não encontros independentes comprovados. "
              "`attack_count` e demais informações posteriores ao incidente não são preditores.",
              "- O resumo diário discrimina `exact_attack_count`, `reported_attack_count` e "
              "`has_reported_date`. Esses campos servem à auditoria da hipótese e a análises de "
              "sensibilidade; não devem ser usados como preditores do próprio dia.",
              "- Se o mesmo local/dia tiver coordenadas distintas, elas não são promediadas nem "
              "escolhidas arbitrariamente: ficam vazias no resumo, com `coordinate_conflict=1`. "
              "As coordenadas individuais continuam no arquivo de eventos.", "",
              "## Distribuição e mudanças", "",
              f"Países/rótulos: {countries_before} valores brutos distintos, "
              f"{countries_after} valores preenchidos normalizados. "
              f"Meses: {len({r['Month_raw'] for r in rows})} representações brutas para "
              f"{len({r['Month'] for r in kept if r['Month']})} meses.", "",
              "| Campo | Registros com valor alterado |", "| --- | ---: |"]
    for field in [*GEO, "Month"]:
        lines.append(f"| {field} | {sum(m['input_count'] for m in mappings if m['field'] == field and m['original'] != m['normalized'])} |")
    lines += ["", "## Precisão das datas na base retida", "", "| Situação | Registros |", "| --- | ---: |"]
    lines += [f"| {key} | {count} |" for key, count in sorted(statuses.items())]
    lines += ["", "## Exclusões do recorte de eventos diários", "",
              "Todos os registros de entrada aparecem no arquivo de auditoria. Uma linha pode ter "
              "mais de um motivo; as contagens por motivo não devem ser somadas como linhas distintas.", "",
              "| Motivo | Registros de entrada | Explicação |", "| --- | ---: | --- |"]
    lines += [f"| {key} | {count} | {REASON_TEXT.get(key, key)} |" for key, count in sorted(daily_reasons.items())]
    lines += ["", "Motivos adicionais para não entrar no resumo por localidade:", "",
              "| Motivo | Registros de entrada |", "| --- | ---: |"]
    lines += [f"| {key} | {spatial_reasons[key]} |" for key in ["coordinates_missing_or_invalid", "country_missing", "location_missing"] if spatial_reasons[key]]
    lines += ["", "## Repetições e múltiplos no mesmo dia", "",
              f"Foram encontrados {len(evidence)} grupos de atributos completos repetidos após "
              f"normalização, dos quais {sum(e['assessment'] == 'confirmed_source_duplicate' for e in evidence)} "
              "possuem duplicação comprovada. O arquivo de duplicidades registra as linhas candidatas, "
              "os casos e os nomes originais que justificam preservar ou remover cada repetição.", "",
              "Registros removidos da base limpa (numeração da fonte atual, cabeçalho = 1): "
              + ", ".join(str(r["source_csv_record"]) for r in rows if r["duplicate_removed"]) + ". "
              "Todos continuam integralmente na auditoria, com `duplicate_removed=1` e "
              "`daily_exclusion_reasons` contendo `confirmed_duplicate`.", "",
              "## Limitações mantidas para as próximas etapas", "",
              "- Validade numérica não comprova geocodificação correta. Todas as linhas têm "
              "`coordinates_spatially_verified=0`. Há indícios de geocodificação incorreta: registros "
              "originalmente NEW BRITAIN aparecem com latitude positiva e longitude do Reino Unido/EUA. "
              "Não foram inventadas novas coordenadas. A etapa 2 deve verificar país, distância à costa "
              "e atribuição ao segmento antes de liberar esses pontos para treinamento.",
              "- A coluna Country ainda contém oceanos, regiões históricas, fronteiras e rótulos "
              "incertos. A normalização não os transforma artificialmente em países. State também "
              "contém ilhas, cidades e áreas marítimas: não é um cadastro administrativo validado.",
              "- O recorte de tipos segue a definição do plano: presença de registro na base. "
              "Não foi aplicada uma nova seleção por Type. `legacy_types` permite identificar Invalid, "
              "Questionable, Watercraft etc. A decisão sobre a população de incidentes deve ser explícita "
              "antes do treinamento; `attack=1` aqui indica registro, não validação factual do incidente.",
              "- Dados climáticos/lunares retidos para datas elegíveis (exatas ou Reported) continuam sendo o enriquecimento "
              "antigo por ponto de ataque. Não devem entrar diretamente no painel regional final: "
              "as etapas 4 e 5 preveem clima padronizado por segmento e lua única por data. "
              "Colunas `_raw`, identificadores, `legacy_types`, atividade, espécie, horário e contagens "
              "do próprio dia são de rastreabilidade e não definem a lista de preditores.", "",
              "## Arquivos da execução", "", "| Produto | Uso |", "| --- | --- |",
              f"| gsaf_limpa_{version}.csv | Base completa retida; preserva os campos brutos e as flags. |",
              f"| gsaf_eventos_diarios_{version}.csv | Eventos com data elegível, exata ou Reported; pode haver coordenadas ausentes. |",
              f"| gsaf_eventos_modelagem_{version}.csv | Entrada enxuta da etapa espacial; preserva todos os eventos com data elegível. |",
              f"| gsaf_datas_inelegiveis_{version}.csv | Registros retidos com data inelegível, separados para revisão/análise mensal. |",
              f"| gsaf_dias_positivos_local_{version}.csv | Uma linha por localidade e data elegível; discrimina registros exatos e Reported. |",
              f"| gsaf_auditoria_{version}.csv | Uma linha para cada entrada, incluindo removidas, destinos e motivos. |",
              f"| gsaf_duplicidades_{version}.csv | Evidências de repetições e múltiplos registros. |",
              f"| gsaf_normalizacoes_{version}.csv | Correspondência de cada valor original para o normalizado e frequência. |",
              f"| gsaf_qualidade_{version}.md | Este relatório. |",
              f"| gsaf_manifesto_{version}.json | Fontes, versão, parâmetros, contagens e hashes de todos os produtos. |", "",
              "## Reexecução e verificações", "", "```powershell",
              "python scripts/clean_data.py --as-of 2026-10-23", "python -m unittest discover -s tests -v", "```", "",
              "A próxima execução escolhe automaticamente a próxima versão livre em Data. "
              "Uma versão solicitada explicitamente só pode ser usada se não existir. "
              "CSV: UTF-8 com BOM, delimitador vírgula, decimal com ponto, ausentes vazios. "
              "Os artefatos incluem conferência de contagens, chaves, datas e preservação dos brutos. "
              "Não houve mudança nos arquivos de origem.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Fonte atual; por padrão localiza a única GSAF_clima_lua.csv no projeto.")
    parser.add_argument("--legacy", type=Path, default=ROOT / "Old Data/Md/GSAF5_ml_ready_final.csv")
    parser.add_argument("--output-dir", type=Path, default=DATA)
    parser.add_argument("--version", type=int)
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(timezone(timedelta(hours=-3))).date())
    args = parser.parse_args()
    args.input = args.input or locate_input()
    fields, originals = read_csv(args.input)
    legacy_fields, legacy = read_csv(args.legacy)
    required = {*RAW_FIELDS, "Time", "Activity"}
    if not required.issubset(fields):
        raise ValueError(f"Colunas necessárias ausentes: {sorted(required - set(fields))}")
    standard_layout = args.output_dir.resolve() == DATA
    used_files = DATA.rglob("*") if standard_layout else args.output_dir.glob("*")
    versions = {int(m[1]) for p in used_files if (m := re.search(r"_v(\d+)\.", p.name))}
    number = args.version if args.version is not None else max(versions, default=0) + 1
    if number < 1 or number in versions:
        raise ValueError("A versão deve ser positiva e ainda não existir. Nenhum arquivo foi sobrescrito.")
    version = f"v{number:03d}"
    if standard_layout:
        args.output_dir = version_dir(CLEAN, version)
    rows, evidence, mappings = prepare(fields, originals, legacy_fields, legacy, args.as_of)
    days = local_days(rows)
    validate(rows, days, len(originals))
    kept = [r for r in rows if not r["duplicate_removed"]]
    eligible = [r for r in kept if r["eligible_daily_event"]]
    model_rows = model_events(rows)
    incomplete = [r for r in kept if not r["eligible_daily_event"]]
    extra_fields = [field for field in rows[0] if field not in fields and not field.startswith("_")]
    output_fields = ["record_id", "source_csv_record", *fields,
                     *[field for field in extra_fields if field not in {"record_id", "source_csv_record"}]]
    daily_fields = ["location_id", "date", *GEO, "attack", "attack_count", "extracted_lat", "extracted_lon",
                    "exact_attack_count", "reported_attack_count", "has_reported_date",
                    "coordinate_variants", "coordinate_conflict", "coordinates_spatially_verified", "record_ids"]
    duplicate_fields = ["duplicate_group_id", "assessment", "input_count", "removed_count", "source_records_distinct",
                        "source_csv_records", "legacy_csv_records", "legacy_case_numbers", "legacy_names"]
    tables = {
        "gsaf_limpa": (kept, output_fields), "gsaf_eventos_diarios": (eligible, output_fields),
        "gsaf_eventos_modelagem": (model_rows, list(model_rows[0])),
        "gsaf_datas_inelegiveis": (incomplete, output_fields), "gsaf_dias_positivos_local": (days, daily_fields),
        "gsaf_auditoria": (rows, output_fields), "gsaf_duplicidades": (evidence, duplicate_fields),
        "gsaf_normalizacoes": (mappings, ["field", "country_scope", "original", "normalized", "input_count"]),
    }
    sources = [{"path": project_path(p),
                "rows": len(data), "sha256": file_hash(p)} for p, data in [(args.input, originals), (args.legacy, legacy)]]
    metadata = {"version": version, "rules_version": "1.2.0", "as_of": args.as_of.isoformat(),
                "date_policy": {"eligible_statuses": sorted(ELIGIBLE_DATE_STATUSES),
                                "reported_assumption": "Data de registro aceita como aproximação do dia do ataque por decisão do pesquisador; intervalo não medido."},
                "script_sha256": file_hash(Path(__file__)), "sources": sources,
                "counts": {"input": len(rows), "removed_duplicates": len(rows) - len(kept), "clean": len(kept),
                           "exact_date_events": sum(r["date_status"] == "exact" for r in kept),
                           "reported_date_events": sum(r["date_status"] == "reported_date" for r in kept),
                           "eligible_daily_events": len(eligible), "ineligible_date_events": len(incomplete),
                           "model_event_rows": len(model_rows),
                           "model_events_with_valid_coordinates": sum(not r["needs_geocoding"] for r in model_rows),
                           "model_events_needing_geocoding": sum(r["needs_geocoding"] for r in model_rows),
                           "local_day_events": sum(r["eligible_local_day"] for r in rows), "positive_local_days": len(days)},
                "date_status_counts": dict(Counter(r["date_status"] for r in kept)),
                "validation": "passed", "outputs": []}
    report_text = report(version, rows, days, evidence, mappings, metadata)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    targets = [args.output_dir / f"{name}_{version}.csv" for name in tables]
    targets += [args.output_dir / f"gsaf_qualidade_{version}.md", args.output_dir / f"gsaf_manifesto_{version}.json"]
    if any(p.exists() for p in targets):
        raise FileExistsError("Um produto desta versão já existe. Nenhum arquivo foi sobrescrito.")
    created = []
    try:
        for name, (data, columns) in tables.items():
            path = args.output_dir / f"{name}_{version}.csv"
            with path.open("x", encoding="utf-8-sig", newline="") as handle:
                created.append(path)
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                writer.writerows(data)
            saved_fields, saved = read_csv(path)
            assert saved_fields == columns and len(saved) == len(data)
            for expected, actual in zip(data, saved):
                assert all(actual[field] == ("" if expected.get(field) is None else str(expected.get(field, ""))) for field in columns)
            metadata["outputs"].append({"path": path.name, "rows": len(data), "sha256": file_hash(path)})
        report_path = args.output_dir / f"gsaf_qualidade_{version}.md"
        with report_path.open("x", encoding="utf-8", newline="\n") as handle:
            created.append(report_path)
            handle.write(report_text)
        metadata["outputs"].append({"path": report_path.name, "sha256": file_hash(report_path)})
        manifest_path = args.output_dir / f"gsaf_manifesto_{version}.json"
        with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
            created.append(manifest_path)
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        assert all(file_hash(path) == source["sha256"] for path, source in zip([args.input, args.legacy], sources))
    except BaseException:
        # Somente arquivos novos desta execução; nunca apagar diretórios recursivamente.
        for path in created:
            path.unlink(missing_ok=True)
        raise
    print(json.dumps({"version": version, "counts": metadata["counts"],
                      "date_status_counts": metadata["date_status_counts"], "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
