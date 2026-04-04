# System Overview

> **Audience**: Engineering managers, architects, new team members  
> **Purpose**: Understand what the platform is, why it exists, and what it contains

---

## Executive Summary

The **MLOps Platform on EKS** is a fully managed, Infrastructure-as-Code ML platform that provides a complete, end-to-end machine learning lifecycle environment on Amazon Web Services.

It eliminates the need for data scientists to manage any infrastructure. A data scientist can:

1. **Explore data and prototype models** in JupyterHub (with shared EFS storage and pre-installed ML libraries).
2. **Schedule and orchestrate ML pipelines** with Airflow (git-sync DAGs, KubernetesExecutor for isolation).
3. **Track experiments, log parameters/metrics, and register models** with MLflow.
4. **Deploy trained models as REST endpoints** via SageMaker, monitored via a Streamlit dashboard.
5. **Observe the entire platform health** through Prometheus + Grafana.

All access is controlled via **GitHub OAuth** and **AWS IAM**, creating a secure, auditable environment suitable for multiple teams.

---

## Platform Goals

| Goal | How Addressed |
|------|--------------|
| **Reproducibility** | MLflow experiment tracking + artifact versioning in S3 |
| **Scalability** | EKS Cluster Autoscaler + KubernetesExecutor ephemeral pods |
| **Security** | IRSA (no node-level credentials), GitHub OAuth, private subnets |
| **Multi-tenancy** | Per-namespace isolation, per-user IAM roles, GitHub team-based access |
| **Observability** | Prometheus + Grafana, K8s dashboard IDs: 2, 315, 6417 |
| **Infrastructure Independence** | All IaC in Terraform; reproducible from scratch in ~20 min |
| **Cost Efficiency** | Autoscaling node groups (min=0), spot-friendly (large workloads on tainted ng2) |

---

## Component Catalogue

```mermaid
graph TB
    subgraph USER["👤 Users"]
        DS[Data Scientists]
        DE[Data Engineers]
        MLO[ML Engineers]
        DevU[Platform Admins]
    end

    subgraph ACCESS["🔐 Access Layer"]
        GHO[GitHub OAuth]
        ALB[AWS ALB\nPath-Based Routing]
        R53[Route 53\nDNS]
    end

    subgraph PLATFORM["⚙️ ML Platform — Amazon EKS 1.24"]
        AFW[Airflow 2.6.3\nWorkflow Orchestration\nns: airflow]
        MLF[MLflow 2.4.1\nExperiment Tracking\nns: mlflow]
        JHB[JupyterHub 2.0.0\nInteractive Notebooks\nns: jupyterhub]
        SMK[SageMaker Dashboard\nStreamlit v1.0\nns: sagemaker]
        DASH[Platform Dashboard\nVue.js\nns: dashboard]
        PROM[Prometheus 19.7.2\nMetrics Collection\nns: monitoring]
        GRAF[Grafana 6.57.4\nVisualization\nns: monitoring]
    end

    subgraph COMPUTE["🖥️ AWS Compute"]
        NG0[Node Group ng0\nt3.small × 0-5]
        NG1[Node Group ng1\nt3.medium × 4-6]
        NG2[Node Group ng2\nt3.large × 0-3\nNoSchedule taint]
        SM_EP[SageMaker\nManaged Endpoints]
        ECR[ECR\nContainer Registry]
    end

    subgraph DATA["💾 Data Layer"]
        PG[RDS PostgreSQL 13.11\nAirflow metadata]
        MY[RDS MySQL 8.0.33\nMLflow metadata]
        S3A[S3 Bucket\nAirflow data]
        S3M[S3 Bucket\nMLflow artifacts]
        EFS[EFS\nShared persistent storage]
    end

    subgraph OPS["🔧 Platform Ops"]
        TF[Terraform\nIaC — all resources]
        SM_S[AWS Secrets Manager\nCredentials]
        ESO[External Secrets Op\nK8s sync]
        IRSA[OIDC / IRSA\nPod IAM]
    end

    DS & DE & MLO & DevU --> GHO
    GHO --> ALB
    R53 --> ALB
    ALB -->|/airflow| AFW
    ALB -->|/mlflow| MLF
    ALB -->|/jupyterhub| JHB
    ALB -->|/sagemaker| SMK
    ALB -->|/main| DASH
    ALB -->|/grafana| GRAF

    AFW --> PG
    AFW --> S3A
    AFW -->|MLFLOW_TRACKING_URI| MLF
    MLF --> MY
    MLF --> S3M
    JHB --> EFS
    JHB -->|env var| MLF
    AFW -->|deploy model| SM_EP
    SM_EP --> ECR
    SMK -->|read endpoints| SM_EP
    PROM -->|scrape| AFW & MLF & JHB & NG0 & NG1 & NG2
    GRAF --> PROM

    TF --> PLATFORM
    TF --> COMPUTE
    TF --> DATA
    SM_S --> ESO --> PLATFORM
    IRSA --> PLATFORM

    style USER fill:#e8f4f8
    style ACCESS fill:#fff3e0
    style PLATFORM fill:#e8f5e9
    style COMPUTE fill:#fce4ec
    style DATA fill:#f3e5f5
    style OPS fill:#e0f2f1
```

