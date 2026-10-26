import json
from pathlib import Path

import pandas as pd
import pytest

from model import dataset

NAN = float("nan")


def _raw(values: dict[str, list[float]], start: str = "2023-01-01") -> pd.DataFrame:
    rows = []
    for site, series in values.items():
        hours = pd.date_range(start, periods=len(series), freq="h", tz="UTC")
        rows += [
            {"id_site": site, "heure": h, "brute": v} for h, v in zip(hours, series)
        ]
    return pd.DataFrame(rows)


def _write_csv(path: Path, values: dict[str, list[float]]) -> None:
    rows = []
    for site, series in values.items():
        hours = pd.date_range("2023-01-01", periods=len(series), freq="h")
        rows += [
            {
                "timestamp": h.strftime("%Y-%m-%d %H:%M:%S"),
                "site_id": site,
                "consumption_kwh": v,
            }
            for h, v in zip(hours, series)
        ]
    pd.DataFrame(rows).to_csv(path, index=False)


class TestImputation:
    def test_comble_un_trou_court_par_interpolation(self) -> None:
        result = dataset.impute_site(pd.Series([10.0, NAN, NAN, 40.0]))
        assert result["consommation_kwh"].tolist() == [10.0, 20.0, 30.0, 40.0]
        assert result["methode_imputation"].tolist() == [
            "none",
            "linear_interpolation",
            "linear_interpolation",
            "none",
        ]

    def test_laisse_vide_un_trou_trop_long(self) -> None:
        result = dataset.impute_site(pd.Series([10.0, NAN, NAN, NAN, 50.0]))
        assert result["consommation_kwh"].isna().sum() == 3
        assert (result["methode_imputation"] == "none").all()

    def test_ne_comble_pas_un_trou_en_debut_ou_en_fin_de_serie(self) -> None:
        result = dataset.impute_site(pd.Series([NAN, 10.0, 20.0, NAN]))
        assert result["consommation_kwh"].isna().tolist() == [True, False, False, True]

    def test_perte_reseau_longue_puis_trou_court(self) -> None:
        brute = pd.Series([1.0, *[NAN] * 8, 10.0, NAN, 12.0])
        result = dataset.impute_site(brute)
        assert result["consommation_kwh"].iloc[1:9].isna().all()
        assert result["consommation_kwh"].iloc[10] == pytest.approx(11.0)


class TestFormatGold:
    def test_colonnes_et_valeurs_de_gold_consommation_horaire(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [5.0, NAN, 7.0]}))
        assert list(data.columns) == [
            *dataset.GOLD_COLUMNS,
            "consommation_kwh_brute",
            "methode_imputation",
        ]
        assert data["consommation_kwh"].tolist() == [5.0, 6.0, 7.0]
        assert data["consommation_kwh_brute"].isna().tolist() == [False, True, False]
        assert data["nb_mesures"].tolist() == [60, 60, 60]
        assert data["nb_imputees"].tolist() == [0, 60, 0]
        assert data["taux_couverture"].tolist() == [1.0, 1.0, 1.0]
        assert (data["moyenne_kw"] == data["consommation_kwh"]).all()
        assert data["pic_kw"].isna().all()

    def test_heure_sans_consommation_a_une_couverture_nulle(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [5.0, NAN, NAN, NAN, 9.0]}))
        assert data["taux_couverture"].tolist() == [1.0, 0.0, 0.0, 0.0, 1.0]
        assert data["nb_mesures"].tolist() == [60, 0, 0, 0, 60]

    def test_consommation_negative_traitee_comme_manquante(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [5.0, -3.0, 7.0]}))
        assert pd.isna(data["consommation_kwh_brute"].iloc[1])
        assert data["consommation_kwh"].iloc[1] == pytest.approx(6.0)

    def test_garde_les_zeros_des_coupures(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [5.0, 0.0, 7.0]}))
        assert data["consommation_kwh"].iloc[1] == 0.0
        assert data["nb_imputees"].iloc[1] == 0

    def test_complete_les_heures_absentes_et_retire_les_doublons(self) -> None:
        raw = _raw({"SITE001": [1.0, 2.0, 3.0, 4.0]})
        raw = pd.concat([raw.drop(index=2), raw.iloc[[0]]], ignore_index=True)
        data = dataset.to_gold_format(raw)
        assert len(data) == 4
        assert data["heure"].is_monotonic_increasing
        assert data["consommation_kwh"].iloc[2] == pytest.approx(3.0)

    def test_horodatages_en_utc(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [1.0]}))
        assert str(data["heure"].dt.tz) == "UTC"


