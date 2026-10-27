# Stockage Azure des sauvegardes (Terraform)

Ce dossier crée le stockage **hors de la VM** où restic envoie les sauvegardes chiffrées des bases (SMARTOPS-53). Si la VM est perdue, les sauvegardes restent dans Azure.

| Ressource | Rôle |
|---|---|
| groupe de ressources (`resource_group_name`) | **existant**, fourni par l'administrateur de l'abonnement : Terraform le lit sans le créer. Il doit être en France |
| compte de stockage (`storage_account_name`) | HTTPS et TLS 1.2 uniquement, aucun accès public, ouvert seulement aux IP de `allowed_ips`, double chiffrement au repos |
| conteneurs `restic-dev` et `restic-prod` | un dépôt restic par environnement, privés |
| suppression réversible | un blob supprimé reste récupérable pendant `retention_days` (30 jours par défaut), puis Azure le purge tout seul |
| versioning et politique de cycle de vie (`versioning_enabled`) | un blob écrasé reste aussi récupérable, et les anciennes versions sont purgées après `retention_days`. Les deux vont ensemble : sans la purge, chaque `restic prune` laisserait des versions jamais supprimées, et la facture grossirait sans limite. À désactiver (`false`) si le rôle n'a pas le droit `managementPolicies/write` |

Le compte et les conteneurs ont `prevent_destroy` : Terraform refuse de les supprimer.

## Choix

- **Région en France** (celle du groupe de ressources, `francecentral` ou `francesouth`, vérifiée par une précondition) : les données des sites restent en France (RGPD, souveraineté).
- **Chiffrement côté client** : restic chiffre tout avant l'envoi, Azure ne voit que des données chiffrées. Les clés gérées par le client dans Key Vault (Trivy `AZU-0060`) n'apportent donc pas grand-chose ici, pour un coût et une complexité en plus.
- **Redondance `LRS`** par défaut (3 copies dans un centre de données), le moins cher. La sauvegarde est déjà une copie hors site de la base : passer en `GRS` (Trivy `AZU-0058`) se fait en changeant `replication_type`.
- **Pas de journaux de diagnostic** (Trivy `AZU-0057`) : ils demandent un espace Log Analytics payant. Le suivi des sauvegardes passe par la supervision (SMARTOPS-56).
- **Pas d'apply depuis la CI** : il faudrait stocker un principal de service Azure dans GitHub. La CI ne fait que `fmt`, `validate`, `tflint` et le scan Trivy (`terraform.yml`, `security.yml`).

## Prérequis

