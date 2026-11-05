variable "region" {
  description = "Región de AWS"
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Nombre base de los recursos"
  type        = string
  default     = "caucion-alert"
}

variable "ssm_prefix" {
  description = "Prefijo de los secretos en SSM Parameter Store"
  type        = string
  default     = "/caucion-alert"
}

variable "umbral_tna" {
  description = "% TNA a partir del cual se avisa"
  type        = number
  default     = 60
}

variable "schedule" {
  description = "Expresión cron de EventBridge Scheduler (hora Argentina)"
  type        = string
  default     = "cron(* 11-16 ? * MON-FRI *)"
}

variable "budget_email" {
  description = "Email para la alerta de presupuesto (vacío = no se crea)"
  type        = string
  default     = ""
}
