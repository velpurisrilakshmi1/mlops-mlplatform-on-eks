# Data Flow — Infrastructure Deployment with Terraform

> **Scenario**: A platform engineer deploys the entire MLOps stack from scratch or updates a component using Terraform.  
> **Actors**: Platform Engineer, Terraform CLI, AWS APIs, Helm, Kubernetes

---

## Overview: Full Stack Deployment

```mermaid
flowchart TD
    START([Platform engineer has AWS admin credentials\n+ GitHub OAuth apps created\n+ Route 53 hosted zone ready])

    BOOTSTRAP[Step 0: Bootstrap\ncd deployment/bootstrap\nterraform init + apply\nCreates: S3 state bucket + DynamoDB lock table]
    
    CONFIGURE[Step 1: Configure\nCreate prod.tfvars\nwith all secrets + domain + OAuth settings]
    
    DEPLOY_INFRA[Step 2: Deploy Infrastructure\ncd deployment\nterraform init -backend-config\nterraform apply -var-file=prod.tfvars]
    
    subgraph INFRA_MOD["Infrastructure Layer (parallel in plan)"]
        VPC_D[VPC Module\nCIDR, subnets, NAT, SGs]
        EKS_D[EKS Module\nCluster + node groups\nOIDC + CSI drivers]
    end
    
    subgraph NETWORKING["Networking Layer (after EKS)"]
        ALB_D[AWS LB Controller\nHelm release + IRSA]
        EDNS_D[ExternalDNS\nHelm release + IRSA]
    end
    
    subgraph APPS["Application Layer (after networking, parallel)"]
        AF_D[Airflow\nHelm + RDS + S3 + IAM]
        MLF_D[MLflow\nHelm + RDS + S3 + IAM]
        JHB_D[JupyterHub\nHelm release]
        MON_D[Monitoring\nPrometheus + Grafana Helm]
        SAGE_D[SageMaker\nECR + IAM + Helm]
        DASH_D[Dashboard\nHelm release]
    end
    
    subgraph USERS["User Provisioning"]
        USR_D[User Profiles\nIAM users + roles per YAML]
    end

    START --> BOOTSTRAP --> CONFIGURE --> DEPLOY_INFRA
    DEPLOY_INFRA --> VPC_D --> EKS_D
    EKS_D --> ALB_D & EDNS_D
    ALB_D & EDNS_D --> AF_D & MLF_D & JHB_D & MON_D & SAGE_D & DASH_D
    EKS_D --> USR_D
```

---

## Detailed Deployment Sequence

