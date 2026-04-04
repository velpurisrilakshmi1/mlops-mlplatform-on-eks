# High-Level Design (HLD)

> **Audience**: Solution architects, technical leads, DevOps/Platform engineers  
> **Purpose**: End-to-end architectural view — how components interconnect, AWS service topology, and module organization

---

## 1. C4 Context Diagram — System in Environment

The platform is used by ML practitioners and integrates with GitHub (identity), AWS (infrastructure), and end customers (consuming deployed models).

```mermaid
graph TB
    classDef person fill:#08427b,color:#fff,stroke:#052e56
    classDef platform fill:#1168bd,color:#fff,stroke:#0b4884
    classDef external fill:#999,color:#fff,stroke:#6b6b6b

    DS(["👤 Data Scientist\nExplores data,\ntrains models"]):::person
    DE(["👤 Data Engineer\nBuilds ETL pipelines\nAuthors Airflow DAGs"]):::person
    MLE(["👤 ML Engineer\nDeploys models\nManages endpoints"]):::person
    PADMIN(["👤 Platform Admin\nProvisions infra,\nmanages user access"]):::person

    PLATFORM["🏗️ MLOps Platform on EKS\n\nProvides: workflow orchestration, experiment tracking,\ninteractive notebooks, model serving, observability"]:::platform

    GH_ID["GitHub\nIdentity Provider\nOAuth 2.0"]:::external
    AWS_SVC["AWS Cloud\nEKS, RDS, S3, ALB,\nRoute53, SageMaker, ECR"]:::external
    END_USER["End Users / Applications\nConsume ML model\nREST APIs"]:::external
    CICD["CI/CD System\nGitHub Actions\n(pipelines trigger DAGs)"]:::external

    DS -->|"Prototype in JupyterHub\nTrack with MLflow"| PLATFORM
    DE -->|"Author DAGs\nSchedule pipelines"| PLATFORM
    MLE -->|"Deploy models\nMonitor endpoints"| PLATFORM
    PADMIN -->|"Terraform apply\nManage user-list.yaml"| PLATFORM

    PLATFORM -->|"OAuth flow"| GH_ID
    PLATFORM -->|"Provision &\nrun workloads"| AWS_SVC
    PLATFORM -->|"REST inference\nAPI calls"| END_USER
    CICD -->|"Trigger DAG runs\nvia Airflow API"| PLATFORM
```

---

## 2. C4 Container Diagram — Internal Components

