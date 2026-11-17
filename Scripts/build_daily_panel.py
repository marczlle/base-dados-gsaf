"""Build the retrospective fixed 25 km GSAF segment-day panel (requires pyarrow)."""

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from data_paths import COAST, PANEL, project_path, version_dir

EPOCH = date(1970, 1, 1)
SCALE = "25"
DATE_FLAGS = {"exact": "0", "reported_date": "1"}
SCHEMA = pa.schema([
    ("segment_id", pa.string()),
    ("date", pa.date32()),
    ("attack", pa.uint8()),
    ("attack_count", pa.uint32()),
    ("reported_attack_count", pa.uint32()),
    ("date_status", pa.string()),
    ("date_is_approximate", pa.uint8()),
])


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_assignments(path):
    days_by_segment = defaultdict(lambda: defaultdict(Counter))
    assignments = Counter()
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row["scale_km"] != SCALE:
                continue
            event_id = row["event_id"]
            segment_id = row["segment_id"]
            status = row["status"]
            date_status = row["date_status"]
            if not event_id or event_id in seen:
                raise ValueError(f"Identificador vazio ou repetido na escala de 25 km: {event_id!r}")
            if row["date_is_approximate"] != DATE_FLAGS.get(date_status):
                raise ValueError(f"Status ou flag de data inesperado: {event_id}")
            if not status or (status == "assigned") != bool(segment_id):
                raise ValueError(f"Atribuição espacial inconsistente: {event_id}")
            day = date.fromisoformat(row["date"])
            seen.add(event_id)
            assignments[status] += 1
            if segment_id:
                days_by_segment[segment_id][day][date_status] += 1
    if not days_by_segment:
        raise ValueError(f"Nenhum evento atribuído a um segmento de 25 km em {path}")
    return days_by_segment, assignments