```mermaid
sequenceDiagram
    actor PE as Platform Engineer
    participant TF as Terraform CLI\n(local machine)
    participant S3_TF as S3 State Bucket\nmlplatform-terraform-state
    participant DDB as DynamoDB\nmlplatform-terraform-locks
    participant AWS_API as AWS APIs\n(IAM, EC2, EKS, RDS, S3...)
    participant K8S_API as Kubernetes API\n(EKS cluster)
    participant HELM as Helm\n(in-cluster)
    participant R53 as Route 53

    Note over PE, DDB: Phase 0 — Bootstrap (run once)
    PE->>TF: cd deployment/bootstrap && terraform init
    TF->>TF: Initialize with local state
    PE->>TF: terraform apply
    TF->>AWS_API: Create S3 bucket: mlplatform-terraform-state\n• versioning: on\n• encryption: AES256\n• public access: blocked
    TF->>AWS_API: Create DynamoDB table: mlplatform-terraform-locks\n• hash_key: LockID\n• billing: PAY_PER_REQUEST
    TF->>PE: Bootstrap outputs: bucket name, table name

    Note over PE, R53: Phase 1 — VPC + EKS
    PE->>TF: terraform init -reconfigure\n(point to S3 backend)
    TF->>S3_TF: Check/create state file
    PE->>TF: terraform apply -var-file=prod.tfvars\n-target=module.vpc
    TF->>DDB: Acquire state lock (LockID=deployment.tfstate)
    TF->>AWS_API: Create VPC 10.0.0.0/16\n+ public subnets (10.0.4-6.0/24)\n+ private subnets (10.0.1-3.0/24)\n+ Internet Gateway\n+ NAT Gateway (AZ1)\n+ route tables\n+ security groups ×5
    TF->>S3_TF: Write state
    TF->>DDB: Release lock

    PE->>TF: terraform apply -target=module.eks
    TF->>DDB: Acquire lock
    TF->>AWS_API: Create EKS cluster (v1.24)\n+ node group ng0 (t3.small, 0-5)\n+ node group ng1 (t3.medium, 4-6)\n+ node group ng2 (t3.large, 0-3, tainted)\n+ OIDC provider\n+ Add-on: vpc-cni\n+ Add-on: ebs-csi-driver
    TF->>K8S_API: Wait for cluster active
    TF->>HELM: helm install aws-efs-csi-driver
    TF->>K8S_API: Patch gp2 StorageClass (remove default annotation)
    TF->>K8S_API: Create efs-sc StorageClass (set as default)
    TF->>S3_TF: Write state
    TF->>DDB: Release lock

    Note over PE, HELM: Phase 2 — Networking
    PE->>TF: terraform apply -target=module.networking
    TF->>DDB: Acquire lock
    TF->>AWS_API: Create IAM role: aws-load-balancer-controller-role\n(IRSA — OIDC trust policy)
    TF->>HELM: helm install aws-load-balancer-controller\n(kube-system, v2.4.2)
    TF->>AWS_API: Create IAM role: external-dns-role\n(IRSA — Route53 permissions)
    TF->>HELM: helm install external-dns\n(kube-system, bitnami 6.20.4)
    TF->>S3_TF: Write state
    TF->>DDB: Release lock

    Note over PE, R53: Phase 3 — Application Modules (parallel Terraform)
    PE->>TF: terraform apply [all remaining modules]

    par MLflow deployment
        TF->>AWS_API: Create RDS MySQL 8.0.33 (db.t3.micro)
        TF->>AWS_API: Create S3 bucket: mlplatform-{prefix}-mlflow-mlflow
        TF->>AWS_API: Create IAM role: mlflow-s3-access-role (IRSA)
        TF->>HELM: helm install mlflow (custom chart v2.4.1)
    and Airflow deployment
        TF->>AWS_API: Create RDS PostgreSQL 13.11 (db.t3.micro)
        TF->>AWS_API: Create S3 bucket: mlplatform-{prefix}-airflow-data-storage
        TF->>AWS_API: Create IAM role: airflow-iam-role (IRSA)
        TF->>K8S_API: kubectl create secret (git credentials, OAuth, DB password, AWS info)
        TF->>HELM: helm install airflow (community 8.7.1)
    and JupyterHub deployment
        TF->>HELM: helm install jupyterhub (official 2.0.0)
    and Monitoring deployment
        TF->>HELM: helm install prometheus-operator-crds
        TF->>HELM: helm install kube-prometheus-stack
        TF->>HELM: helm install grafana (6.57.4)
    and SageMaker deployment
        TF->>AWS_API: Create ECR repo: mlflow-sagemaker-deployment
        TF->>AWS_API: Create IAM role: sagemaker-access-role (IRSA)
        TF->>AWS_API: Create IAM user: dashboard-read-user (static)
        TF->>TF: null_resource local-exec: docker build + push\n(SageMaker base image)
        TF->>HELM: helm install streamlit-sagemaker app
    end
    
    TF->>K8S_API: Wait for all Ingress resources to have ALB address
    K8S_API->>HELM: Ingress created → LBC provisions ALB
    HELM->>R53: ExternalDNS detects hostname annotation → creates A record
    TF->>S3_TF: Write final state
    TF->>DDB: Release lock
    TF->>PE: terraform apply complete\nOutput: cluster_name, ALB URL
```

---

## Makefile Targets

