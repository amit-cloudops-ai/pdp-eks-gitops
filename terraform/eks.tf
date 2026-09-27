module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.34"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    initial = {
      instance_types = ["t3.small"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }
  }

  enable_cluster_creator_admin_permissions = true
}

resource "aws_eks_addon" "pod_identity" {
  cluster_name  = module.eks.cluster_name
  addon_name    = "eks-pod-identity-agent"
}
