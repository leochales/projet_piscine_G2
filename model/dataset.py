"""Modèle — Jeu d'entraînement à partir de l'historique CSV du sujet (SMARTOPS-93).

    python -m model.dataset [--raw-dir data/raw] [--out-dir data/processed] [--sans-mlflow]

Entrée : ``all_sites_combined.csv`` (7 sites, une mesure par heure, 2023-2024) et les
``SITE00X_metadata.json`` (anomalies étiquetées), déposés dans ``DATASET_RAW_DIR``.

Sortie, dans ``DATASET_OUTPUT_DIR`` :
  - ``dataset.parquet`` : une ligne par site et par heure, au format de
    ``gold.consommation_horaire`` (ce que le modèle lit en production), plus la valeur
    brute, la méthode d'imputation et le jeu (entraînement, validation ou test) ;
  - ``anomalies.parquet`` : anomalies étiquetées, pour évaluer la détection des pics ;
  - ``rapport_qualite.json`` : valeurs manquantes, imputées et nulles, par site et par jeu.

Règles :
  - horodatages sans fuseau lus comme de l'UTC, comme ceux de l'API Mock (un fuseau
    explicite est converti en UTC) ;
  - première version sans météo : seule la consommation est gardée ;
  - aucune ligne supprimée : une consommation négative devient manquante, un trou de
    MAX_IMPUTED_GAP heures au plus est comblé par interpolation linéaire, un trou plus
    long reste vide (taux_couverture = 0) ;
  - découpage chronologique sur des heures communes à tous les sites, pour qu'une même
    heure ne soit jamais à la fois dans l'entraînement et dans le test ; l'imputation se
    fait dans chaque jeu, sans valeur prise dans le jeu suivant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from common.logs import configure_logging

logger = logging.getLogger(__name__)

CSV_NAME = "all_sites_combined.csv"
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_OUTPUT_DIR = Path("data/processed")

# Trou le plus long (en heures consécutives) comblé par interpolation : la doc de
# l'API Mock réserve l'interpolation aux pannes de moins de 3 mesures
MAX_IMPUTED_GAP = 2

# Part de l'entraînement et de la validation ; le test prend le reste
SPLIT_RATIOS = (0.70, 0.15)
SPLITS = ("entrainement", "validation", "test")

MLFLOW_EXPERIMENT = "jeu-entrainement"

# Gold compte en minutes (nb_mesures, nb_imputees) : une heure mesurée du CSV en vaut 60
MINUTES_PER_HOUR = 60

GOLD_COLUMNS = [
    "id_site",
    "heure",
    "consommation_kwh",
    "pic_kw",
    "moyenne_kw",
    "nb_mesures",
    "nb_imputees",
    "taux_couverture",
    "heure_complete",
]


@dataclass(frozen=True)
class DatasetFiles:
    dataset: Path
    anomalies: Path
    report: Path
    fingerprint: str


def load_raw(csv_path: Path) -> pd.DataFrame:
    """Lit les colonnes utiles du CSV, horodatages en UTC."""
    raw = pd.read_csv(
        csv_path,
        usecols=["timestamp", "site_id", "consumption_kwh"],
        dtype={"site_id": "string", "consumption_kwh": "float64"},
    )
    raw["heure"] = to_utc(raw["timestamp"])
    return raw.rename(columns={"site_id": "id_site", "consumption_kwh": "brute"})[
        ["id_site", "heure", "brute"]
    ]


def to_utc(timestamps: pd.Series) -> pd.Series:
    """Horodatages ISO 8601 en UTC : sans fuseau, ils sont déjà en UTC."""
    return pd.to_datetime(timestamps, format="ISO8601", utc=True)


def hour_range(raw: pd.DataFrame) -> pd.DatetimeIndex:
    """Toutes les heures, de la première à la dernière du fichier."""
    return pd.date_range(raw["heure"].min(), raw["heure"].max(), freq="h")


def complete_grid(raw: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par site et par heure, de la première à la dernière heure du fichier."""
    hours = hour_range(raw)
    grid = pd.MultiIndex.from_product(
        [sorted(raw["id_site"].unique()), hours], names=["id_site", "heure"]
    )
    deduplicated = raw.drop_duplicates(["id_site", "heure"], keep="first")
    return deduplicated.set_index(["id_site", "heure"]).reindex(grid).reset_index()


def short_gaps(missing: pd.Series, max_gap: int) -> pd.Series:
    """Vrai pour les valeurs manquantes d'un trou de ``max_gap`` heures au plus,
    entouré de deux valeurs connues (un trou en début ou en fin de série reste vide)."""
    run_id = (missing != missing.shift()).cumsum()
    run_length = missing.groupby(run_id).transform("size")
    first, last = run_id.iloc[0], run_id.iloc[-1]
    inside = (run_id != first) & (run_id != last)
    return missing & (run_length <= max_gap) & inside


