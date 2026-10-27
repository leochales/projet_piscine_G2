import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "pull", Path(__file__).resolve().parents[1] / "pull.py"
)
assert _spec and _spec.loader
pull = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pull)

FILES = {
    "all_sites_combined.csv": b"timestamp,site_id\n",
    "SITE001_metadata.json": b"{}",
}


def _md5(content: bytes) -> str:
    return hashlib.md5(content, usedforsecurity=False).hexdigest()


def _store(tmp_path: Path, files: dict[str, bytes] = FILES) -> tuple[Path, Path]:
    """Stockage au format de DVC 3 et fichier .dvc qui pointe dessus."""
    store = tmp_path / "store"
    for content in files.values():
        path = pull.object_path(store, _md5(content))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    entries = [{"md5": _md5(c), "relpath": name} for name, c in files.items()]
    manifest = json.dumps(entries).encode()
    dir_md5 = _md5(manifest)
    path = pull.object_path(store, dir_md5, ".dir")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(manifest)
    dvc_file = tmp_path / "repo" / "data" / "raw.dvc"
    dvc_file.parent.mkdir(parents=True)
    dvc_file.write_text(f"outs:\n- md5: {dir_md5}.dir\n  path: raw\n", encoding="utf-8")
    return store, dvc_file


def _run(
    store: Path, dvc_file: Path, monkeypatch: pytest.MonkeyPatch, *args: str
) -> int:
    monkeypatch.setenv("DVC_STORE", str(store))
    return pull.main(["--dvc-file", str(dvc_file), *args])


def test_copie_la_version_du_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, dvc_file = _store(tmp_path)
    assert _run(store, dvc_file, monkeypatch) == 0
    raw = dvc_file.with_suffix("")
    assert {p.name: p.read_bytes() for p in raw.iterdir()} == FILES


def test_ne_recopie_pas_un_fichier_a_jour_et_retire_les_autres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, dvc_file = _store(tmp_path)
    raw = dvc_file.with_suffix("")
    raw.mkdir()
    (raw / "all_sites_combined.csv").write_bytes(FILES["all_sites_combined.csv"])
    (raw / "ancien.csv").write_bytes(b"version precedente")

    md5 = pull.dir_hash(dvc_file)
    assert pull.pull(store, md5, raw) == 1
    assert sorted(p.name for p in raw.iterdir()) == sorted(FILES)


def test_refuse_un_fichier_corrompu_dans_le_stockage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, dvc_file = _store(tmp_path)
    pull.object_path(store, _md5(FILES["SITE001_metadata.json"])).write_bytes(b"autre")
    assert _run(store, dvc_file, monkeypatch) == 1


def test_check_sans_copie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, dvc_file = _store(tmp_path)
    assert _run(store, dvc_file, monkeypatch, "--check") == 0
    assert not dvc_file.with_suffix("").exists()


def test_check_echoue_si_la_version_n_a_pas_ete_envoyee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, dvc_file = _store(tmp_path)
    assert _run(tmp_path / "vide", dvc_file, monkeypatch, "--check") == 1


def test_check_echoue_s_il_manque_un_fichier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, dvc_file = _store(tmp_path)
    pull.object_path(store, _md5(FILES["all_sites_combined.csv"])).unlink()
    assert _run(store, dvc_file, monkeypatch, "--check") == 1


def test_refuse_un_chemin_hors_du_dossier(tmp_path: Path) -> None:
    store, _ = _store(tmp_path, {"../evasion": b"x"})
    md5 = _md5(json.dumps([{"md5": _md5(b"x"), "relpath": "../evasion"}]).encode())
    with pytest.raises(pull.StoreError, match="chemin refusé"):
        pull.manifest(store, md5)


def test_le_vrai_fichier_dvc_du_depot_est_lisible() -> None:
    assert len(pull.dir_hash(pull.ROOT / "data" / "raw.dvc")) == 32