def write_panel(path, days_by_segment):
    counts = Counter()
    with pq.ParquetWriter(path, SCHEMA, compression="zstd") as writer:
        for segment_id, days in sorted(days_by_segment.items()):
            first, last = min(days), max(days)
            length = (last - first).days + 1
            attack = [0] * length
            attack_count = [0] * length
            reported_count = [0] * length
            date_status = [None] * length
            approximate = [0] * length
            for day, events in days.items():
                offset = (day - first).days
                exact, reported = events["exact"], events["reported_date"]
                attack[offset] = 1
                attack_count[offset] = exact + reported
                reported_count[offset] = reported
                approximate[offset] = int(reported > 0)
                status = "mixed" if exact and reported else next(iter(events))
                date_status[offset] = status
                counts[f"positive_days_{status}"] += 1
                counts["multiple_event_days"] += int(exact + reported > 1)
                counts["exact_events"] += exact
                counts["reported_events"] += reported
            start = (first - EPOCH).days
            writer.write_batch(pa.RecordBatch.from_arrays([
                pa.repeat(pa.scalar(segment_id), length),
                pa.array(range(start, start + length), type=pa.int32()).cast(pa.date32()),
                pa.array(attack, type=pa.uint8()),
                pa.array(attack_count, type=pa.uint32()),
                pa.array(reported_count, type=pa.uint32()),
                pa.array(date_status, type=pa.string()),
                pa.array(approximate, type=pa.uint8()),
            ], schema=SCHEMA))
            counts["rows"] += length
            counts["positive_days"] += len(days)
            counts["negative_days"] += length - len(days)
            counts["segments"] += 1
            counts["single_day_segments"] += int(length == 1)
    metadata = pq.read_metadata(path)
    if metadata.num_rows != counts["rows"] or metadata.num_row_groups != counts["segments"]:
        raise RuntimeError("Contagens do Parquet divergiram da geração do painel")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Versão de saída, por exemplo v006")
    parser.add_argument("--source-version", required=True, help="Versão da correspondência evento–segmento")
    args = parser.parse_args()
    if any(not re.fullmatch(r"v[0-9]{3,}", value) for value in (args.version, args.source_version)):
        parser.error("Use versões no formato vNNN")

    source = version_dir(COAST, args.source_version) / f"gsaf_eventos_segmentos_{args.source_version}.csv"
    output = version_dir(PANEL, args.version)
    panel = f"gsaf_painel_diario_25km_{args.version}.parquet"
    report = f"gsaf_painel_diario_25km_relatorio_{args.version}.md"
    manifest = f"gsaf_painel_diario_25km_manifesto_{args.version}.json"
    outputs = (panel, report, manifest)
    for name in outputs:
        if (output / name).exists():
            raise FileExistsError(f"A versão de saída já existe: {output / name}")

    source_hash = sha256(source)
    days_by_segment, assignments = read_assignments(source)
    start = min(min(days) for days in days_by_segment.values()).isoformat()
    end = max(max(days) for days in days_by_segment.values()).isoformat()
    rules = [
        "Usar segmentos fixos de 25 km e vínculos com status `assigned`, incluindo os aproximados aceitos na etapa espacial.",
        "Gerar uma linha por `segment_id` e `date` entre o primeiro e o último evento de cada segmento, inclusive.",
        "`attack=1` indica pelo menos um registro no dia. `attack=0` indica ausência de registro na GSAF dentro da janela.",
        "`attack_count` conta eventos distintos. `reported_attack_count` conta os eventos com data `Reported`.",
        "`date_status` é `exact`, `reported_date` ou `mixed` se houver ambos no dia, e nulo nos dias com `attack=0`. "
        "`date_is_approximate=1` indica pelo menos um evento `Reported` no dia.",
        "Contagens e flags derivados dos eventos servem à auditoria do alvo. O enriquecimento climático e lunar pertence às etapas seguintes.",
        "O intervalo primeiro–último é retrospectivo. Um teste prospectivo requer elegibilidade e fim do teste definidos sem usar os ataques futuros.",
    ]
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output, prefix=".painel_") as temporary:
        stage = Path(temporary)
        counts = write_panel(stage / panel, days_by_segment)
        if counts["exact_events"] + counts["reported_events"] != assignments["assigned"] or sha256(source) != source_hash:
            raise RuntimeError("Falha na reconciliação dos eventos ou alteração da fonte durante a geração")
        counts["source_events"] = sum(assignments.values())
        counts["excluded_events"] = counts["source_events"] - assignments["assigned"]
        counts["positive_fraction"] = counts["positive_days"] / counts["rows"]
        metrics = {
            "Segmentos no painel": counts["segments"],
            "Segmentos com janela de um dia": counts["single_day_segments"],
            "Linhas": counts["rows"],
            "Dias positivos": counts["positive_days"],
            "Dias sem registro": counts["negative_days"],
            "Dias positivos com múltiplos eventos": counts["multiple_event_days"],
            "Dias positivos somente com data exata": counts["positive_days_exact"],
            "Dias positivos somente com data Reported": counts["positive_days_reported_date"],
            "Dias positivos com data exata e Reported": counts["positive_days_mixed"],
            "Eventos com data exata": counts["exact_events"],
            "Eventos com data Reported": counts["reported_events"],
        }
        lines = [f"# Painel diário de 25 km — {args.version}", "", f"Fonte `{source.name}`.",
                 f"Intervalo global das datas {start} a {end}.", "", "## Regras", ""]
        lines += [f"- {rule}" for rule in rules]
        lines += ["", "## Contagens", "", "| Métrica | Total |", "| --- | ---: |"]
        lines += [f"| {label} | {value:,} |".replace(",", ".") for label, value in metrics.items()]
        fraction = f"{counts['positive_fraction']:.5%}".replace(".", ",")
        lines += [f"| Proporção de dias positivos | {fraction} |", "", "## Correspondências na fonte", "",
                  f"Foram excluídos {counts['excluded_events']} eventos sem atribuição espacial nessa escala. "
                  f"Os IDs e motivos individuais estão no CSV de origem.", "", "| Status | Eventos |", "| --- | ---: |"]
        lines += [f"| `{status}` | {total:,} |".replace(",", ".") for status, total in sorted(assignments.items())]
        lines += ["", "## Reprodução", "", "```powershell", f"python -m pip install pyarrow=={pa.__version__}",
                  f"python Scripts/build_daily_panel.py --source-version {args.source_version} --version {args.version}",
                  "```", "", "Em `Data/` com esta versão já publicada, use a próxima versão disponível.",
                  f"Fontes, versão do PyArrow e hashes SHA-256 em `{manifest}`.", ""]
        (stage / report).write_text("\n".join(lines), encoding="utf-8")

        metadata = {
            "version": args.version,
            "scale_km": int(SCALE),
            "date_range": [start, end],
            "sources": [{"file": source.name, "path": project_path(source), "sha256": source_hash}],
            "script": {"file": f"Scripts/{Path(__file__).name}", "sha256": sha256(Path(__file__))},
            "pyarrow_version": pa.__version__,
            "rules": rules,
            "assignment_status_counts": dict(assignments),
            "counts": dict(counts),
            "products": [{"file": name, "sha256": sha256(stage / name), "bytes": (stage / name).stat().st_size}
                         for name in (panel, report)],
        }
        (stage / manifest).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        published = []
        try:
            for name in outputs:
                destination = output / name
                os.link(stage / name, destination)
                published.append(destination)
        except BaseException:
            for destination in reversed(published):
                destination.unlink()
            raise
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
