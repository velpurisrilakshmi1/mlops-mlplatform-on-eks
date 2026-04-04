# Low-Level Design (LLD)

> **Audience**: Platform engineers, SREs, backend developers  
> **Purpose**: Detailed component internals — K8s resource specs, DB schemas, IAM role trust policies, Helm configurations, and storage classes

---

## 1. Kubernetes Resources Per Namespace

### 1.1 kube-system — Platform Infrastructure

```mermaid
graph TB
    subgraph KS["Namespace: kube-system"]
        subgraph LBC_COMP["AWS Load Balancer Controller"]
            LBC_DEPLOY["Deployment\naws-load-balancer-controller\nReplicas: 2"]
            LBC_SA["ServiceAccount\naws-load-balancer-controller\nAnnotation: eks.amazonaws.com/role-arn"]
            LBC_CRD["CRDs\nIngressClassParams\nTargetGroupBindings"]
        end
        subgraph EDNS_COMP["ExternalDNS"]
            EDNS_DEPLOY["Deployment\nexternal-dns\nBitnami 6.20.4"]
            EDNS_SA["ServiceAccount\nexternal-dns\nAnnotation: eks.amazonaws.com/role-arn"]
        end
        subgraph EFS_CSI["EFS CSI Driver"]
            EFS_CTRL["DaemonSet/Deployment\nefs-csi-controller"]
            EFS_SC["StorageClass\nefs-sc (default)\nprovisioner: efs.csi.aws.com"]
            EFS_SC2["StorageClass\nefs-sc-custom\nprovisioner: efs.csi.aws.com"]
        end
        subgraph EBS_CSI["EBS CSI Driver (addon)"]
            EBS_CTRL["Deployment\nebs-csi-controller"]
            EBS_SC["StorageClass\ngp2 (NOT default)\nannotation removed by patch"]
        end
        subgraph CA["Cluster Autoscaler"]
            CA_DEPLOY["Deployment\ncluster-autoscaler\nIn autoscaler/ submodule"]
        end
    end
```

### 1.2 Airflow Namespace — Detailed K8s Resources

```mermaid
graph TB
    subgraph AF_NS["Namespace: airflow"]
        direction TB
        subgraph WORKLOADS_AF["Workloads"]
            AF_WEB_D["Deployment: airflow-web\nImage: seblum/airflow:2.6.3-python3.11-custom-light\nContainers: webserver + git-sync sidecar\nPort: 8080\nProbes: /health endpoint"]
            AF_SCH_D["Deployment: airflow-scheduler\nImage: seblum/airflow:2.6.3-python3.11-custom-light\nSidecar: git-sync (60s interval)\nMounts: EFS /opt/airflow/logs"]
            AF_EXEC_P["Pod (ephemeral): task-{dag}-{run}-{task}\nCreated by KubernetesExecutor\nDeleted after task completion\nInherits airflow SA IRSA role"]
        end
        subgraph SERVICES_AF["Services"]
            AF_SVC["Service: airflow-web\nType: ClusterIP\nPort: 8080 (web)"]
        end
        subgraph INGRESS_AF["Ingress"]
            AF_ING["Ingress: airflow\nalb.ingress.kubernetes.io/group.name: mlplatform\nalb.ingress.kubernetes.io/scheme: internet-facing\nalb.ingress.kubernetes.io/target-type: ip\nPath: /airflow → airflow-web:web"]
        end
        subgraph CONFIG_AF["ConfigMaps & Secrets"]
            AF_CM_WS["ConfigMap: airflow-webserver-config\nContains: WebServerConfig.py\nGitHub team → FAB role mapping"]
            AF_SEC_DB["Secret: {prefix}-db-auth\npostgresql-password: RDS password"]
            AF_SEC_GIT["Secret: {prefix}-https-git-secret\nusername: git_username\npassword: git_token"]
            AF_SEC_GH["Secret: {prefix}-organization-git-secret\nGITHUB_CLIENT_ID: OAuth App ID\nGITHUB_CLIENT_SECRET: OAuth secret"]
            AF_SEC_AWS["Secret: {ns}-aws-account-information\nAWS_REGION, AWS_ID"]
            AF_SEC_SAGE["Secret: {ns}-sagemaker-access\nAWS_ROLE_NAME_SAGEMAKER"]
        end
        subgraph STORAGE_AF["Storage"]
            AF_PVC["PVC: airflow-logs\nStorageClass: efs-sc\nAccessMode: ReadWriteMany\nSize: 5Gi"]
        end
        subgraph SA_AF["Service Accounts"]
            AF_SA["ServiceAccount: airflow\nAnnotation: role-arn → arn:aws:iam::{acct}:role/airflow-sa-role\nPermissions: S3 data bucket + MLflow policy"]
        end
    end
```