def impute_site(brute: pd.Series, max_gap: int = MAX_IMPUTED_GAP) -> pd.DataFrame:
    """Interpolation linéaire des trous courts d'un site (série triée par heure)."""
    missing = brute.isna()
    to_fill = short_gaps(missing, max_gap)
    interpolated = brute.interpolate(method="linear", limit_area="inside")
    value = brute.where(~to_fill, interpolated)
    method = pd.Series("none", index=brute.index).where(
        ~to_fill, "linear_interpolation"
    )
    return pd.DataFrame({"consommation_kwh": value, "methode_imputation": method})


def to_gold_format(
    raw: pd.DataFrame, max_gap: int = MAX_IMPUTED_GAP, bounds: Sequence[Any] = ()
) -> pd.DataFrame:
    """Nettoie et met au format de gold.consommation_horaire (une mesure par heure).

    ``bounds`` : premières heures de la validation et du test. Chaque jeu est imputé à
    part : un trou à la frontière n'est pas comblé avec une valeur du jeu suivant."""
    data = complete_grid(raw).sort_values(["id_site", "heure"], ignore_index=True)
    data["consommation_kwh_brute"] = data["brute"].where(data["brute"] >= 0)
    segment = pd.Index(bounds).searchsorted(data["heure"], side="right")
    imputed = [
        impute_site(group["consommation_kwh_brute"], max_gap)
        for _, group in data.groupby(["id_site", segment], sort=False)
    ]
    data = data.join(pd.concat(imputed))

    # Mêmes précisions que gold : NUMERIC(12, 3) pour les kWh, NUMERIC(10, 2) pour les kW
    data["consommation_kwh"] = data["consommation_kwh"].round(3)
    measured = data["consommation_kwh_brute"].notna()
    # Pic des minutes de l'heure : inconnu avec une mesure horaire, laissé vide
    data["pic_kw"] = float("nan")
    data["moyenne_kw"] = data["consommation_kwh"].round(2)
    # Comme l'ETL, qui n'impute que des trous de quelques minutes : une heure interpolée
    # ici n'aurait aucune mesure en gold. Sa valeur sert à l'entraînement, repérée par
    # methode_imputation, mais ne compte ni comme mesurée ni comme imputée.
    data["nb_mesures"] = measured.astype("int64") * MINUTES_PER_HOUR
    data["nb_imputees"] = 0
    data["taux_couverture"] = data["nb_mesures"] / MINUTES_PER_HOUR
    # Gold : vrai quand silver a les 60 minutes de l'heure, avec ou sans consommation.
    # Toutes les heures de l'historique sont terminées.
    data["heure_complete"] = True
    return data[[*GOLD_COLUMNS, "consommation_kwh_brute", "methode_imputation"]]


def split_bounds(
    hours: pd.Series, ratios: tuple[float, float] = SPLIT_RATIOS
) -> list[Any]:
    """Premières heures de la validation et du test, communes à tous les sites."""
    unique = hours.drop_duplicates().sort_values(ignore_index=True)
    n = len(unique)
    n_train = int(n * ratios[0])
    n_valid = int(n * ratios[1])
    if n_train == 0 or n_valid == 0 or n_train + n_valid >= n:
        raise ValueError(f"Pas assez d'heures ({n}) pour un découpage {ratios}")
    return [unique.iloc[n_train], unique.iloc[n_train + n_valid]]


def assign_split(
    data: pd.DataFrame, bounds: Sequence[Any] | None = None
) -> pd.DataFrame:
    """Ordonne chronologiquement et ajoute la colonne ``jeu``."""
    start_valid, start_test = bounds or split_bounds(data["heure"])
    ordered = data.sort_values(["heure", "id_site"], ignore_index=True)
    ordered["jeu"] = SPLITS[0]
    ordered.loc[ordered["heure"] >= start_valid, "jeu"] = SPLITS[1]
    ordered.loc[ordered["heure"] >= start_test, "jeu"] = SPLITS[2]
    return ordered


