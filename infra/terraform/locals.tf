locals {
  # azurerm n'a pas de default_tags : chaque ressource reprend ces tags
  common_tags = merge(var.tags, {
    ManagedBy = "Terraform"
    Project   = var.project_name
    Usage     = "sauvegarde-restic"
  })
}