### 1.3 MLflow Namespace

```mermaid
graph TB
    subgraph MLF_NS["Namespace: mlflow"]
        subgraph WORKLOADS_MLF["Workloads"]
            MLF_DEP["Deployment: mlflow\nImage: seblum/mlflow:v2.4.1\nCommand: mlflow server\n--backend-store-uri mysql://{user}:{pw}@{host}:5432/mlflow_db\n--default-artifact-root s3://{bucket}\n--host 0.0.0.0\n--port 5000"]
        end
        subgraph SERVICES_MLF["Services"]
            MLF_SVC["Service: mlflow-service\nType: ClusterIP\nPort: 5000\nUsed by: Airflow + JupyterHub via internal DNS\nDNS: mlflow-service.mlflow.svc.cluster.local"]
        end
        subgraph INGRESS_MLF["Ingress"]
            MLF_ING["Ingress: mlflow\nalb.ingress.kubernetes.io/group.name: mlplatform\nPath: /mlflow → mlflow-service:5000"]
        end
        subgraph SECRETS_MLF["Secrets"]
            MLF_SEC["Secret: mlflow-{suffix}\n[If ESO enabled]\nSynced from AWS Secrets Manager\nContains: DB password, S3 bucket name"]
        end
        subgraph CM_MLF["ConfigMaps"]
            MLF_CM["ConfigMap: mlflow-config\nDB_URI: mysql+pymysql://...\nARTIFACT_ROOT: s3://..."]
        end
        subgraph SA_MLF["Service Accounts"]
            MLF_SA["ServiceAccount: mlflow\nAnnotation: role-arn → arn:aws:iam::{acct}:role/mlflow-s3-access-role\nPermissions: s3:GetObject, s3:PutObject on artifact bucket"]
        end
    end
```

### 1.4 JupyterHub Namespace

```mermaid
graph TB
    subgraph JHB_NS["Namespace: jupyterhub"]
        subgraph WORKLOADS_JHB["Workloads"]
            JHB_HUB_D["Deployment: hub\nImage: jupyterhub/k8s-hub:2.0.0\nEnv: GITHUB OAuth config\nMounts: hub-db-dir (SQLite)"]
            JHB_PROXY_D["Deployment: proxy\nImage: jupyterhub/configurable-http-proxy"]
            JHB_USER_D["Pod (per-user): jupyter-{username}\nImage: seblum/jupyterhub-server:latest\nSpawned by Hub on login\nCulling: enabled (remove inactive)"]
        end
        subgraph SERVICES_JHB["Services"]
            JHB_HUB_SVC["Service: hub\nType: ClusterIP\nPort: 8081"]
            JHB_PROXY_SVC["Service: proxy-public\nType: ClusterIP\nPort: 80"]
        end
        subgraph INGRESS_JHB["Ingress"]
            JHB_ING["Ingress: jupyterhub\nalb.ingress.kubernetes.io/group.name: mlplatform\nPath: /jupyterhub → hub"]
        end
        subgraph ENV_JHB["Key Environment Variables (per user pod)"]
            JHB_ENV["MLFLOW_TRACKING_URI: http://mlflow-service.mlflow.svc.cluster.local\nGIT_REPO_URL: {git_repository_url}"]
        end
        subgraph LIFECYCLE_JHB["Pod Lifecycle Hooks"]
            JHB_POST["postStart hook:\ngit clone {git_repository_url} /home/jovyan/work"]
        end
    end
```

### 1.5 Monitoring Namespace

```mermaid
graph TB
    subgraph MON_NS["Namespace: monitoring"]
        subgraph PROM_COMP["Prometheus (chart 19.7.2)"]
            PROM_D["Deployment: prometheus-server\n2Gi persistent volume\nRetention: 15d (default)"]
            PROM_CM["ConfigMap: prometheus-server\nScrape configs: pods, services, nodes"]
            PROM_SVC2["Service: prometheus-server\nClusterIP port 80"]
            PROM_CRD["CRDs (chart 5.1.0)\nServiceMonitor\nPodMonitor\nPrometheusRule"]
        end
        subgraph GRAF_COMP["Grafana (chart 6.57.4)"]
            GRAF_D["Deployment: grafana\nPersistent: 1Gi EBS"]
            GRAF_DS["DataSource: Prometheus\nURL: http://prometheus-server.monitoring.svc.cluster.local"]
            GRAF_DB["Dashboards (via grafana.com IDs):\n• ID 2: Prometheus stats\n• ID 315: Kubernetes cluster\n• ID 6417: K8s cluster detail"]
            GRAF_AUTH["Auth: GitHub OAuth\nScopes: user:email, read:org\nTeam: grafana-user-team"]
            GRAF_ING["Ingress: grafana\nPath: /grafana OR /monitoring\n→ grafana:80"]
        end
    end
```

