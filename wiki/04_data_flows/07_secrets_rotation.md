# Data Flow — Secrets Rotation

> **Scenario**: Secrets (DB passwords, OAuth tokens, AWS access keys) need to be rotated. This covers both the automated ESO sync path and the manual rotation path.  
> **Actors**: Platform Admin, AWS Secrets Manager, External Secrets Operator (ESO), Kubernetes, Application Pods

---

## Overview: Two Secrets Paths

```mermaid
graph TB
    subgraph PATH_A["Path A — ESO Automated Sync (MLflow RDS)"]
        SM_A[AWS Secrets Manager\nSecret: mlflow-rds]
        ESO_A[External Secrets Operator\nClusterSecretStore]
        ES_A[ExternalSecret CR\n(mlflow namespace)]
        K8S_SEC_A[K8s Secret: mlflow-{suffix}\nAuto-refreshed]
        MLF_POD_A[MLflow Pod\nMounts secret as env var]
        
        SM_A -->|"ESO polls every 1h"| ESO_A
        ESO_A -->|ExternalSecret reconcile| ES_A
        ES_A -->|Creates/updates| K8S_SEC_A
        K8S_SEC_A -->|Projected into pod env| MLF_POD_A
    end

    subgraph PATH_B["Path B — Manual Rotation (Airflow OAuth, DB passwords)"]
        ADMIN_B[Platform Admin\nUpdates tfvars / secret value]
        TF_B[Terraform apply\nUpdates K8s Secret]
        K8S_SEC_B[K8s Secret\n(airflow namespace)]
        AF_POD_B[Airflow Pod\nRestarts to pick up new secret]
        
        ADMIN_B -->|Edit prod.tfvars| TF_B
        TF_B -->|kubectl apply| K8S_SEC_B
        K8S_SEC_B -->|Rolling restart| AF_POD_B
    end

    style PATH_A fill:#e8f5e9
    style PATH_B fill:#e3f2fd
```

---

## Path A: Automated Rotation via External Secrets Operator

### Architecture

```mermaid
graph TB
    subgraph AWS_CLOUD["AWS"]
        SM6["AWS Secrets Manager\nSecret: mlflow-rds\nValue: {db_password, db_host, db_port}"]
        IRSA_ESO["IRSA Role: external-secrets-operator-role\nPermissions: secretsmanager:GetSecretValue\nfor specific secret ARNs"]
    end

    subgraph K8S_CLUSTER2["Kubernetes Cluster"]
        ESO_CTRL["External Secrets Operator Controller\n(external-secrets namespace)\nServiceAccount: external-secrets-sa (IRSA)"]
        
        CSS["ClusterSecretStore\nProvider: AWS Secrets Manager\nRegion: eu-central-1\nAuth: IRSA (service account annotation)"]
        
        ES_CR["ExternalSecret CR\n(mlflow namespace)\nSpec:\n  secretStoreRef: aws-secrets-manager\n  target.name: mlflow-{suffix}\n  refreshInterval: 1h\n  data:\n    - secretKey: DB_PASSWORD\n      remoteRef.key: mlflow-rds\n      remoteRef.property: db_password"]
        
        K8S_SECRET2["K8s Secret: mlflow-{suffix}\n(auto-managed by ESO)\nData: DB_PASSWORD, DB_HOST, DB_PORT"]
        
        MLF_POD2["MLflow Deployment\nenvFrom:\n  - secretRef:\n      name: mlflow-{suffix}"]
    end

    SM6 -->|"GetSecretValue API call\n(IRSA auth)"| ESO_CTRL
    IRSA_ESO -->|"Vended via OIDC"| ESO_CTRL
    ESO_CTRL -->|"Reads"| CSS
    CSS -->|"Reconciles"| ES_CR
    ES_CR -->|"Creates/updates"| K8S_SECRET2
    K8S_SECRET2 -->|"Mounted as env vars"| MLF_POD2

    style SM6 fill:#fff3e0
    style ESO_CTRL fill:#e8f5e9
    style K8S_SECRET2 fill:#fce4ec
```

### ESO-Automated Rotation Sequence