```mermaid
graph TB
    classDef browser fill:#e8f4f8,stroke:#1168bd
    classDef k8s fill:#e8f5e9,stroke:#2e7d32
    classDef aws fill:#fff3e0,stroke:#e65100
    classDef storage fill:#f3e5f5,stroke:#6a1b9a
    classDef iam fill:#fce4ec,stroke:#880e4f

    subgraph K8S_CLUSTER["Amazon EKS Cluster — mlplatform-eks-cluster"]
        subgraph INGRESS_LAYER["Ingress Layer (kube-system)"]
            LBC[AWS Load Balancer\nController v2.4.2]:::k8s
            EDNS[ExternalDNS\nBitnami 6.20.4]:::k8s
        end

        subgraph AIRFLOW_NS["Namespace: airflow"]
            AF_WEB[Airflow Webserver\nseblum/airflow:2.6.3]:::k8s
            AF_SCH[Airflow Scheduler]:::k8s
            AF_EXEC[KubernetesExecutor\nEphemeral task pods]:::k8s
            AF_GIT[git-sync sidecar\n60s interval]:::k8s
        end

        subgraph MLFLOW_NS["Namespace: mlflow"]
            MLF_SRV[MLflow Server\nseblum/mlflow:v2.4.1]:::k8s
        end

        subgraph JHB_NS["Namespace: jupyterhub"]
            JHB_HUB[JupyterHub Hub]:::k8s
            JHB_PROXY[JupyterHub Proxy]:::k8s
            JHB_USER["Single-user servers\n(spawned per login)"]:::k8s
        end

        subgraph MON_NS["Namespace: monitoring"]
            PROM[Prometheus Server\n19.7.2]:::k8s
            GRAF[Grafana\n6.57.4]:::k8s
        end

        subgraph SAGE_NS["Namespace: sagemaker"]
            STREAM[Streamlit App\nv1.0.0]:::k8s
        end

        subgraph DASH_NS["Namespace: dashboard"]
            VUEJS[Vue.js Dashboard\nlatest]:::k8s
        end
    end

    subgraph ALB_LAYER["AWS ALB — mlplatform group"]
        ALB_RT["/airflow → airflow-web\n/mlflow → mlflow-service:5000\n/jupyterhub → hub\n/grafana → grafana\n/sagemaker → streamlit\n/main → dashboard"]:::browser
    end

    subgraph AWS_DATA["AWS Managed Data"]
        PG_RDS["RDS PostgreSQL 13.11\nAirflow metadata DB\ndb.t3.micro port:5000"]:::storage
        MY_RDS["RDS MySQL 8.0.33\nMLflow metadata DB\ndb.t3.micro port:5432"]:::storage
        S3_MLFLOW["S3: mlflow-mlflow\nArtifact storage\nAES256 encrypted"]:::storage
        S3_AF["S3: airflow-data-storage\nPipeline data\nAES256 encrypted"]:::storage
        EFS["AWS EFS\nReadWriteMany\nAirflow logs & JupyterHub"]:::storage
        SM_SEC["AWS Secrets Manager\nPer-user credentials\nOAuth tokens"]:::storage
    end

    subgraph AWS_COMPUTE["AWS Managed Compute"]
        SM_EP["SageMaker Endpoints\nModel serving"]:::aws
        ECR_R["ECR Repository\nmlflow-sagemaker-deployment"]:::aws
    end

    subgraph AWS_NET["AWS Networking"]
        R53["Route 53\nHosted Zone"]:::aws
        ALB_SVC["Application\nLoad Balancer"]:::aws
    end

    subgraph IAM_LAYER["IAM / IRSA"]
        OIDC["EKS OIDC Provider\nFederation"]:::iam
        IRSA_ROLES["IRSA Roles\n(per service account)"]:::iam
    end

    %% Ingress routing
    R53 -->|A record| ALB_SVC
    ALB_SVC --> ALB_RT
    ALB_RT --> AF_WEB & MLF_SRV & JHB_PROXY & GRAF & STREAM & VUEJS

    %% App → Data flows
    AF_WEB & AF_SCH --> PG_RDS
    AF_EXEC --> S3_AF
    AF_EXEC -->|MLFLOW_TRACKING_URI| MLF_SRV
    MLF_SRV --> MY_RDS
    MLF_SRV --> S3_MLFLOW
    JHB_USER --> EFS
    JHB_USER -->|env var MLFLOW_TRACKING_URI| MLF_SRV

    %% SageMaker flow
    AF_EXEC -->|docker push| ECR_R
    AF_EXEC -->|deploy endpoint| SM_EP
    STREAM -->|describe endpoints| SM_EP

    %% Monitoring
    PROM -->|scrape /metrics| AF_WEB & MLF_SRV & JHB_HUB
    GRAF --> PROM

    %% DNS + Ingress mgmt
    LBC -->|manages| ALB_SVC
    EDNS -->|sync| R53

    %% IAM
    OIDC --> IRSA_ROLES
    IRSA_ROLES -->|assume role| AF_EXEC & MLF_SRV & LBC & EDNS

    %% Secrets
    SM_SEC -->|ESO sync| AF_WEB & MLF_SRV
    AF_GIT --> AF_WEB
```

---

## 3. AWS Service Architecture Map