- [Terraform](https://developer.hashicorp.com/terraform/install) 1.17 ou plus et [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- Un compte Azure qui peut créer des comptes de stockage dans le groupe de ressources et y attribuer un rôle (`Microsoft.Authorization/roleAssignments/write`)
- `az login`, puis `az account set --subscription <id>`

## Amorçage (une seule fois)

L'état Terraform contient la clé du compte de stockage (le provider `azurerm` n'a pas d'équivalent éphémère). Il est donc rangé dans un compte à part, sans clé partagée, accessible seulement par Entra ID. Ce compte, créé dans le même groupe de ressources, n'est pas géré par Terraform (remplacer `<groupe>`, et ajouter avec `--tags` les tags qu'une policy impose) :

```bash
az storage account create --name enervisiontfstate --resource-group <groupe> --location francecentral --sku Standard_LRS --min-tls-version TLS1_2 --allow-blob-public-access false --allow-shared-key-access false
```

```bash
az role assignment create --assignee "$(az ad signed-in-user show --query id -o tsv)" --role "Storage Blob Data Contributor" --scope "$(az storage account show --name enervisiontfstate --resource-group <groupe> --query id -o tsv)"
```

```bash
az storage container create --name tfstate --account-name enervisiontfstate --auth-mode login
```

Chaque personne qui lance Terraform a besoin du rôle **Storage Blob Data Contributor** sur ce compte (commande `az role assignment create` ci-dessus). Le rôle met quelques minutes à s'appliquer : d'ici là, `terraform init` échoue en `403 AuthorizationPermissionMismatch`.

### Abonnement du cours (`rg-<login>_cours-projet-eadl`)

Le rôle `Devops-cours-projet-eadl` et les policies de l'abonnement imposent :

| Contrainte | Réglage |
|---|---|
| pas de création de groupe de ressources | `resource_group_name = "rg-<login>_cours-projet-eadl"` |
| tag `user` égal à celui du groupe sur chaque ressource | `tags = { user = "<login>" }`, et `--tags user=<login>` à l'amorçage |
| pas de droit sur les politiques de cycle de vie | `versioning_enabled = false` : pas de versioning, la suppression réversible protège seule. restic n'écrase presque jamais un fichier (ils sont nommés par leur contenu) : une sauvegarde supprimée par erreur ou avec un SAS volé reste récupérable pendant `retention_days` |
| `Standard_LRS` seulement, 2 comptes de stockage au plus, `francecentral` | valeurs par défaut (compte d'état + compte des sauvegardes) |
| pas de suppression d'attribution de rôle | le rôle de l'amorçage reste orphelin si le compte d'état est supprimé, sans effet ni coût |

## Créer ou modifier le stockage

```bash
cd infra/terraform
cp backend.hcl.example backend.hcl            # noms du compte d'état
cp terraform.tfvars.example terraform.tfvars  # abonnement, nom du compte, IP de la VM
terraform init -backend-config=backend.hcl
terraform plan -out=backup.tfplan
terraform apply backup.tfplan
```

`backend.hcl`, `terraform.tfvars`, `*.tfplan` et l'état ne sont jamais commités. Le fichier `.terraform.lock.hcl` l'est : il fixe la version du provider. Pour ajouter une plateforme : `terraform providers lock -platform=linux_amd64 -platform=windows_amd64 -platform=darwin_arm64 -platform=darwin_amd64`.

Le compte n'accepte que les IP de `allowed_ips`. Pour lire les conteneurs depuis un poste (test, restauration), ajouter son IP le temps de l'opération, puis la retirer.

## Donner l'accès à restic

restic n'utilise pas la clé du compte, mais un **SAS limité à un conteneur** : celui de dev ne lit pas prod. Le SAS s'appuie sur une **politique d'accès stockée** (`restic`) du conteneur, qui porte ses droits et sa date d'expiration : supprimer la politique révoque le SAS de cet environnement seul, sans toucher à l'autre.

Pour chaque environnement (ici `restic-prod`), avec `<compte>` = `terraform output -raw storage_account_name` et `<groupe>` = `resource_group_name` :

```bash
az storage container policy create --account-name <compte> --account-key "$(az storage account keys list -n <compte> -g <groupe> --query [0].value -o tsv)" -c restic-prod -n restic --permissions racwdl --expiry 2027-10-31T00:00Z
```

```bash
az storage container generate-sas --account-name <compte> --account-key "$(az storage account keys list -n <compte> -g <groupe> --query [0].value -o tsv)" -n restic-prod --policy-name restic --https-only -o tsv
```

Sous Windows PowerShell, les guillemets doubles imbriqués sont retirés : lancer ces commandes depuis Git Bash ou WSL.

| Variable restic | Valeur | Dans GitHub (Settings → Secrets and variables → Actions) |
|---|---|---|
| `AZURE_ACCOUNT_NAME` | `terraform output storage_account_name` | variable `AZURE_ACCOUNT_NAME` (un seul compte pour dev et prod) |
| `AZURE_ACCOUNT_SAS` | le SAS généré ci-dessus | secrets `DEV_AZURE_ACCOUNT_SAS` / `PROD_AZURE_ACCOUNT_SAS` |
| `RESTIC_REPOSITORY` | `terraform output restic_repositories` | pas un secret |

Le branchement de ces secrets dans le déploiement relève de SMARTOPS-53.

## Vérifier que la VM peut écrire

Azure ne voit pas l'IP privée de la VM (`10.43.43.x`) mais l'**IP publique de sortie** du réseau de l'école : c'est elle qui va dans `allowed_ips` (les adresses privées y sont refusées).

Le workflow **Azure storage check** (`.github/workflows/azure-storage-check.yml`) tourne sur le runner de la VM : il affiche cette IP, puis envoie, relit et supprime un fichier de test dans `restic-dev` (`restic-prod` depuis `main`). Il se lance **à la main seulement** (Actions → Azure storage check → Run workflow), une fois sur la branche par défaut : jamais sur `pull_request`, car le dépôt est public (voir `infra/runner.md`, « Limite connue »). En cas de HTTP 403, ajouter l'IP affichée dans `allowed_ips`, puis `terraform plan` et `apply`.

- **Expiration** : un SAS expiré bloque les sauvegardes. Avant la date, prolonger la politique (`az storage container policy update ... -n restic --expiry <nouvelle date>`) : le SAS existant reste valable, rien à changer dans GitHub.
- **SAS d'un environnement compromis** : supprimer sa politique (`az storage container policy delete ... -c restic-prod -n restic`). Le SAS est refusé en moins d'une minute, l'autre environnement continue de fonctionner. Recréer ensuite la politique, générer un nouveau SAS et mettre à jour le secret GitHub. Les sauvegardes supprimées entre-temps restent récupérables grâce à la suppression réversible.
- **Clé du compte compromise** : `az storage account keys renew --account-name <compte> --resource-group <groupe> --key primary` invalide tous les SAS signés avec cette clé, dev et prod en même temps ; régénérer ensuite les deux.