### 1.6 SageMaker & Dashboard Namespaces

| Resource | SageMaker NS | Dashboard NS |
|----------|-------------|-------------|
| Deployment | `streamlit-sagemaker-app` `seblum/streamlit-sagemaker-app:v1.0.0` | `dashboard` `seblum/vuejs-ml-dashboard:latest` |
| Service | `streamlit-sagemaker-service` ClusterIP:8501 | `dashboard-service` ClusterIP:80 |
| Ingress | `/sagemaker` → streamlit | `/main` → dashboard |
| Env vars | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (from IAM user) | Component URLs |

---

## 2. RDS Database Schemas

### 2.1 Airflow — PostgreSQL 13.11

```mermaid
erDiagram
    dag {
        string dag_id PK
        boolean is_paused
        boolean is_subdag
        boolean is_active
        timestamp last_pickled
        timestamp last_expired
        timestamp last_scheduler_run
        int max_active_runs
        int max_active_tasks
    }
    dag_run {
        int id PK
        string dag_id FK
        timestamp execution_date
        string run_id
        string state
        string run_type
        timestamp start_date
        timestamp end_date
    }
    task_instance {
        string task_id PK
        string dag_id FK
        string run_id FK
        string state
        timestamp start_date
        timestamp end_date
        int try_number
        string operator
        string pool
        text log
    }
    job {
        int id PK
        string dag_id
        string state
        string job_type
        timestamp start_date
        timestamp end_date
        timestamp latest_heartbeat
        string hostname
        int unixname
    }
    serialized_dag {
        string dag_id PK
        timestamp last_updated
        text fileloc
        text data
    }
    variable {
        int id PK
        string key
        text val
        boolean is_encrypted
    }
    connection {
        int id PK
        string conn_id
        string conn_type
        string host
        string schema
        string login
        string password
    }

    dag ||--o{ dag_run : "has"
    dag_run ||--o{ task_instance : "contains"
    dag ||--o{ task_instance : "runs"
```

**Connection Details**:
- DB Name: `airflow_db`
- Engine: PostgreSQL 13.11
- Host: `{rds_endpoint}:5000`
- Admin User: `airflow_admin`
- Character Encoding: UTF-8
- Backup: `skip_final_snapshot = true`
- Storage: 20 GB gp2 (auto-scale to 500 GB)

### 2.2 MLflow — MySQL 8.0.33

```mermaid
erDiagram
    experiments {
        int experiment_id PK
        string name
        string artifact_location
        string lifecycle_stage
        timestamp creation_time
        timestamp last_update_time
    }
    runs {
        string run_uuid PK
        string name
        string source_type
        string source_name
        string entry_point_name
        int experiment_id FK
        string user_id
        string status
        bigint start_time
        bigint end_time
        string source_version
        string lifecycle_stage
        string artifact_uri
    }
    params {
        string key PK
        string run_uuid FK
        string value
    }
    metrics {
        string key PK
        string run_uuid FK
        float value
        bigint timestamp
        int step
        boolean is_nan
    }
    tags {
        string key PK
        string run_uuid FK
        string value
    }
    model_version {
        string name PK
        int version PK
        string creation_time
        string last_updated_time
        string description
        string source
        string run_id FK
        string status
        string current_stage
    }
    registered_models {
        string name PK
        timestamp creation_time
        timestamp last_updated_time
        string description
    }

    experiments ||--o{ runs : "contains"
    runs ||--o{ params : "has"
    runs ||--o{ metrics : "logs"
    runs ||--o{ tags : "tagged with"
    registered_models ||--o{ model_version : "versions"
    runs ||--o{ model_version : "source"
```

**Connection Details**:
- DB Name: `mlflow_db`
- Engine: MySQL 8.0.33
- Host: `{rds_endpoint}:5432`
- Admin User: `mlflow_admin`
- Password: No special characters (MySQL 8 compat)
- Connection URI: `mysql+pymysql://mlflow_admin:{pw}@{host}:5432/mlflow_db`
- Storage: 20 GB gp2 (auto-scale to 500 GB)