```mermaid
graph LR
    subgraph VPC["VPC — 10.0.0.0/16 (eu-central-1)"]
        subgraph AZ1["AZ: eu-central-1a"]
            PUB1[Public 10.0.4.0/24]
            PRIV1[Private 10.0.1.0/24]
        end
        subgraph AZ2["AZ: eu-central-1b"]
            PUB2[Public 10.0.5.0/24]
            PRIV2[Private 10.0.2.0/24]
        end
        subgraph AZ3["AZ: eu-central-1c"]
            PUB3[Public 10.0.6.0/24]
            PRIV3[Private 10.0.3.0/24]
        end

        NAT["NAT Gateway\n(AZ1 only — cost saving)"]
        ALB_I["Application\nLoad Balancer\n(internet-facing)"]

        EKS_NG1["EKS Workers\nng1 t3.medium × 4-6"]
        EKS_NG0["EKS Workers\nng0 t3.small × 0-5"]
        EKS_NG2["EKS Workers\nng2 t3.large × 0-3\n(NoSchedule taint)"]

        RDS_PG["RDS PostgreSQL\nSubnet Group\n(private subnets)"]
        RDS_MY["RDS MySQL\nSubnet Group"]
        EFS_MT["EFS Mount\nTargets × 3"]
    end

    subgraph GLOBAL["AWS Global / Regional Services"]
        R53["Route 53\nHosted Zone"]
        IAM["IAM + OIDC"]
        SM["Secrets Manager"]
        ECR3["ECR"]
        S3_G["S3 Buckets"]
        SAGE["SageMaker"]
        DDB["DynamoDB\nState locks"]
        TFSTATE["S3 Terraform\nState"]
    end

    PUB1 & PUB2 & PUB3 --> NAT --> INTERNET
    PUB1 & PUB2 & PUB3 --> ALB_I
    ALB_I --> PRIV1 & PRIV2 & PRIV3
    PRIV1 & PRIV2 & PRIV3 --> EKS_NG0 & EKS_NG1 & EKS_NG2
    EKS_NG0 & EKS_NG1 & EKS_NG2 --> RDS_PG & RDS_MY
    PRIV1 --> EFS_MT
    PRIV2 --> EFS_MT
    PRIV3 --> EFS_MT
    EKS_NG0 & EKS_NG1 & EKS_NG2 --> S3_G
    EKS_NG0 & EKS_NG1 & EKS_NG2 --> ECR3
    EKS_NG0 & EKS_NG1 & EKS_NG2 --> SAGE
    EKS_NG0 & EKS_NG1 & EKS_NG2 --> SM
    IAM --> EKS_NG0 & EKS_NG1 & EKS_NG2
    R53 --> ALB_I
    DDB --> TFSTATE

    INTERNET([Internet])
    INTERNET --> R53
```

---

## 4. Terraform Module Dependency Graph

All modules are conditionally deployed from a single root `deployment/main.tf`. Arrows indicate data dependencies (output → input).

```mermaid
graph TD
    BOOT[Bootstrap\nS3 + DynamoDB\nRun first]

    VPC[VPC Module\ninfrast/vpc]
    EKS[EKS Module\ninfrast/eks]
    NET[Networking Module\nALB + ExternalDNS]
    RDS_MOD[RDS Module\nPostgreSQL + MySQL]
    TFB[TFState Backend\nmodules/tfstate-backend]

    USR[User Profiles Module\nmodules/user-profiles]
    MLF_MOD[MLflow Module\nmodules/mlflow]
    AFW_MOD[Airflow Module\nmodules/airflow]
    JHB_MOD[JupyterHub Module\nmodules/jupyterhub]
    MON_MOD[Monitoring Module\nmodules/monitoring]
    SAGE_MOD[SageMaker Module\nmodules/sagemaker]
    DASH_MOD[Dashboard Module\nmodules/dashboard]
    ESO_MOD[External Secrets Module\nmodules/external-secrets]

    BOOT -->|"Enables remote\nS3 backend"| VPC
    VPC -->|"vpc_id\nsubnet_ids\nsg_ids"| EKS
    EKS -->|"cluster_name\nordic_arn\nkubeconfig"| NET
    EKS -->|"cluster_endpoint\nkubeconfig"| RDS_MOD
    EKS -->|"oidc_provider_arn\ncluster_name"| USR
    NET -->|"alb_controller ready"| MLF_MOD
    NET -->|"alb_controller ready"| AFW_MOD
    NET -->|"alb_controller ready"| JHB_MOD
    NET -->|"alb_controller ready"| MON_MOD
    NET -->|"alb_controller ready"| SAGE_MOD
    NET -->|"alb_controller ready"| DASH_MOD
    RDS_MOD -->|"pg_endpoint\npg_password"| AFW_MOD
    RDS_MOD -->|"mysql_endpoint\nmysql_password"| MLF_MOD
    MLF_MOD -->|"mlflow_tracking_uri\ns3_policy_arn"| AFW_MOD
    MLF_MOD -->|"s3_artifact_bucket\ntracking_uri"| JHB_MOD
    SAGE_MOD -->|"ecr_image_tag\nsagemaker_role_arn"| AFW_MOD
    EKS -->|"oidc_arn"| ESO_MOD
    ESO_MOD -->|"cluster_secret_store"| MLF_MOD

    style BOOT fill:#ffccbc
    style VPC fill:#b2dfdb
    style EKS fill:#b2dfdb
    style NET fill:#b2dfdb
    style RDS_MOD fill:#b2dfdb
    style USR fill:#c5cae9
    style MLF_MOD fill:#dcedc8
    style AFW_MOD fill:#dcedc8
    style JHB_MOD fill:#dcedc8
    style MON_MOD fill:#dcedc8
    style SAGE_MOD fill:#dcedc8
    style DASH_MOD fill:#dcedc8
    style ESO_MOD fill:#c5cae9
```

