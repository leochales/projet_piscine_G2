import os
import time
from dataclasses import replace

import mlflow
import numpy as np
import pandas as pd
import pytest

from model import registre
from model.entrainement import (
    REFERENCE,
    REGLAGES,
    entrainer_horizon,
    entrainer_modele_final,
    main,
    preparer,
)
from model.features import noms_variables
from model.tests.test_entrainement import faux_jeu, moyennes_entrainement

# Stockage en fichiers de MLflow (test seulement) : codecs.open, déprécié en Python 3.14
pytestmark = pytest.mark.filterwarnings("ignore:codecs.open:DeprecationWarning")


def resultat_et_final(bruit: float = 0.1):
    df = faux_jeu(bruit)
    r = entrainer_horizon(df, moyennes_entrainement(df), 24)
    final = entrainer_modele_final(df, 24, r.meilleur) if r.bat_reference else None
    return df, r, final


def test_metriques_sans_pourcent():
    """MLflow refuse « % » dans un nom de métrique."""
    tableau = pd.DataFrame(
        {"MAE": [1.0], "RMSE": [2.0], "WAPE_%": [3.0]}, index=["random_forest"]
    )
    assert registre.metriques(tableau, "test") == {
        "test_random_forest_MAE": 1.0,
        "test_random_forest_RMSE": 2.0,
        "test_random_forest_WAPE": 3.0,
    }


def test_modele_enregistre_puis_recharge(client):
    """Le modèle et ses moyennes par site reviennent à l'identique, par l'alias que
    SMARTOPS-33 utilisera."""
    df, r, final = resultat_et_final()
    version = registre.enregistrer(r, 24, REGLAGES[r.meilleur], "abc123", final)
    assert version == "1"

    production = registre.charger(24)
    assert production.version == "prevision-conso-24h/1"
    moyennes = production.moyennes
    pd.testing.assert_series_equal(moyennes, final[1], check_names=False)
    lignes = preparer(df, moyennes, 24)
    X = lignes[noms_variables(24, moyennes)]
    np.testing.assert_allclose(production.modele.predict(X), final[0].predict(X))

    # Le run garde les paramètres, les scores et l'empreinte du jeu
    run = client.get_run(
        client.get_model_version_by_alias(
            registre.nom_modele(24), registre.ALIAS
        ).run_id
    )
    assert run.data.params["empreinte_jeu"] == "abc123"
    assert run.data.params["modele"] == r.meilleur
    assert run.data.tags["bat_reference"] == "true"
    assert run.data.tags["bat_reference_test"] == "true"
    assert "réentraîné sur toutes les données" in run.data.tags["mlflow.note.content"]
    assert f"validation_{REFERENCE}_WAPE" in run.data.metrics
    assert f"test_{r.meilleur}_WAPE" in run.data.metrics


def test_cache_telecharge_une_seule_fois(client, tmp_path, monkeypatch):
    """Avec un cache, la version est téléchargée au premier appel, puis lue sur le
    disque : MLflow ne sert plus qu'à lire le numéro de la version production."""
    df, r, final = resultat_et_final()
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "abc123", final)
    cache = tmp_path / "cache"
    premiere = registre.charger(24, cache)
    (dossier,) = (cache / "prevision-conso-24h").iterdir()
    assert dossier.name.startswith("1-")
    assert (dossier / registre.MOYENNES).exists()

    def pas_de_telechargement(*args, **kwargs):
        raise AssertionError("version déjà en cache : rien à télécharger")

    monkeypatch.setattr(mlflow.artifacts, "download_artifacts", pas_de_telechargement)
    seconde = registre.charger(24, cache)
    assert seconde.version == premiere.version == "prevision-conso-24h/1"
    pd.testing.assert_series_equal(seconde.moyennes, final[1], check_names=False)
    lignes = preparer(df, seconde.moyennes, 24)
    X = lignes[noms_variables(24, seconde.moyennes)]
    np.testing.assert_allclose(seconde.modele.predict(X), final[0].predict(X))


def vieillir(dossier, heures=2):
    """Date de modification reculée : dossier inutilisé depuis ``heures`` heures."""
    passe = time.time() - heures * 3600
    os.utime(dossier, (passe, passe))


def test_cache_supprime_les_dossiers_inutilises(client, tmp_path):
    """Ancienne version et téléchargement abandonné, inutilisés depuis plus de
    DELAI_NETTOYAGE : supprimés au lancement suivant."""
    _, r, final = resultat_et_final()
    cache = tmp_path / "cache"
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v1", final)
    registre.charger(24, cache)
    (ancienne,) = (cache / "prevision-conso-24h").iterdir()
    # Dossier temporaire d'un lancement tué en plein téléchargement
    abandonne = cache / "prevision-conso-24h" / ".en-cours-abc"
    abandonne.mkdir()
    vieillir(ancienne)
    vieillir(abandonne)
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v2", final)
    assert registre.charger(24, cache).version == "prevision-conso-24h/2"
    restants = [d.name for d in (cache / "prevision-conso-24h").iterdir()]
    assert len(restants) == 1
    assert restants[0].startswith("2-")


def test_cache_laisse_les_dossiers_d_un_autre_lancement(client, tmp_path):
    """Deux lancements qui se chevauchent : la version qu'un autre lancement vient
    d'utiliser et son téléchargement en cours ne sont pas effacés."""
    _, r, final = resultat_et_final()
    cache = tmp_path / "cache"
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v1", final)
    registre.charger(24, cache)
    (ancienne,) = (cache / "prevision-conso-24h").iterdir()
    en_cours = cache / "prevision-conso-24h" / ".en-cours-abc"
    en_cours.mkdir()
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v2", final)
    registre.charger(24, cache)
    assert ancienne.exists()
    assert en_cours.exists()
    # La version 1, utilisée par l'autre lancement, reste lisible
    vieille = registre.MlflowClient().get_model_version(registre.nom_modele(24), "1")
    assert registre.telecharger(registre.nom_modele(24), vieille, cache) == ancienne


