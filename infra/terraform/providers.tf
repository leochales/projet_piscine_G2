provider "azurerm" {
  subscription_id = var.subscription_id

  # Opérations sur les blobs par Entra ID plutôt qu'avec la clé du compte
  storage_use_azuread = true

  features {}
}
