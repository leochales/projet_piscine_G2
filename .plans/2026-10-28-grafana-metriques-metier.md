# SMARTOPS-105 — Métriques métier dans Grafana

## Goal / Out of scope

Totaux déjà en base, affichés dans Grafana. Hors périmètre : VM, Keycloak, alertes Prometheus, Pushgateway (SMARTOPS-82).

## Approach

Vue `gold.supervision_metier` lue par le postgres-exporter déjà en place. Le compte monitoring ne reçoit que cette vue. Pas de code dans l'ETL ni le modèle : les cron s'arrêtent, les totaux restent en base.

## Fait

- [x] `db/19_supervision_metier.sql` et test SQL (monitoring lit les totaux, pas les tables).
- [x] `infra/monitoring/postgres-exporter/queries.yaml` branché dans `compose-local.yml`.
- [x] Tableau `infra/monitoring/grafana/dashboards/enervision-metier.json`.
