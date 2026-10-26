"""Récupère data/raw (suivi par DVC, voir data/raw.dvc) depuis le stockage DVC de la VM.

    python3 infra/dataset/pull.py [--check]

Lancé par deploy.yml (--check : vérifie seulement que le stockage a la version du commit)
et dataset.yml, sur le runner auto-hébergé. Le stockage est sur le disque de la VM : il est
lu directement, dans le format de DVC 3 (files/md5/<2 car.>/<reste>), sans installer DVC.
Chaque fichier copié est vérifié par son empreinte MD5.

Bibliothèque standard seulement : python3 du système, sans venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = Path("/srv/enervision-dvc")


class StoreError(Exception):
    pass


def dir_hash(dvc_file: Path) -> str:
    """Empreinte du dossier suivi (ligne « md5: <hash>.dir » du fichier .dvc)."""
    match = re.search(
        r"md5:\s*([0-9a-f]{32})\.dir", dvc_file.read_text(encoding="utf-8")
    )
    if not match:
        raise StoreError(f"{dvc_file} : empreinte du dossier introuvable")
    return match.group(1)


def object_path(store: Path, md5: str, suffix: str = "") -> Path:
    return store / "files" / "md5" / md5[:2] / f"{md5[2:]}{suffix}"


def manifest(store: Path, md5: str) -> list[dict[str, str]]:
    """Fichiers du dossier (relpath, md5), lus dans le stockage."""
    path = object_path(store, md5, ".dir")
    if not path.is_file():
        raise StoreError(
            f"version {md5} absente du stockage {store} (dvc push à faire)"
        )
    entries: list[dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        relpath = Path(entry["relpath"])
        if relpath.is_absolute() or ".." in relpath.parts:
            raise StoreError(f"chemin refusé dans le stockage : {entry['relpath']}")
    return entries


def file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(store: Path, md5: str) -> int:
    """Vérifie que le stockage a tous les fichiers de la version ; renvoie leur nombre."""
    entries = manifest(store, md5)
    missing = [
        e["relpath"] for e in entries if not object_path(store, e["md5"]).is_file()
    ]
    if missing:
        raise StoreError(f"fichiers absents du stockage : {', '.join(missing)}")
    return len(entries)


def pull(store: Path, md5: str, target: Path) -> int:
    """Met dans target exactement les fichiers de la version ; renvoie le nombre copié."""
    entries = manifest(store, md5)
    copied = 0
    expected = set()
    for entry in entries:
        dest = target / entry["relpath"]
        expected.add(dest)
        if dest.is_file() and file_md5(dest) == entry["md5"]:
            continue
        source = object_path(store, entry["md5"])
        if not source.is_file():
            raise StoreError(f"{entry['relpath']} absent du stockage")
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(f".{dest.name}.partiel")
        shutil.copyfile(source, partial)
        if file_md5(partial) != entry["md5"]:
            partial.unlink()
            raise StoreError(
                f"{entry['relpath']} : empreinte différente dans le stockage"
            )
        partial.replace(dest)
        copied += 1
    # Fichiers d'une autre version : retirés, le dossier est exactement celui du commit
    for path in target.rglob("*"):
        if path.is_file() and path not in expected:
            path.unlink()
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="vérifier sans copier")
    parser.add_argument("--dvc-file", type=Path, default=ROOT / "data" / "raw.dvc")
    args = parser.parse_args(argv)

    store = Path(os.environ.get("DVC_STORE") or DEFAULT_STORE)
    try:
        md5 = dir_hash(args.dvc_file)
        if args.check:
            print(f"{check(store, md5)} fichiers de la version {md5} dans {store}")
        else:
            target = args.dvc_file.with_suffix("")
            copied = pull(store, md5, target)
            print(f"{target} : version {md5}, {copied} fichier(s) copié(s)")
    except StoreError as error:
        print(f"erreur : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