```mermaid
graph TB
    subgraph MAKE["Makefile — deployment/Makefile"]
        ALL[deploy-all\nFull stack deployment]
        DESTROY_ALL[destroy-all\nComplete teardown]
        
        VPC_T[create-vpc]
        EKS_T[create-eks-cluster]
        NET_T[deploy-networking]
        AF_T[deploy-airflow]
        MLF_T[deploy-mlflow]
        JHB_T[deploy-jupyterhub]
        MON_T[deploy-monitoring]
        SAGE_T[deploy-sagemaker]
        DASH_T[deploy-dashboard]
        USR_T[deploy-user-profiles]
    end

    ALL --> VPC_T --> EKS_T --> NET_T
    NET_T --> AF_T & MLF_T & JHB_T & MON_T & SAGE_T & DASH_T --> USR_T

    DESTROY_ALL --> D_AF[destroy-airflow] & D_MLF[destroy-mlflow] & D_JHB[destroy-jupyterhub]
    D_AF & D_MLF & D_JHB --> D_EKS[destroy-eks]
    D_EKS --> D_VPC[destroy-vpc]
```

**Usage**:
```bash
# Full deployment
make deploy-all VARS_FILE=prod.tfvars

# Deploy single module
make deploy-mlflow VARS_FILE=prod.tfvars

# Destroy everything
make destroy-all VARS_FILE=prod.tfvars
```

---

## Terraform Backend Configuration

```hcl
# deployment/providers.tf (or backend.tf per sub-stack)
terraform {
  backend "s3" {
    bucket         = "mlplatform-terraform-state"
    key            = "deployment.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "mlplatform-terraform-locks"
    encrypt        = true
  }
  required_version = ">= 1.5.3"
}
```

---

## Required `prod.tfvars` Values

```hcl
# Network & Identity
domain_name = "ml.example.com"
AWS_REGION  = "eu-central-1"

# Git Source
git_username             = "github-user"
git_token                = "ghp_xxxx"    # GitHub PAT
git_sync_repository_url  = "https://github.com/org/ml-dags.git"
git_sync_branch          = "main"

# GitHub OAuth Apps (one per component)
airflow_git_client_id     = "..."
airflow_git_client_secret = "..."
jupyterhub_git_client_id  = "..."
jupyterhub_git_client_secret = "..."
jupyterhub_proxy_secret_token = "random-hex-64-chars"
grafana_git_client_id     = "..."
grafana_git_client_secret = "..."

# Airflow Security
airflow_fernet_key = "base64-encoded-32-byte-key"

# Feature Flags
deploy_airflow    = true
deploy_mlflow     = true
deploy_jupyterhub = true
deploy_monitoring = true
deploy_dashboard  = true
deploy_sagemaker  = true
```

---

## Deployment Timing

| Module | Approx. Time | Notes |
|--------|-------------|-------|
| Bootstrap | 1–2 min | S3 + DynamoDB only |
| VPC | 3–5 min | NAT gateway slow to provision |
| EKS cluster + nodes | 12–18 min | Longest step; node group creation |
| Networking (ALB + DNS) | 3–5 min | Including Helm release + IRSA |
| MLflow + RDS MySQL | 8–12 min | RDS creation dominates |
| Airflow + RDS PostgreSQL | 8–12 min | RDS creation dominates |
| JupyterHub | 2–3 min | Helm only |
| Monitoring | 3–5 min | 2 Helm releases (CRDs + stack) |
| SageMaker | 5–8 min | ECR + docker push + Helm |
| **Total (parallel)** | **~30–40 min** | |

---

## AWS Services Involved

| Service | Role |
|---------|------|
| **S3** | Terraform remote state storage |
| **DynamoDB** | Terraform state locking |
| **VPC, Subnets, NAT** | Network layer |
| **EKS** | Kubernetes control plane + nodes |
| **RDS** | PostgreSQL + MySQL (for Airflow/MLflow) |
| **ECR** | Container image registry |
| **IAM** | IRSA roles, user/developer policies, user accounts |
| **Route 53** | DNS record creation via ExternalDNS |
| **EFS** | StorageClass creation + mount targets |
| **EBS** | CSI driver add-on |
| **ALB** | Provisioned by LBC after Helm install |
| **Secrets Manager** | Per-user credential storage |
| **SageMaker** | Endpoint infrastructure (post-deploy) |