def load_anomalies(raw_dir: Path) -> pd.DataFrame:
    """Anomalies étiquetées des fichiers SITE00X_metadata.json."""
    rows = []
    for path in sorted(raw_dir.glob("SITE*_metadata.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        for anomaly in meta.get("anomalies", []):
            rows.append(
                {
                    "id_site": meta["site_id"],
                    "debut": anomaly["timestamp"],
                    "type": anomaly["type"],
                    "gravite": anomaly["severity"],
                    "description": anomaly.get("description"),
                }
            )
    anomalies = pd.DataFrame(
        rows, columns=["id_site", "debut", "type", "gravite", "description"]
    )
    anomalies["debut"] = to_utc(anomalies["debut"])
    return anomalies.sort_values(["debut", "id_site"], ignore_index=True)


def _counts(group: pd.DataFrame) -> dict[str, int]:
    return {
        "heures": len(group),
        "brutes_manquantes": int(group["consommation_kwh_brute"].isna().sum()),
        "imputees": int((group["methode_imputation"] != "none").sum()),
        "restant_manquantes": int(group["consommation_kwh"].isna().sum()),
        "nulles": int((group["consommation_kwh"] == 0).sum()),
    }


def quality_report(data: pd.DataFrame) -> dict[str, Any]:
    """Valeurs manquantes, imputées et nulles, au total, par site et par jeu."""
    periods = {
        jeu: {
            "debut": g["heure"].min().isoformat(),
            "fin": g["heure"].max().isoformat(),
        }
        for jeu, g in data.groupby("jeu", sort=False)
    }
    return {
        "total": _counts(data),
        "par_site": {site: _counts(g) for site, g in data.groupby("id_site")},
        "par_jeu": {
            jeu: _counts(g) | periods[jeu] for jeu, g in data.groupby("jeu", sort=False)
        },
        "imputation_max_heures": MAX_IMPUTED_GAP,
    }


def fingerprint(data: pd.DataFrame, anomalies: pd.DataFrame) -> str:
    """Empreinte du jeu et des anomalies, indépendante du format d'écriture du Parquet."""
    digest = hashlib.sha256()
    for frame in (data, anomalies):
        digest.update(
            pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes()
        )
    return digest.hexdigest()


def build(raw_dir: Path, out_dir: Path) -> DatasetFiles:
    """Produit le jeu, les anomalies et le rapport de qualité."""
    raw = load_raw(raw_dir / CSV_NAME)
    bounds = split_bounds(pd.Series(hour_range(raw)))
    data = assign_split(to_gold_format(raw, bounds=bounds), bounds)
    anomalies = load_anomalies(raw_dir)
    report = quality_report(data)

    out_dir.mkdir(parents=True, exist_ok=True)
    files = DatasetFiles(
        dataset=out_dir / "dataset.parquet",
        anomalies=out_dir / "anomalies.parquet",
        report=out_dir / "rapport_qualite.json",
        fingerprint=fingerprint(data, anomalies),
    )
    data.to_parquet(files.dataset, index=False)
    anomalies.to_parquet(files.anomalies, index=False)
    report["empreinte"] = files.fingerprint
    files.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = report["total"]
    logger.info(
        "jeu produit : %d heures, %d imputées, %d encore manquantes, empreinte %s",
        total["heures"],
        total["imputees"],
        total["restant_manquantes"],
        files.fingerprint[:12],
    )
    return files


def log_to_mlflow(files: DatasetFiles, source: Path) -> str:
    """Enregistre le jeu comme entrée d'un run MLflow et renvoie l'identifiant du run."""
    import mlflow
    from mlflow.data.dataset_source_registry import resolve_dataset_source
    from mlflow.data.pandas_dataset import from_pandas

    # MLflow enregistre la même source de fichiers locaux pour les chemins et les URI
    # file:// : il prévient d'une ambiguïté qui n'en est pas une
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", "The specified dataset source can be interpreted", UserWarning
        )
        dataset_source = resolve_dataset_source(str(source))

    data = pd.read_parquet(files.dataset)
    report = json.loads(files.report.read_text(encoding="utf-8"))
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=f"jeu-{files.fingerprint[:12]}") as run:
        for jeu in SPLITS:
            subset = data[data["jeu"] == jeu]
            dataset = from_pandas(
                subset,
                source=dataset_source,
                name=f"historique-csv-{jeu}",
                digest=files.fingerprint[:16],
            )
            mlflow.log_input(dataset, context=jeu)
        mlflow.log_params(
            {
                "source": source.name,
                "empreinte": files.fingerprint,
                "imputation_max_heures": MAX_IMPUTED_GAP,
                "decoupage": "/".join(
                    f"{r:.0%}" for r in (*SPLIT_RATIOS, 1 - sum(SPLIT_RATIOS))
                ),
                **{f"debut_{jeu}": report["par_jeu"][jeu]["debut"] for jeu in SPLITS},
            }
        )
        mlflow.log_metrics(
            {f"{jeu}_heures": report["par_jeu"][jeu]["heures"] for jeu in SPLITS}
        )
        mlflow.log_metrics({f"total_{k}": v for k, v in report["total"].items()})
        for path in (files.dataset, files.anomalies, files.report):
            mlflow.log_artifact(str(path), artifact_path="jeu")
        return str(run.info.run_id)


def main(argv: list[str] | None = None) -> DatasetFiles:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(os.environ.get("DATASET_RAW_DIR", DEFAULT_RAW_DIR)),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(os.environ.get("DATASET_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)),
    )
    parser.add_argument(
        "--sans-mlflow", action="store_true", help="ne pas enregistrer dans MLflow"
    )
    args = parser.parse_args(argv)
    # Sans adresse, MLflow écrirait dans un dossier mlruns local, sans prévenir
    if not args.sans_mlflow and not os.environ.get("MLFLOW_TRACKING_URI"):
        parser.error("MLFLOW_TRACKING_URI manquant (serveur MLflow), ou --sans-mlflow")

    files = build(args.raw_dir, args.out_dir)
    if not args.sans_mlflow:
        run_id = log_to_mlflow(files, args.raw_dir / CSV_NAME)
        logger.info("jeu enregistré dans MLflow : run %s", run_id)
    return files


if __name__ == "__main__":
    configure_logging("model")
    main()