def test_cache_modele_reenregistre_depuis_la_version_1(client, tmp_path):
    """Un modèle supprimé puis réenregistré repart à la version 1 : le cache ne doit
    pas resservir l'ancienne version 1."""
    df, r, final = resultat_et_final()
    cache = tmp_path / "cache"
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "ancien", final)
    registre.charger(24, cache)
    client.delete_registered_model(registre.nom_modele(24))
    autre_modele, moyennes = entrainer_modele_final(df, 24, "ridge")
    registre.enregistrer(
        r, 24, REGLAGES[r.meilleur], "nouveau", (autre_modele, moyennes)
    )
    production = registre.charger(24, cache)
    assert production.version == "prevision-conso-24h/1"
    assert type(production.modele) is type(autre_modele)


def test_cache_sans_version_incomplete(client, tmp_path, monkeypatch):
    """Un téléchargement qui échoue ne laisse rien dans le cache : le lancement
    suivant retélécharge la version entière."""
    _, r, final = resultat_et_final()
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "abc123", final)
    vrai = mlflow.artifacts.download_artifacts

    def echec_sur_les_moyennes(*args, **kwargs):
        if kwargs.get("artifact_path") == registre.MOYENNES:
            raise OSError("connexion coupée")
        return vrai(*args, **kwargs)

    monkeypatch.setattr(mlflow.artifacts, "download_artifacts", echec_sur_les_moyennes)
    cache = tmp_path / "cache"
    with pytest.raises(OSError):
        registre.charger(24, cache)
    assert list((cache / "prevision-conso-24h").iterdir()) == []
    monkeypatch.setattr(mlflow.artifacts, "download_artifacts", vrai)
    assert registre.charger(24, cache).version == "prevision-conso-24h/1"


def test_nouvelle_version_prend_l_alias(client):
    _, r, final = resultat_et_final()
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v1", final)
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v2", final)
    production = client.get_model_version_by_alias(
        registre.nom_modele(24), registre.ALIAS
    )
    # MLflow 3 donne le numéro de version en entier, enregistrer le renvoie en texte
    assert str(production.version) == "2"


def test_modele_refuse_garde_le_run_sans_version(client):
    """Règle de SMARTOPS-30 : un modèle qui ne bat pas la référence sur la validation
    n'est pas enregistré, mais son run reste pour la trace."""
    _, r, final = resultat_et_final(bruit=0.0)
    assert not r.bat_reference
    assert registre.enregistrer(r, 24, REGLAGES[r.meilleur], "abc123", final) is None
    assert len(client.search_registered_models()) == 0
    runs = mlflow.search_runs(
        experiment_names=[registre.EXPERIENCE], output_format="list"
    )
    assert len(runs) == 1
    assert runs[0].data.tags["bat_reference"] == "false"
    assert "Aucun modèle enregistré" in runs[0].data.tags["mlflow.note.content"]


def test_main_enregistre_les_deux_horizons(client, tmp_path):
    chemin = tmp_path / "dataset.parquet"
    faux_jeu().drop(columns=["baseline_veille", REFERENCE]).to_parquet(chemin)
    (tmp_path / "rapport_qualite.json").write_text('{"empreinte": "abc123"}')
    main(["--chemin", str(chemin)])
    for horizon in (24, 168):
        production = registre.charger(horizon)
        assert list(production.moyennes.index) == ["SITE001", "SITE002"]
        assert hasattr(production.modele, "predict")


def test_modele_final_garde_les_sites_recents(client, tmp_path):
    """Un site mis en service après la date de coupure n'est pas évalué, mais le
    modèle de production l'apprend : SMARTOPS-33 pourra le prévoir."""
    df = faux_jeu().drop(columns=["baseline_veille", REFERENCE])
    recent = (df["id_site"] == "SITE002") & (df["jeu"] == "entrainement")
    chemin = tmp_path / "dataset.parquet"
    df[~recent].to_parquet(chemin)
    (tmp_path / "rapport_qualite.json").write_text('{"empreinte": "abc123"}')
    resultats = main(["--chemin", str(chemin)])
    # Évaluation sur SITE001 seulement
    assert list(resultats[0].par_site.index) == ["SITE001"]
    assert list(registre.charger(24).moyennes.index) == ["SITE001", "SITE002"]


def test_modele_moins_bon_que_la_production_garde_l_alias(client):
    """SMARTOPS-34 : un modèle qui bat la référence mais pas la version en production
    n'est pas enregistré, l'alias ne bouge pas. Le run reste pour la trace."""
    _, r, final = resultat_et_final()
    registre.enregistrer(r, 24, REGLAGES[r.meilleur], "v1", final)
    moins_bon = replace(r, bat_production=False)
    assert (
        registre.enregistrer(moins_bon, 24, REGLAGES[r.meilleur], "v2", final) is None
    )
    production = client.get_model_version_by_alias(
        registre.nom_modele(24), registre.ALIAS
    )
    assert str(production.version) == "1"
    runs = mlflow.search_runs(
        experiment_names=[registre.EXPERIENCE], output_format="list"
    )
    assert len(runs) == 2
    derniers = {run.data.tags["bat_production"] for run in runs}
    assert derniers == {"sans_production", "false"}
    assert any(
        "version en production" in run.data.tags["mlflow.note.content"] for run in runs
    )
