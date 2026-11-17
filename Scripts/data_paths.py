"""Shared locations for versioned project data."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Data"
CLEAN = "01_limpeza"
COAST = "02_segmentacao"
PANEL = "03_painel_diario"
CLIMATE = "04_clima"
LUNAR = "05_lua"
ATLAS = "atlas"
SOURCES = DATA / "fontes"


def version_dir(stage, version):
    active = DATA / stage / version
    archived = DATA / "historico" / stage / version
    return archived if archived.is_dir() and not active.exists() else active


def project_path(path):
    path = path.resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
