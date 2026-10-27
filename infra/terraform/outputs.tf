output "resource_group_name" {
  description = "Groupe de ressources du stockage des sauvegardes"
  value       = data.azurerm_resource_group.main.name
}

output "restic_repositories" {
  description = "Valeur de RESTIC_REPOSITORY pour chaque environnement"
  value       = { for env, container in azurerm_storage_container.restic : env => "azure:${container.name}:/" }
}

output "storage_account_name" {
  description = "Nom du compte de stockage (AZURE_ACCOUNT_NAME pour restic)"
  value       = azurerm_storage_account.main.name
}