class TestDecoupage:
    def test_proportions_chronologiques_sans_recouvrement(self) -> None:
        data = dataset.to_gold_format(
            _raw({"SITE001": [1.0] * 100, "SITE002": [2.0] * 100})
        )
        split = dataset.assign_split(data)

        assert split["heure"].is_monotonic_increasing
        hours = split.groupby("jeu")["heure"]
        assert hours.nunique().to_dict() == {
            "entrainement": 70,
            "validation": 15,
            "test": 15,
        }
        assert hours.max()["entrainement"] < hours.min()["validation"]
        assert hours.max()["validation"] < hours.min()["test"]

    def test_une_meme_heure_est_dans_un_seul_jeu_pour_tous_les_sites(self) -> None:
        data = dataset.to_gold_format(
            _raw({"SITE001": [1.0] * 20, "SITE002": [2.0] * 20})
        )
        split = dataset.assign_split(data)
        assert (split.groupby("heure")["jeu"].nunique() == 1).all()

    def test_refuse_un_jeu_trop_petit(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [1.0, 2.0]}))
        with pytest.raises(ValueError, match="Pas assez"):
            dataset.assign_split(data)


class TestConstruction:
    def test_produit_le_jeu_les_anomalies_et_le_rapport(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        _write_csv(
            raw_dir / dataset.CSV_NAME,
            {"SITE001": [1.0, NAN, 3.0, *[4.0] * 37], "SITE002": [*[2.0] * 39, NAN]},
        )
        meta = {
            "site_id": "SITE001",
            "anomalies": [
                {
                    "timestamp": "2023-01-01T05:00:00",
                    "type": "outage",
                    "severity": "critical",
                }
            ],
        }
        (raw_dir / "SITE001_metadata.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        files = dataset.build(raw_dir, tmp_path / "out")

        data = pd.read_parquet(files.dataset)
        assert len(data) == 80
        assert set(data["jeu"]) == set(dataset.SPLITS)
        anomalies = pd.read_parquet(files.anomalies)
        assert anomalies.loc[0, "type"] == "outage"
        assert str(anomalies["debut"].dt.tz) == "UTC"

        report = json.loads(files.report.read_text(encoding="utf-8"))
        assert report["total"]["imputees"] == 1
        assert report["total"]["restant_manquantes"] == 1
        assert report["par_site"]["SITE002"]["brutes_manquantes"] == 1
        assert report["empreinte"] == files.fingerprint

    def test_empreinte_stable_et_sensible_au_contenu(self) -> None:
        data = dataset.to_gold_format(_raw({"SITE001": [1.0, 2.0, 3.0]}))
        anomalies = pd.DataFrame(
            {"id_site": ["SITE001"], "type": ["spike"], "gravite": ["high"]}
        )
        changed = data.copy()
        changed.loc[1, "consommation_kwh"] = 9.0
        relabeled = anomalies.assign(gravite=["low"])
        reference = dataset.fingerprint(data, anomalies)
        assert reference == dataset.fingerprint(data.copy(), anomalies.copy())
        assert reference != dataset.fingerprint(changed, anomalies)
        assert reference != dataset.fingerprint(data, relabeled)

    def test_main_sans_mlflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        _write_csv(raw_dir / dataset.CSV_NAME, {"SITE001": [1.0] * 40})

        def fail(*_: object) -> str:
            raise AssertionError("MLflow ne doit pas être appelé")

        monkeypatch.setattr(dataset, "log_to_mlflow", fail)
        files = dataset.main(
            [
                "--raw-dir",
                str(raw_dir),
                "--out-dir",
                str(tmp_path / "out"),
                "--sans-mlflow",
            ]
        )
        assert files.dataset.exists()


class TestMlflow:
    def test_enregistre_les_trois_jeux_les_parametres_et_les_fichiers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mlflow

        monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
        # Stockage en fichiers : suffisant pour un test, sans les dépendances du serveur
        monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri((tmp_path / "mlruns").as_uri())
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        _write_csv(
            raw_dir / dataset.CSV_NAME, {"SITE001": [1.0, NAN, 3.0, *[4.0] * 37]}
        )
        files = dataset.build(raw_dir, tmp_path / "out")

        run_id = dataset.log_to_mlflow(files, raw_dir / dataset.CSV_NAME)

        run = mlflow.MlflowClient().get_run(run_id)
        assert run.data.params["empreinte"] == files.fingerprint
        assert run.data.params["decoupage"] == "70%/15%/15%"
        assert run.data.metrics["total_imputees"] == 1
        contexts = {i.tags[0].value for i in run.inputs.dataset_inputs}
        assert contexts == set(dataset.SPLITS)
        artifacts = {
            a.path for a in mlflow.MlflowClient().list_artifacts(run_id, "jeu")
        }
        assert artifacts == {
            "jeu/dataset.parquet",
            "jeu/anomalies.parquet",
            "jeu/rapport_qualite.json",
        }