---

## AWS Service Map

| AWS Service | Role | Key Configuration |
|-------------|------|-------------------|
| **EKS** | Kubernetes control plane | v1.24, public + private endpoint, OIDC enabled |
| **EC2 Auto Scaling** | Worker nodes | 3 node groups: t3.small/medium/large |
| **VPC** | Network isolation | `10.0.0.0/16`, 3 AZs, single NAT gateway |
| **ALB** | Ingress traffic | Internet-facing, IP target type, path-based rules |
| **Route 53** | DNS | ExternalDNS syncs Ingress → A records automatically |
| **RDS (PostgreSQL)** | Airflow DB | v13.11, `db.t3.micro`, port 5000, private subnets |
| **RDS (MySQL)** | MLflow DB | v8.0.33, `db.t3.micro`, port 5432, private subnets |
| **EFS** | Shared file storage | Dynamic provisioning, `efs-ap` mode, IAM auth |
| **EBS** | Block storage | `gp2` available (not default), used by stateful workloads |
| **S3** | Artifact & data storage | 2 buckets (MLflow artifacts, Airflow data), AES256 encryption |
| **S3** | Terraform remote state | `mlplatform-terraform-state`, versioned, encrypted |
| **DynamoDB** | Terraform state locking | `mlplatform-terraform-locks`, prevents concurrent applies |
| **IAM + OIDC** | IRSA (pod-level AWS access) | One role per K8s service account |
| **Secrets Manager** | Credential storage | Per-user AWS keys + OAuth tokens |
| **ECR** | Container registry | `mlflow-sagemaker-deployment` for model images |
| **SageMaker** | Model serving | Endpoint management; deployment triggered from Airflow |

---

## Infrastructure Technical Stack

```mermaid
graph LR
    subgraph IaC["Infrastructure as Code"]
        TF[Terraform ≥ 1.5.3]
        TF -->|provider| AWSP[AWS 5.11.0]
        TF -->|provider| K8SP[Kubernetes 2.22.0]
        TF -->|provider| HELMP[Helm 2.10.1]
        TF -->|provider| RANDP[Random 3.5.1]
        TF -->|provider| TLSP[TLS 4.0.4]
        TF -->|provider| NULLP[Null 3.2.1]
    end

    subgraph CONTAINER["Container / Delivery"]
        HELM[Helm 3.x]
        DOCKER[Docker]
        K8S[Kubernetes 1.24]
    end

    subgraph LANGUAGE["Application Layer"]
        PY[Python 3.11]
        VUE[Vue.js]
        STREAM[Streamlit]
    end

    subgraph OBSERV["Observability Stack"]
        PROM2[Prometheus]
        GRAF2[Grafana]
        KUBE_STATE[kube-state-metrics]
    end

    TF --> HELM --> K8S
    TF --> DOCKER --> ECR2[ECR]
    K8S --> PY & VUE & STREAM
    K8S --> PROM2 --> GRAF2
    K8S --> KUBE_STATE --> PROM2

    style IaC fill:#e8f4f8
    style CONTAINER fill:#e8f5e9
    style LANGUAGE fill:#fff3e0
    style OBSERV fill:#fce4ec
```

