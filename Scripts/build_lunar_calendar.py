"""Generate one lunar and seasonal record per date present in the daily panel."""

import argparse
import calendar
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, time, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import ephem
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from data_paths import LUNAR, PANEL, project_path, version_dir


PHASES = (
    "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous",
    "full_moon", "waning_gibbous", "last_quarter", "waning_crescent",
)
FIELDS = (
    "date", "moon_phase", "moon_phase_deg", "moon_phase_sin", "moon_phase_cos",
    "moon_illumination", "year", "day_of_year", "day_of_year_sin", "day_of_year_cos",
)
RULES = [
    "Uma linha para cada data presente no painel de origem. A referência comum a todos os trechos é 12:00 UTC.",
    "A fase é a diferença entre as longitudes eclípticas geocêntricas aparentes da Lua e do Sol, em [0°, 360°). "
    "Lua nova corresponde a 0°, quarto crescente a 90°, cheia a 180° e quarto minguante a 270°.",
    "O rótulo da fase indica o setor de 45° mais próximo. O seno e o cosseno representam o ângulo contínuo.",
    "A iluminação é a fração do disco lunar iluminada, entre 0 e 1, segundo o PyEphem.",
    "O dia do ano é codificado em seno e cosseno usando (dia do ano − 1) dividido por 365 ou 366. "
    "O ano bruto permite ajustar transformações futuras só com os dados de treino.",
]
REFERENCES = ["https://rhodesmill.org/pyephem/coordinates.html", "https://rhodesmill.org/pyephem/quick.html"]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def panel_dates(path):
    dates = set()
    for batch in pq.ParquetFile(path).iter_batches(columns=["date"]):
        dates.update(pc.unique(batch.column(0)).to_pylist())
    if not dates or None in dates:
        raise ValueError("O painel precisa conter datas válidas")
    return sorted(dates)


def apparent_longitude(body, timestamp):
    return float(ephem.Ecliptic(ephem.Equatorial(body.g_ra, body.g_dec, epoch=timestamp)).lon)


def lunar_position(when):
    timestamp = ephem.Date(when)
    moon, sun = ephem.Moon(timestamp), ephem.Sun(timestamp)
    angle = (apparent_longitude(moon, timestamp) - apparent_longitude(sun, timestamp)) % math.tau
    return angle, moon.moon_phase


def calendar_row(day):
    angle, illuminated = lunar_position(datetime.combine(day, time(12), tzinfo=timezone.utc))
    phase = PHASES[math.floor(angle * 8 / math.tau + 0.5) % 8]
    day_of_year = day.timetuple().tm_yday
    seasonal = math.tau * (day_of_year - 1) / (365 + calendar.isleap(day.year))
    if not (0 <= angle < math.tau and 0 <= illuminated <= 1):
        raise ValueError(f"Valores lunares fora do intervalo esperado em {day}")
    return (day, phase, math.degrees(angle), math.sin(angle), math.cos(angle), illuminated,
            day.year, day_of_year, math.sin(seasonal), math.cos(seasonal))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--panel-version", default="v006")
    args = parser.parse_args()
    if any(not re.fullmatch(r"v[0-9]{3,}", version) for version in (args.version, args.panel_version)):
        parser.error("Use versões vNNN")
    panel = version_dir(PANEL, args.panel_version) / f"gsaf_painel_diario_25km_{args.panel_version}.parquet"
    output = version_dir(LUNAR, args.version)
    if output.exists():
        raise FileExistsError(f"Versão de saída já existe: {output}")
    input_hash = sha(panel)
    dates = panel_dates(panel)
    histogram = Counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".lua_") as directory:
        folder = Path(directory)
        dataset = folder / f"gsaf_calendario_lunar_{args.version}.csv"
        with dataset.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(FIELDS)
            for day in dates:
                row = calendar_row(day)
                histogram[row[1]] += 1
                writer.writerow(f"{value:.10f}" if isinstance(value, float) else value for value in row)
        if sha(panel) != input_hash:
            raise RuntimeError("O painel de origem foi alterado durante a geração")

        report = folder / f"gsaf_calendario_lunar_relatorio_{args.version}.md"
        lines = [f"# Calendário lunar e sazonal — {args.version}", "",
                 f"Foram calculadas {len(dates):,} datas distintas de {dates[0]} a {dates[-1]}.".replace(",", "."),
                 f"O calendário acompanha `{panel.name}` e pode ser associado pelo campo `date`.", "", "## Regras", "",
                 *(f"- {rule}" for rule in RULES), "", "## Distribuição dos rótulos", "",
                 "| Fase | Datas |", "| --- | ---: |", *(f"| `{phase}` | {histogram[phase]} |" for phase in PHASES), "",
                 "## Reprodução", "", "```powershell", f"python -m pip install ephem=={ephem.__version__} pyarrow=={pa.__version__}",
                 f"python Scripts/build_lunar_calendar.py --panel-version {args.panel_version} --version {args.version}", "```", "",
                 "Se a versão já existir em `Data/`, informe a próxima versão disponível.", ""]
        report.write_text("\n".join(lines), encoding="utf-8")
        manifest = folder / f"gsaf_calendario_lunar_manifesto_{args.version}.json"
        manifest.write_text(json.dumps({
            "version": args.version, "panel_version": args.panel_version, "pyephem_version": ephem.__version__, "pyarrow_version": pa.__version__,
            "dates": len(dates), "date_range": [str(dates[0]), str(dates[-1])], "phase_counts": dict(histogram),
            "reference_time_utc": "12:00:00Z", "rules": RULES, "references": REFERENCES,
            "inputs": [{"path": project_path(panel), "sha256": input_hash},
                       {"path": project_path(Path(__file__)), "sha256": sha(Path(__file__))}],
            "products": [{"file": path.name, "sha256": sha(path)} for path in (dataset, report)],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output.mkdir()
        published = []
        try:
            for product in (dataset, report, manifest):
                destination = output / product.name
                os.link(product, destination)
                published.append(destination)
        except BaseException:
            for path in published:
                path.unlink()
            output.rmdir()
            raise
    print(f"{len(dates)} datas calculadas em {output}")


if __name__ == "__main__":
    main()
