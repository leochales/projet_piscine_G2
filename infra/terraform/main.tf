# Groupe fourni par l'administrateur de l'abonnement : Terraform ne le crée pas
data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

# Les sauvegardes restic sont chiffrées par restic avant l'envoi : Azure ne voit
# que des données chiffrées. Le compte ajoute son propre chiffrement au repos.
resource "azurerm_storage_account" "main" {
  name                              = var.storage_account_name
  resource_group_name               = data.azurerm_resource_group.main.name
  location                          = data.azurerm_resource_group.main.location
  account_kind                      = "StorageV2"
  account_tier                      = "Standard"
  account_replication_type          = var.replication_type
  access_tier                       = "Hot"
  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  allow_nested_items_to_be_public   = false
  cross_tenant_replication_enabled  = false
  infrastructure_encryption_enabled = true
  default_to_oauth_authentication   = true
  # Nécessaire pour signer les SAS limités à un conteneur que restic utilise
  shared_access_key_enabled = true

  blob_properties {
    # Versioning seulement si ses anciennes versions sont purgées (politique de
    # cycle de vie ci-dessous) : sinon chaque prune de restic les accumulerait sans
    # limite. restic n'écrase presque jamais un fichier (ils sont nommés par leur
    # contenu) : la suppression réversible suffit alors à rendre récupérable, pendant
    # retention_days, une sauvegarde supprimée par erreur ou avec un SAS volé.
    versioning_enabled = var.versioning_enabled

    delete_retention_policy {
      days = var.retention_days
    }

    container_delete_retention_policy {
      days = var.retention_days
    }
  }

  # Seules les IP listées joignent le compte
  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    ip_rules       = var.allowed_ips
  }

  tags = local.common_tags

  lifecycle {
    prevent_destroy = true

    # Les données des sites restent en France (RGPD, souveraineté)
    precondition {
      condition     = contains(["francecentral", "francesouth"], data.azurerm_resource_group.main.location)
      error_message = "Le groupe de ressources doit être en France (francecentral ou francesouth)."
    }
  }
}

# Un dépôt restic par environnement : un SAS donné à dev ne lit pas prod
resource "azurerm_storage_container" "restic" {
  for_each = var.environments

  name                  = "restic-${each.key}"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"

  # Le conteneur porte les sauvegardes : retirer un environnement de la liste
  # ne doit pas les supprimer
  lifecycle {
    prevent_destroy = true
  }
}

# Les anciennes versions gardées par le versioning sont supprimées après
# retention_days, sinon chaque prune de restic ferait grossir la facture
resource "azurerm_storage_management_policy" "main" {
  count = var.versioning_enabled ? 1 : 0

  storage_account_id = azurerm_storage_account.main.id

  rule {
    name    = "purge-anciennes-versions"
    enabled = true

    filters {
      blob_types = ["blockBlob"]
    }

    actions {
      version {
        delete_after_days_since_creation = var.retention_days
      }
    }
  }
}