---

## Deployment Feature Flags

Every platform component can be independently enabled or disabled via a boolean variable in the `.tfvars` file.

| Variable | Default | Component Deployed |
|----------|---------|-------------------|
| `deploy_airflow` | `true` | Airflow + RDS PostgreSQL + S3 data bucket |
| `deploy_mlflow` | `true` | MLflow + RDS MySQL + S3 artifact bucket |
| `deploy_jupyterhub` | `true` | JupyterHub |
| `deploy_monitoring` | `true` | Prometheus + Grafana |
| `deploy_dashboard` | `true` | Vue.js unified dashboard |
| `deploy_sagemaker` | `true` | SageMaker IAM + ECR + Streamlit dashboard |

> Cloud cost tip: Set all `deploy_*` to `false` until needed. EKS control plane (base cost) + 4× t3.medium nodes run continuously regardless of flags.

---

## User Roles

```mermaid
graph TD
    GH_ORG[GitHub Organization\nmlplatform-seblum-me]
    
    GH_ORG --> ADMIN_TEAM[Team: airflow-admin-team]
    GH_ORG --> USER_TEAM[Team: airflow-users-team]
    GH_ORG --> GRAFANA_TEAM[Team: grafana-user-team]

    ADMIN_TEAM -->|Airflow role| AF_ADMIN[Airflow Admin\nFull DAG control]
    ADMIN_TEAM -->|IAM role| DEV_IAM[Developer IAM Policy\nEKS + EC2 + S3 + RDS + VPC]
    ADMIN_TEAM -->|K8s group| SYS_MASTERS[system:masters\nFull cluster access]

    USER_TEAM -->|Airflow role| AF_USER[Airflow User\nDAG run only]
    USER_TEAM -->|IAM role| USER_IAM[User IAM Policy\nSageMaker read-only]

    GRAFANA_TEAM -->|Grafana role| GRAF_VIEWER[Grafana Viewer\nDashboards read-only]

    style ADMIN_TEAM fill:#ffcdd2
    style USER_TEAM fill:#c8e6c9
    style GRAFANA_TEAM fill:#e1bee7
```

---

## Network Topology Summary

```mermaid
graph TB
    INTERNET([Internet])
    
    subgraph AWS_REGION["AWS Region — eu-central-1"]
        subgraph VPC["VPC 10.0.0.0/16"]
            subgraph PUB["Public Subnets (10.0.4-6.0/24)"]
                NAT[NAT Gateway\nSingle AZ]
                ALB2[Application\nLoad Balancer]
            end
            
            subgraph PRIV["Private Subnets (10.0.1-3.0/24)"]
                subgraph EKS_NG["EKS Worker Nodes"]
                    NG0[ng0 t3.small]
                    NG1[ng1 t3.medium]
                    NG2[ng2 t3.large]
                end
                
                subgraph DBS["Databases"]
                    PG2[RDS PostgreSQL]
                    MY2[RDS MySQL]
                end
                
                EFS2[EFS Mount Targets\n× 3 AZs]
            end
        end
        
        subgraph MANAGED["AWS Managed Services"]
            S32[S3 Buckets]
            SM2[SageMaker]
            ECR3[ECR]
            R532[Route 53]
            SMGR[Secrets Manager]
        end
    end

    INTERNET --> R532 --> ALB2
    INTERNET --> SMGR
    ALB2 --> EKS_NG
    EKS_NG --> NAT --> INTERNET
    EKS_NG <--> DBS
    EKS_NG <--> EFS2
    EKS_NG --> S32
    EKS_NG --> SM2
    EKS_NG --> ECR3
    EKS_NG --> SMGR

    style PUB fill:#fff9c4
    style PRIV fill:#c8e6c9
    style MANAGED fill:#e3f2fd
```
