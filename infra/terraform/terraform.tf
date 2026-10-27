terraform {
  required_version = ">= 1.17"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.11"
    }
  }

  # Configuration partielle : les noms du compte d'état sont dans backend.hcl
  # (voir backend.hcl.example). Accès par Entra ID, sans clé de compte.
  backend "azurerm" {
    use_azuread_auth = true
  }
}
