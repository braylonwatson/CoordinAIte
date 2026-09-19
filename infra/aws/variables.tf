variable "region" {
  type    = string
  default = "us-east-1"
}
variable "name" {
  type    = string
  default = "coordinaite"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.name))
    error_message = "Use 3–20 lowercase letters, numbers, and hyphens, starting with a letter."
  }
}
variable "frontend_url" {
  type        = string
  description = "Exact production Vercel origin, with https:// and no trailing slash."
  validation {
    condition     = can(regex("^https://[^/]+$", var.frontend_url))
    error_message = "Supply an HTTPS origin without a path or trailing slash."
  }
}
variable "additional_frontend_origins" {
  type        = list(string)
  default     = []
  nullable    = false
  description = "Additional trusted HTTPS origins, such as a specific Vercel branch preview. Production is always included."
  validation {
    condition = alltrue([
      for origin in var.additional_frontend_origins :
      can(regex("^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]+)?$", origin))
    ])
    error_message = "Use explicit HTTPS origins without wildcards, credentials, paths, trailing slashes, or query strings."
  }
}
variable "github_repository" {
  type    = string
  default = "braylonwatson/CoordinAIte"
}
variable "github_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Existing GitHub OIDC provider ARN in this AWS account, if one already exists."
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}
variable "db_multi_az" {
  type        = bool
  default     = false
  description = "Enable standby database failover after reviewing the extra monthly cost."
}
variable "db_deletion_protection" {
  type    = bool
  default = true
}
