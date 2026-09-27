
output "karpenter_iam_role_arn" {
  value = module.karpenter.iam_role_arn
}

output "karpenter_queue_name" {
  value = module.karpenter.queue_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "karpenter_node_iam_role_name" {
  value = module.karpenter.node_iam_role_name
}
