"""Prepara e serve o atlas estático a partir dos produtos versionados da etapa 2."""

import argparse
import gzip
import hashlib
import json
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

from data_paths import ATLAS, COAST, ROOT, project_path, version_dir

DIST = ROOT / "sites" / "atlas-costeiro" / "dist"
LAND_SOURCE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_land.geojson"
LAND_SHA = "9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_versioned(path, content):
    if path.is_file() and path.read_bytes() == content:
        return
    with path.open("xb") as stream:
        stream.write(content)


def prepare(version, record_manifest=False):
    atlas_dir = version_dir(ATLAS, version)
    coast_dir = version_dir(COAST, version)
    index = atlas_dir / f"atlas_indice_{version}.json"
    index_blob = index.read_bytes()
    basemap = atlas_dir / f"atlas_terra_{version}.geojson"
    if not basemap.exists():
        cached = version_dir(ATLAS, "v004") / "atlas_terra_v004.geojson"
        if cached.is_file():
            content = cached.read_bytes()
        else:
            with urlopen(LAND_SOURCE, timeout=30) as response:
                content = response.read()
        if sha(content) != LAND_SHA:
            raise ValueError("O hash do mapa-base não corresponde à fonte fixada.")
        write_versioned(basemap, content)

    land_blob = basemap.read_bytes()
    if sha(land_blob) != LAND_SHA:
        raise ValueError("O mapa-base local não corresponde à fonte fixada.")
    info = json.loads(index_blob)
    manifest = json.loads((coast_dir / f"gsaf_segmentacao_manifesto_{version}.json").read_bytes())
    hashes = {entry["file"]: entry["sha256"] for entry in manifest["products"]}
    if info["version"] != version or sha(index_blob) != hashes.get(index.name):
        raise ValueError("O índice não corresponde ao manifesto da etapa 2.")
    assets = [(index, index_blob, None), (basemap, land_blob, None)]
    for scale in (10, 25, 50):
        source = atlas_dir / f"atlas_segmentos_{scale}km_{version}.json"
        content = source.read_bytes()
        if info["files"][str(scale)] != source.name or sha(content) != hashes.get(source.name):
            raise ValueError(f"A escala {scale} não corresponde ao manifesto da etapa 2.")
        compressed = source.with_suffix(".json.gz")
        if compressed.exists():
            payload = compressed.read_bytes()
            if gzip.decompress(payload) != content:
                raise ValueError(f"O recurso compactado difere da fonte: {source.name}")
        else:
            payload = gzip.compress(content, compresslevel=6, mtime=0)
            write_versioned(compressed, payload)
        assets.append((compressed, payload, source))
    (DIST / "data").mkdir(parents=True, exist_ok=True)
    for source, content, _ in assets:
        if len(content) > 25 * 1024 * 1024:
            raise ValueError(f"Divida o recurso antes de publicar: {source.name}")
        write_versioned(DIST / "data" / source.name, content)
    if record_manifest:
        manifest_path = atlas_dir / f"atlas_manifesto_site_{version}.json"
        legacy_paths = False
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_bytes())
            legacy_paths = existing["dados"][0]["arquivo"] == f"Data/{index.name}"

        def asset_path(path):
            return f"Data/{path.name}" if legacy_paths else project_path(path)

        website = sorted(p for p in DIST.rglob("*") if p.is_file() and p.parent != DIST / "data")
        manifest = {
            "versao": version,
            "regra": "O site usa apenas as projeções cartográficas da etapa 2 e o mapa-base; os CSVs de origem não são incluídos.",
            "mapa_base": {"fonte": LAND_SOURCE, "camada": "Natural Earth Land 1:110m", "sha256": LAND_SHA},
            "dados": [{"arquivo": asset_path(path), "bytes": len(blob), "sha256": sha(blob),
                       **({"derivado_de": {"arquivo": asset_path(origin), "sha256": hashes[origin.name]}} if origin else {})}
                      for path, blob, origin in assets],
            "interface": [{"arquivo": p.relative_to(ROOT).as_posix(), "sha256": sha(p.read_bytes())} for p in website],
        }
        if not (DIST / "index.html").is_file():
            raise ValueError("A interface ainda não está disponível em dist/index.html.")
        write_versioned(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v005")
    parser.add_argument("--manifesto", action="store_true", help="Registra hashes da interface concluída e das fontes.")
    parser.add_argument("--serve", action="store_true", help="Abre um servidor HTTP local para visualizar o atlas.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]{3,}", args.version):
        parser.error("Use uma versão sequencial como v004.")
    prepare(args.version, args.manifesto)
    if args.serve:
        handler = partial(SimpleHTTPRequestHandler, directory=str(DIST))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            print(f"Atlas: http://127.0.0.1:{server.server_port}/", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