```mermaid
sequenceDiagram
    actor ADMIN2 as Platform Admin
    participant SM7 as AWS Secrets Manager
    participant ESO_C as ESO Controller\n(external-secrets ns)
    participant CSS2 as ClusterSecretStore
    participant ES2 as ExternalSecret CR\n(mlflow ns)
    participant K8S_SEC2 as K8s Secret: mlflow-{suffix}
    participant MLF2 as MLflow Pod

    Note over ADMIN2, SM7: Step 1 — Update secret in AWS
    ADMIN2->>SM7: Update secret value:\naws secretsmanager put-secret-value\n--secret-id mlflow-rds\n--secret-string {db_password: new-password}

    Note over ESO_C, K8S_SEC2: Step 2 — ESO detects change (within refreshInterval)
    
    loop Every refreshInterval (default: 1h)
        ESO_C->>CSS2: Reconcile ClusterSecretStore
        CSS2->>SM7: GetSecretValue(mlflow-rds)
        SM7->>CSS2: Return current secret value
        CSS2->>ESO_C: Secret data
        ESO_C->>ES2: Check ExternalSecret condition
        
        alt Secret value changed
            ESO_C->>K8S_SEC2: Update K8s Secret data\n(new DB_PASSWORD)
            Note over K8S_SEC2: Secret updated but pod NOT restarted automatically
        else No change
            ESO_C->>ES2: Update .status.refreshTime
        end
    end

    Note over MLF2: Step 3 — Pod must restart to pick up new secret
    Note right of MLF2: K8s Secrets as env vars are\nNOT hot-reloaded into running pods\nRolling restart required!
    
    ADMIN2->>MLF2: kubectl rollout restart deployment mlflow\n-n mlflow
    MLF2->>MLF2: New pods start with updated env vars
    MLF2->>SM7: (via K8s Secret) Connect to RDS with new password
```

---

## Path B: Manual Rotation — Airflow Secrets

### What Needs Manual Rotation

| Secret | K8s Secret Name | Contents | Rotation Trigger |
|--------|----------------|----------|-----------------|
| Airflow DB password | `{prefix}-db-auth` | `postgresql-password` | RDS password change |
| Git token | `{prefix}-https-git-secret` | `username`, `password` | GitHub PAT expiry |
| GitHub OAuth | `{prefix}-organization-git-secret` | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | OAuth app rotation |
| AWS info | `{ns}-aws-account-information` | `AWS_REGION`, `AWS_ID` | Account changes |

### Manual Rotation Sequence

```mermaid
sequenceDiagram
    actor ADMIN3 as Platform Admin
    participant TF3 as Terraform
    participant RDS_PG as RDS PostgreSQL
    participant K8S_SEC3 as K8s Secrets\n(airflow ns)
    participant AF3 as Airflow Pods

    Note over ADMIN3, AF3: Scenario: Rotate RDS PostgreSQL password

    ADMIN3->>ADMIN3: Generate new secure password\nopenssl rand -base64 32

    ADMIN3->>ADMIN3: Update prod.tfvars:\nairflow_db_password = new-secure-password

    ADMIN3->>TF3: terraform apply -target=module.rds\n-var-file=prod.tfvars

    TF3->>RDS_PG: aws_db_instance: modify password\n(may cause brief connection drop)

    TF3->>K8S_SEC3: kubernetes_secret: update\n{prefix}-db-auth\npostgresql-password = new-password

    Note over K8S_SEC3: K8s Secret updated
    Note right of AF3: Airflow pods still using old\npassword from env var cache

    ADMIN3->>AF3: kubectl rollout restart deployment\nairflow-web airflow-scheduler\n-n airflow

    AF3->>K8S_SEC3: New pods mount updated secret
    AF3->>RDS_PG: Connect with new password ✓
```

---

## Per-User AWS Access Key Rotation