---

## 5. Authentication & Authorization Flow

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant ALB as AWS ALB
    participant App as Platform App\n(Airflow / JupyterHub / Grafana)
    participant GH as GitHub OAuth
    participant IAM as AWS IAM
    participant K8s as Kubernetes RBAC

    User->>Browser: Navigate to https://domain.com/airflow
    Browser->>ALB: HTTPS request
    ALB->>App: Forward to Airflow Webserver pod
    App->>Browser: 302 Redirect to GitHub OAuth
    Browser->>GH: Authorization request\n(scopes: read:org, read:user, user:email)
    GH->>Browser: Show Authorize screen
    User->>GH: Approves access
    GH->>Browser: Return authorization code
    Browser->>App: Callback with code
    App->>GH: Exchange code for access token
    GH->>App: Return token + user info
    App->>GH: GET /orgs/{org}/teams/{team}/members
    GH->>App: Team membership list
    App->>App: Map team → FAB role\n(airflow-admin-team → Admin)
    App->>Browser: Set session cookie; redirect to /airflow

    Note over IAM, K8s: For kubectl / AWS SDK access (Developers)
    User->>IAM: AssumeRole mlplatform-access-{name}
    IAM->>User: Temporary credentials
    User->>K8s: kubectl commands\n(authenticated via aws-auth ConfigMap)
    K8s->>User: API response (system:masters for Developers)
```

---

## 6. Node Group Scaling Architecture

```mermaid
graph TB
    KUBE_CA[Kubernetes Cluster Autoscaler\nkube-system namespace]

    subgraph ASG_NG0["Auto Scaling Group: ng0 (t3.small)"]
        NG0_MIN["Min: 0"]
        NG0_MAX["Max: 5"]
        NG0_DES["Desired: 0"]
        NG0_LABEL["Label: role=t3_small"]
    end

    subgraph ASG_NG1["Auto Scaling Group: ng1 (t3.medium) — BASE LAYER"]
        NG1_MIN["Min: 4"]
        NG1_MAX["Max: 6"]
        NG1_DES["Desired: 4"]
        NG1_LABEL["Label: role=t3_medium"]
    end

    subgraph ASG_NG2["Auto Scaling Group: ng2 (t3.large)"]
        NG2_MIN["Min: 0"]
        NG2_MAX["Max: 3"]
        NG2_DES["Desired: 0"]
        NG2_TAINT["Taint: dedicated=t3_large:NoSchedule"]
        NG2_LABEL["Label: role=t3_large"]
        NG2_USE["Use: Heavy ML workloads\nwith explicit toleration"]
    end

    KUBE_CA -->|"Watch pod Pending state"| ASG_NG0
    KUBE_CA -->|"Scale 4→6 when needed"| ASG_NG1
    KUBE_CA -->|"Scale 0→3 for\nheavy workloads"| ASG_NG2

    subgraph WORKLOADS["Workload Distribution"]
        W1["Platform pods\n(Airflow, MLflow, JupyterHub)\n→ ng1 t3.medium"]
        W2["KubernetesExecutor task pods\n→ ng0 t3.small (spillover)"]
        W3["ML training pods\nwith toleration\n→ ng2 t3.large"]
    end

    ASG_NG1 --> W1
    ASG_NG0 --> W2
    ASG_NG2 --> W3

    style ASG_NG1 fill:#c8e6c9
    style ASG_NG2 fill:#ffccbc
    style KUBE_CA fill:#e1bee7
