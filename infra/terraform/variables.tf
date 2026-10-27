variable "allowed_ips" {
  description = "Adresses IPv4 publiques autorisées à joindre le stockage : IP de sortie de la VM, plus celle d'un poste le temps d'une opération"
  type        = set(string)

  validation {
    condition     = length(var.allowed_ips) > 0
    error_message = "Au moins une IP est nécessaire : sans elle, la VM ne peut pas envoyer ses sauvegardes."
  }

  # Azure refuse les plages /31 et /32 dans ip_rules : des adresses seules,
  # chaque octet entre 0 et 255
  validation {
    condition = alltrue([
      for ip in var.allowed_ips : (
        can(regex("^(\\d{1,3}\\.){3}\\d{1,3}$", ip))
        && try(alltrue([for octet in split(".", ip) : tonumber(octet) <= 255]), false)
      )
    ])
    error_message = "Chaque entrée doit être une adresse IPv4 seule, sans masque (ex. 203.0.113.10)."
  }

  # Azure ne voit que l'IP publique de sortie (après le NAT du réseau), et refuse
  # les adresses privées dans ip_rules
  validation {
    condition     = alltrue([for ip in var.allowed_ips : !can(regex("^(10\\.|127\\.|169\\.254\\.|192\\.168\\.|172\\.(1[6-9]|2\\d|3[01])\\.|100\\.(6[4-9]|[7-9]\\d|1[01]\\d|12[0-7])\\.)", ip))])
    error_message = "Les adresses privées (10.x, 172.16-31.x, 192.168.x, etc.) ne sont pas acceptées : indiquer l'IP publique de sortie (curl -s https://ifconfig.me depuis la machine)."
  }
}

variable "environments" {
  description = "Environnements qui ont chacun leur conteneur (dépôt restic)"
  type        = set(string)
  default     = ["dev", "prod"]

  validation {
    condition     = length(setsubtract(var.environments, ["dev", "prod"])) == 0
    error_message = "Les environnements possibles sont dev et prod."
  }
}

variable "project_name" {
  description = "Nom du projet, utilisé dans les noms et les tags des ressources"
  type        = string
  default     = "enervision"
}

variable "replication_type" {
  description = "Redondance du compte de stockage : LRS (3 copies dans un centre), ZRS (3 zones) ou GRS (copie vers francesouth)"
  type        = string
  default     = "LRS"

  validation {
    condition     = contains(["LRS", "ZRS", "GRS"], var.replication_type)
    error_message = "La redondance doit être LRS, ZRS ou GRS."
  }
}

variable "resource_group_name" {
  description = "Groupe de ressources existant qui accueille le stockage (créé par l'administrateur de l'abonnement). Sa région donne celle du stockage"
  type        = string
}

variable "retention_days" {
  description = "Nombre de jours pendant lesquels un blob supprimé ou écrasé reste récupérable (protection contre une suppression ou un rançongiciel)"
  type        = number
  default     = 30

  validation {
    condition     = var.retention_days >= 7 && var.retention_days <= 365
    error_message = "La rétention doit être comprise entre 7 et 365 jours."
  }
}

variable "storage_account_name" {
  description = "Nom du compte de stockage, unique dans tout Azure"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "Le nom doit faire de 3 à 24 caractères, en minuscules et chiffres uniquement."
  }
}

variable "subscription_id" {
  description = "Identifiant de l'abonnement Azure"
  type        = string
}

variable "tags" {
  description = "Tags ajoutés à ceux du projet, par exemple ceux qu'impose une policy de l'abonnement"
  type        = map(string)
  default     = {}
}

variable "versioning_enabled" {
  description = "Active le versioning des blobs et la politique de cycle de vie qui purge les anciennes versions après retention_days. Nécessite le droit Microsoft.Storage/storageAccounts/managementPolicies/write ; sans lui, mettre false (la suppression réversible reste active)"
  type        = bool
  default     = true
}