```mermaid
sequenceDiagram
    actor PADMIN as Platform Admin
    participant TF8 as Terraform\nuser-profiles module
    participant IAM8 as AWS IAM
    participant SM8 as AWS Secrets Manager
    participant USER8 as User (Alice)

    Note over PADMIN: Periodic rotation or compromise response

    PADMIN->>TF8: terraform taint aws_iam_access_key.alice_smith
    PADMIN->>TF8: terraform apply -target=module.user_profiles.aws_iam_access_key.alice_smith

    TF8->>IAM8: Delete old access key (AKIA...)
    TF8->>IAM8: Create new access key
    IAM8->>TF8: Return new ACCESS_KEY_ID + SECRET_ACCESS_KEY

    TF8->>SM8: PutSecretValue for alice.smith\n(update with new credentials)

    Note over USER8: User retrieves new credentials
    USER8->>SM8: aws secretsmanager get-secret-value --secret-id alice.smith
    SM8->>USER8: New credentials JSON

    USER8->>USER8: aws configure --profile alice\n(update ~/.aws/credentials)
```

---

## Secrets Inventory

```mermaid
graph TB
    subgraph K8S_SECRETS["Kubernetes Secrets (by namespace)"]
        subgraph AF_SECRETS["airflow/"]
            S1["{prefix}-db-auth\nRDS PostgreSQL password"]
            S2["{prefix}-https-git-secret\nGit username + token"]
            S3["{prefix}-organization-git-secret\nGitHub OAuth app credentials"]
            S4["{ns}-aws-account-information\nAWS region, account ID"]
            S5["{ns}-sagemaker-access\nSageMaker role name"]
            S6["{ns}-{s3_secret_name}\nS3 data bucket access keys"]
        end
        subgraph MLF_SECRETS["mlflow/ (if ESO enabled)"]
            S7["mlflow-{suffix}\nRDS MySQL password (ESO-managed)"]
        end
        subgraph JHB_SECRETS["jupyterhub/"]
            S8["jupyterhub-hub-secret\nHub config + proxy token + OAuth secrets"]
        end
        subgraph SAGE_SECRETS["sagemaker/"]
            S9["sagemaker-dashboard-credentials\nStatic IAM user keys (read-only)"]
        end
    end

    subgraph AWS_SM["AWS Secrets Manager"]
        SM_USERS["Per-user: {username}\nACCESS_KEY, SECRET_KEY, ROLE_ARN, email"]
        SM_MLF2["mlflow-rds\nDB password (if ESO path)"]
        SM_OAUTH["(Optional) OAuth app secrets\nfor centralized rotation"]
    end

    SM_MLF2 -->|ESO sync| S7
    SM_USERS --> S6

    style AF_SECRETS fill:#e3f2fd
    style MLF_SECRETS fill:#e8f5e9
    style JHB_SECRETS fill:#fff3e0
    style SAGE_SECRETS fill:#fce4ec
```

---

## Rotation Runbook Quick Reference

| Secret Type | Rotation Method | Downtime? | Command |
|-------------|----------------|-----------|---------|
| RDS PostgreSQL password | Terraform taint + apply | ≤30s (connection reset) | `terraform taint module.rds.aws_db_instance.airflow` |
| RDS MySQL password | Terraform taint + apply | ≤30s | `terraform taint module.rds.aws_db_instance.mlflow` |
| GitHub PAT (git-sync) | Update tfvars + apply + rollout restart | No | `kubectl rollout restart deploy/airflow-scheduler -n airflow` |
| GitHub OAuth secrets | Update tfvars + apply | No (hot reload) | `terraform apply -target=kubernetes_secret.airflow_oauth` |
| MLflow DB (ESO) | Update AWS Secrets Manager + rollout restart | No | `kubectl rollout restart deploy/mlflow -n mlflow` |
| Per-user access keys | Terraform taint access_key | No | `terraform taint ...aws_iam_access_key.{user}` |
| Airflow Fernet Key | Update tfvars + apply | Requires full restart | Requires re-encryption of all connections |

---

## AWS Services Involved

| Service | Role |
|---------|------|
| **AWS Secrets Manager** | Source of truth for all sensitive values |
| **IAM** | Access key management, IRSA role for ESO |
| **EKS (Kubernetes)** | Stores K8s Secrets; pods consume via env vars |
| **External Secrets Operator** | Bridges Secrets Manager → K8s Secrets |
| **RDS** | Database whose passwords are rotated |
| **GitHub** | OAuth app credentials (client ID + secret) |
| **Terraform** | Drives declarative secret provisioning |