```

---

## 7. Data Architecture Overview

```mermaid
graph LR
    subgraph SOURCE["Data Sources"]
        GIT_DAGS[Git Repository\nAirflow DAG code]
        JUPYTER_NB[JupyterHub Notebooks\nExperimentation]
        EXT_DATA[External Data Sources\nAPIs, datasets]
    end

    subgraph PROCESSING["Processing Layer"]
        AF_TASK[Airflow Task Pods\nKubernetesExecutor]
        JHB_SERVER[JupyterHub\nSingle-user servers]
    end

    subgraph TRACKING["ML Tracking"]
        MLF_UI[MLflow UI\nExperiment browser]
        MLF_API[MLflow Tracking API\nhttp://mlflow-service.mlflow.svc]
    end

    subgraph STORAGE["Persistent Storage"]
        S3_DATA[S3 — Airflow Data\nmlplatform-{prefix}-airflow-data-storage]
        S3_ART[S3 — Artifacts\nmlplatform-{prefix}-mlflow-mlflow]
        RDS_PG2[RDS PostgreSQL\nDag/task run metadata]
        RDS_MY2[RDS MySQL\nRun params + metrics]
        EFS2[EFS\nLogs + notebooks]
    end

    subgraph SERVING["Model Serving"]
        ECR4[ECR\nDocker image]
        SM3[SageMaker Endpoint\nREST API]
        DASH3[Streamlit\nEndpoint manager]
    end

    GIT_DAGS -->|git-sync 60s| AF_TASK
    EXT_DATA --> AF_TASK
    AF_TASK --> S3_DATA
    AF_TASK --> MLF_API
    AF_TASK -->|docker build + push| ECR4
    AF_TASK -->|deploy endpoint| SM3
    JUPYTER_NB --> JHB_SERVER
    JHB_SERVER --> MLF_API
    JHB_SERVER --> EFS2
    MLF_API --> RDS_MY2
    MLF_API --> S3_ART
    MLF_UI --> RDS_MY2
    AF_TASK --> RDS_PG2
    SM3 --> DASH3
    ECR4 --> SM3

    style SOURCE fill:#e3f2fd
    style PROCESSING fill:#f3e5f5
    style TRACKING fill:#e8f5e9
    style STORAGE fill:#fff3e0
    style SERVING fill:#fce4ec
```

---

## 8. DNS and Ingress Resolution

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant R53 as Route 53
    participant ALB as AWS ALB\n(Internet-facing)
    participant LBC as AWS LBC\n(kube-system)
    participant EDNS as ExternalDNS\n(kube-system)
    participant ING as K8s Ingress Resource
    participant SVC as K8s Service
    participant POD as Application Pod

    Note over LBC, EDNS: During Terraform apply
    LBC->>ALB: Creates ALB + Target Groups
    LBC->>ING: Writes alb.ingress.kubernetes.io/hostname annotation
    EDNS->>ING: Reads hostname annotation
    EDNS->>R53: Creates A record → ALB IP

    Note over Dev, POD: Request path at runtime
    Dev->>R53: DNS query: mlplatform.example.com
    R53->>Dev: Returns ALB IP
    Dev->>ALB: HTTPS GET /airflow
    ALB->>ALB: Evaluate listener rules (group: mlplatform)
    ALB->>SVC: Forward to airflow-web service
    SVC->>POD: Load balance to healthy Airflow Webserver pod
    POD->>Dev: HTTP 200 response
```