---

## 3. S3 Bucket Policies & IRSA Role Map

### 3.1 MLflow Artifact Bucket

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
        "s3:GetObjectVersion", "s3:ListBucketVersions"
      ],
      "Resource": "arn:aws:s3:::mlplatform-{random12}-mlflow-mlflow/*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::mlplatform-{random12}-mlflow-mlflow"
    }
  ]
}
```

**Trust policy (IRSA)** for `mlflow-s3-access-role`:
```json
{
  "Principal": {
    "Federated": "arn:aws:iam::{ACCOUNT}:oidc-provider/oidc.eks.eu-central-1.amazonaws.com/id/{HASH}"
  },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "oidc.eks.eu-central-1.amazonaws.com/id/{HASH}:sub":
        "system:serviceaccount:mlflow:mlflow"
    }
  }
}
```

### 3.2 Airflow Data Bucket

- **Authentication**: Stored as K8s Secret (access key + secret key), NOT IRSA
- **Secret name**: `{namespace}-{s3_data_bucket_secret_name}`
- **Access keys**: Rotatable via re-running Terraform `user-profiles` module

### 3.3 Complete IRSA Role Map

```mermaid
graph TB
    OIDC["EKS OIDC Provider\noidc.eks.eu-central-1.amazonaws.com/id/{HASH}"]

    subgraph IRSA_ROLES["IRSA Roles → Service Accounts"]
        R_MLF["Role: mlflow-s3-access-role\nSA: mlflow/mlflow\nPolicies: S3 artifact bucket full access"]
        R_AF["Role: airflow-iam-role\nSA: airflow/airflow\nPolicies: S3 data bucket + MLflow S3 policy"]
        R_EFS["Role: efs-csi-role\nSA: kube-system/efs-csi-controller-sa\nPolicies: AmazonElasticFileSystemClientFullAccess"]
        R_EBS["Role: ebs-csi-role\nSA: kube-system/ebs-csi-controller-sa\nPolicies: EC2 volume management"]
        R_LBC["Role: aws-load-balancer-controller-role\nSA: kube-system/aws-load-balancer-controller\nPolicies: AWSLoadBalancerControllerPolicy (custom)"]
        R_EDNS["Role: external-dns-role\nSA: kube-system/external-dns\nPolicies: Route53 ChangeResourceRecordSets\nroute53:ListHostedZones\nroute53:ListResourceRecordSets"]
        R_ESO["Role: external-secrets-operator-role\nSA: external-secrets/external-secrets-sa\nPolicies: SecretsManager GetSecretValue\nfor specific secret ARNs"]
    end

    OIDC --> R_MLF & R_AF & R_EFS & R_EBS & R_LBC & R_EDNS & R_ESO
```

---

## 4. Per-User IAM Provisioning (user-profiles)

```mermaid
sequenceDiagram
    participant TF as Terraform
    participant IAM as AWS IAM
    participant SM as Secrets Manager
    participant K8s as K8s aws-auth ConfigMap

    Note over TF: profiles/user-list.yaml parsed
    TF->>IAM: aws_iam_user: {username}
    TF->>IAM: aws_iam_access_key: {username}
    TF->>IAM: aws_iam_role: mlplatform-access-{firstName}-{lastName}
    TF->>IAM: Attach policy based on role
    
    alt role == "Developer"
        TF->>IAM: Attach mlplatform_developer_access_policy
        Note right of IAM: Permissions: EKS Describe*, EC2 full,\nS3 full, RDS Describe*, VPC full
        TF->>K8s: Add to aws-auth ConfigMap\n(group: system:masters)
    else role == "User"
        TF->>IAM: Attach mlplatform_user_access_policy
        Note right of IAM: Permissions: SageMaker\nListEndpoints, DescribeEndpoint,\nListModels only
    end

    TF->>SM: aws_secretsmanager_secret: {username}
    TF->>SM: Put value JSON:\n{ACCESS_KEY_ID, SECRET_ACCESS_KEY,\nAWS_ROLE_ARN, email, firstName, lastName}
