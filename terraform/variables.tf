variable "cluster_name" {
  description = "Name of the EKS cluster, used for subnet tagging"
  type        = string
  default     = "pdp-eks-cluster"
}