```

### User IAM Policies

**Developer Policy** (`AccessPolicyDeveloper.json`):
```json
{
  "Statement": [
    { "Effect": "Allow", "Action": "eks:Describe*", "Resource": "*" },
    { "Effect": "Allow", "Action": "ec2:*", "Resource": "*" },
    { "Effect": "Allow", "Action": "s3:*", "Resource": "*" },
    { "Effect": "Allow", "Action": "rds:Describe*", "Resource": "*" },
    { "Effect": "Allow", "Action": "vpc:*", "Resource": "*" }
  ]
}
```

**User Policy** (`AccessPolicyUser.json`):
```json
{
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:ListEndpoints",
        "sagemaker:DescribeEndpoint",
        "sagemaker:ListModels",
        "sagemaker:DescribeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 5. Network Security Groups

```mermaid
graph TB
    subgraph VPC_SG["Security Groups"]
        SG_MGMT1["worker_group_mgmt_one\nIngress: SSH (22) from 10.0.0.0/8"]
        SG_MGMT2["worker_group_mgmt_two\nIngress: SSH (22) from 192.168.0.0/16"]
        SG_ALL["all_worker_mgmt\nIngress: SSH from 10.0.0.0/8\n10.0.0.0/8, 172.16.0.0/12,\n192.168.0.0/16"]
        SG_NFS["allow_nfs\nIngress: TCP 2049 (NFS/EFS)\nfrom private subnet CIDRs\n10.0.1.0/24, 10.0.2.0/24, 10.0.3.0/24"]
        SG_RDS["rds_sg\nIngress: TCP 5000 (PostgreSQL)\nTCP 5432 (MySQL)\nfrom private subnet CIDRs only"]
    end

    EKS_NODES["EKS Worker Nodes"] --> SG_MGMT1 & SG_MGMT2 & SG_ALL
    EFS_MNT["EFS Mount Targets"] --> SG_NFS
    RDS_INST["RDS Instances"] --> SG_RDS
```

**Missing Security Controls** (known gaps — see [Security Architecture](06_security_architecture.md)):
- No `NetworkPolicy` resources — all pods can reach all pods in all namespaces
- No `PodSecurityStandards` — containers can run as root
- No `ResourceQuota` per namespace — one noisy tenant can starve others

---

## 6. Helm Chart Configurations — Key Values

### 6.1 Airflow (community 8.7.1)

| Key | Value |
|-----|-------|
| `executor` | `KubernetesExecutor` |
| `scheduler.image` | `seblum/airflow:2.6.3-python3.11-custom-light` |
| `webserver.baseUrl` | `http://{domain_name}/airflow` |
| `web.webserverConfig.configMapName` | `airflow-webserver-config` |
| `dags.gitSync.repo` | `{git_sync_repository_url}` |
| `dags.gitSync.branch` | `{git_sync_branch}` |
| `dags.gitSync.syncWait` | `60` |
| `dags.gitSync.syncTimeout` | `120` |
| `logs.persistence.storageClass` | `efs-sc` |
| `logs.persistence.size` | `5Gi` |
| `logs.persistence.accessMode` | `ReadWriteMany` |
| `web.defaultView` | `grid` |
| `scheduler.timezone` | `Europe/Amsterdam` |
| `web.auth.oauth.providers` | GitHub OAuth (clientId, clientSecret) |

### 6.2 MLflow (Custom Local Chart v2.4.1)

| Key | Value |
|-----|-------|
| `image.repository` | `seblum/mlflow` |
| `image.tag` | `v2.4.1` |
| `backendStore` | MySQL URI via RDS |
| `artifactRoot` | `s3://{bucket_name}` |
| `serviceAccount.annotations` | IRSA role ARN |
| `ingress.annotations` | ALB group `mlplatform`, path `/mlflow` |
| `externalSecrets.enabled` | `true` (if ESO deployed) |

### 6.3 JupyterHub (official 2.0.0)

| Key | Value |
|-----|-------|
| `hub.config.GitHubOAuthenticator.oauth_callback_url` | `https://{domain}/jupyterhub/hub/oauth_callback` |
| `hub.config.GitHubOAuthenticator.client_id` | `{jupyterhub_git_client_id}` |
| `hub.config.GitHubOAuthenticator.allowed_organizations` | `["{github_org}"]` |
| `singleuser.image.name` | `seblum/jupyterhub-server` |
| `singleuser.image.tag` | `latest` |
| `singleuser.defaultUrl` | `/lab` |
| `singleuser.storage.type` | `dynamic` (EFS) |
| `singleuser.lifecycleHooks.postStart.exec.command` | `git clone {repo}` |
| `cull.enabled` | `true` |
| `cull.timeout` | `3600` (1 hour) |
| `proxy.secretToken` | `{jupyterhub_proxy_secret_token}` |

### 6.4 Grafana (grafana.github.io 6.57.4)

| Key | Value |
|-----|-------|
| `adminPassword` | Set via variable |
| `auth.github.enabled` | `true` |
| `auth.github.client_id` | `{grafana_git_client_id}` |
| `auth.github.allowed_organizations` | GitHub org name |
| `datasources.datasources.yaml` | Prometheus URL |
| `dashboardProviders` | `grafana.com` IDs: 2, 315, 6417 |
| `ingress.annotations` | ALB group `mlplatform`, path `/grafana` |

---

## 7. EFS Storage Class Configuration

```yaml
# StorageClass: efs-sc (default for platform)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap          # Access Point mode (per-PVC isolation)
  fileSystemId: fs-{efs_id}
  directoryPerms: "777"
  gidRangeStart: "1000"
  gidRangeEnd: "2000"
  basePath: "/dynamic_provisioning"
mountOptions:
  - iam                              # IAM-based access authentication
reclaimPolicy: Retain
volumeBindingMode: Immediate
```

```yaml
# PVC: airflow-logs
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: airflow-logs
  namespace: airflow
spec:
  accessModes: ["ReadWriteMany"]     # Multiple pods can mount simultaneously
  storageClassName: efs-sc
  resources:
    requests:
      storage: 5Gi
```

---

## 8. Terraform State Backend Detail

```mermaid
graph LR
    subgraph BOOTSTRAP["bootstrap/ (run once, local state)"]
        B_S3["aws_s3_bucket\nmlplatform-terraform-state\n• versioning: enabled\n• encryption: AES256\n• public access: blocked"]
        B_DDB["aws_dynamodb_table\nmlplatform-terraform-locks\n• billing: PAY_PER_REQUEST\n• hash_key: LockID\n• attr: LockID STRING"]
    end

    subgraph REMOTE["All other stacks — remote backend"]
        TF_ROOT["deployment/ backend\nbucket: mlplatform-terraform-state\nkey: deployment.tfstate\ndynamodb_table: mlplatform-terraform-locks\nencrypt: true\nregion: eu-central-1"]
        TF_EKS["infrastructure/eks/ backend\nkey: eks.tfstate"]
        TF_VPC["infrastructure/vpc/ backend\nkey: vpc.tfstate"]
        TF_RDS["infrastructure/rds/ backend\nkey: rds.tfstate"]
    end

    B_S3 -->|"Stores"| TF_ROOT & TF_EKS & TF_VPC & TF_RDS
    B_DDB -->|"Locks"| TF_ROOT & TF_EKS & TF_VPC & TF_RDS
```

**Terraform Remote Data Sources** (cross-stack references):
- `deployment/` reads VPC outputs → `terraform_remote_state.vpc`
- `deployment/` reads EKS outputs → `terraform_remote_state.eks`
- Each module in `deployment/main.tf` passes these as variables

---

## 9. Airflow GitHub OAuth — WebServerConfig.py

The custom `WebServerConfig.py` maps GitHub organization teams to Airflow FAB roles.

```python
# Role → Team mapping (actual code pattern)
GITHUB_ORG = "mlplatform-seblum-me"   # Hardcoded GitHub org
ROLE_MAPPING = {
    "Admin":  f"{GITHUB_ORG}/airflow-admin-team",
    "User":   f"{GITHUB_ORG}/airflow-users-team",
    "Viewer": f"{GITHUB_ORG}/airflow-viewers-team",
    "Op":     f"{GITHUB_ORG}/airflow-op-team",
    "Public": f"{GITHUB_ORG}/airflow-public-team",
}
# Session: 30-minute timeout, force re-auth + role sync on expiry
```

**OAuth Scopes**: `read:org`, `read:user`, `user:email`

---

## 10. Computed Local Values (locals.tf)

| Local | Value | Used By |
|-------|-------|---------|
| `name_prefix` | `mlplatform-{random 12-char string}` | All resource names |
| `cluster_name` | `mlplatform-eks-cluster` | EKS, Helm, K8s provider |
| `vpc_name` | `mlplatform-vpc` | VPC module |
| `mlflow_tracking_uri` | `http://mlflow-service.mlflow.svc.cluster.local` | Airflow vars, JupyterHub env |
| `airflow_variable_list` | Map of env vars injected into Airflow | Airflow DAGs |
| `developers_user_access_auth_list` | List of Dev users for aws-auth configmap | EKS module |
| `ecr_sagemaker_image_tag` | SageMaker ECR image tag | Airflow variable |
