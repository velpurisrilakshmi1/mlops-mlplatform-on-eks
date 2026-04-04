# Data Flow — Model Deployment to SageMaker

> **Scenario**: An Airflow DAG builds a Docker image from a trained MLflow model, pushes it to ECR, deploys a SageMaker endpoint, and the Streamlit dashboard reflects the new endpoint.  
> **Actors**: Airflow KubernetesExecutor, MLflow Model Registry, ECR, SageMaker, Streamlit Dashboard

---

## Overview

```mermaid
graph LR
    MLF_REG[MLflow\nModel Registry] -->|Load model URI| AF_TASK[Airflow Task Pod\nKubernetesExecutor]
    AF_TASK -->|mlflow sagemaker build-and-push-container\ndocker build + push| ECR[ECR Repository\nmlflow-sagemaker-deployment]
    AF_TASK -->|mlflow.sagemaker.deploy| SM_API[SageMaker API]
    ECR -->|Pull image| SM_CONT[SageMaker Endpoint\nContainer]
    SM_API -->|Create endpoint| SM_CONT
    SM_CONT -->|Inference REST| CLIENTS[Downstream\nApplications]
    SM_CONT -->|describe_endpoints| STREAM[Streamlit Dashboard\nsagemaker namespace]

    style MLF_REG fill:#e8f5e9
    style AF_TASK fill:#e3f2fd
    style ECR fill:#fff3e0
    style SM_CONT fill:#fce4ec
    style STREAM fill:#f3e5f5
```

---

## Detailed Sequence Diagram

```mermaid
sequenceDiagram
    actor MLE as ML Engineer
    participant AF_UI as Airflow UI
    participant SCHED as Airflow Scheduler
    participant KEXEC as KubernetesExecutor
    participant K8S as Kubernetes API
    participant TPOD as Task Pod\n(ephemeral)
    participant TPOD2 as Task Pod (build)
    participant TPOD3 as Task Pod (deploy)
    participant MLF as MLflow Server\n(mlflow.svc)
    participant MYSQL as RDS MySQL
    participant ECR2 as AWS ECR\nmlflow-sagemaker-deployment
    participant IAM2 as AWS IAM\n(IRSA)
    participant SM2 as AWS SageMaker
    participant STREAM2 as Streamlit App\nsagemaker namespace

    MLE->>AF_UI: Trigger deployment DAG\n(pass: model_name, model_version)
    AF_UI->>SCHED: Create DagRun
    
    rect rgb(232, 245, 233)
        Note over SCHED, MLF: Step 1 — Fetch registered model
        SCHED->>KEXEC: Queue task: fetch_model_uri
        KEXEC->>TPOD: Spawn task pod
        TPOD->>MLF: GET /api/2.0/mlflow/model-versions/get\n?name={model_name}&version={version}
        MLF->>MYSQL: SELECT model_version WHERE name=... AND version=...
        MYSQL->>MLF: model_version.source = s3://{bucket}/{run_id}/artifacts/model
        MLF->>TPOD: Return model URI
        TPOD->>KEXEC: Store model_uri in XCom
        KEXEC->>K8S: Delete task pod
    end

    rect rgb(225, 245, 254)
        Note over SCHED, ECR2: Step 2 — Build & push Docker image
        SCHED->>KEXEC: Queue task: build_and_push_image
        KEXEC->>TPOD2: Spawn pod with Docker socket mount\nOR use Kaniko/Buildah
        TPOD2->>MLF: Download model artifacts from S3
        TPOD2->>TPOD2: mlflow sagemaker build-and-push-container\n--container mlflow-sagemaker-deployment\n--region eu-central-1
        TPOD2->>IAM2: AssumeRole via IRSA (sagemaker-access-role)
        IAM2->>TPOD2: Temp credentials
        TPOD2->>ECR2: docker login (ECR auth token)
        TPOD2->>ECR2: docker push {image_tag}
        TPOD2->>KEXEC: Store image_uri in XCom
        KEXEC->>K8S: Delete build pod
    end

    rect rgb(252, 228, 236)
        Note over SCHED, SM2: Step 3 — Deploy SageMaker endpoint
        SCHED->>KEXEC: Queue task: deploy_endpoint
        KEXEC->>TPOD3: Spawn pod
        TPOD3->>IAM2: AssumeRole via IRSA (sagemaker-access-role)
        IAM2->>TPOD3: Temp credentials
        TPOD3->>SM2: mlflow.sagemaker.deploy(\n  app_name={model_name},\n  model_uri={uri},\n  image_url={ecr_image_uri},\n  execution_role_arn={role},\n  region_name=eu-central-1,\n  mode=mlflow.sagemaker.DEPLOY_MODE_REPLACE\n)
        SM2->>ECR2: Pull container image
        SM2->>SM2: Provision endpoint instance
        SM2->>TPOD3: Endpoint status: InService
        TPOD3->>KEXEC: task success
        KEXEC->>K8S: Delete deploy pod
    end

    rect rgb(243, 229, 245)
        Note over STREAM2: Step 4 — Dashboard reflects new endpoint
        STREAM2->>IAM2: Read credentials from K8s secret\n(static IAM user, read-only)
        IAM2->>STREAM2: Credentials validated
        STREAM2->>SM2: boto3.client.list_endpoints()
        SM2->>STREAM2: Return endpoint list (includes new endpoint)
        STREAM2->>SM2: boto3.client.describe_endpoint(EndpointName={name})
        SM2->>STREAM2: Endpoint status, ARN, creation time
        MLE->>STREAM2: Navigate to /sagemaker
        STREAM2->>MLE: Render endpoint cards with status
    end
```

---

## Step-by-Step Description

### Phase 1: Trigger and Setup

1. **ML Engineer triggers DAG** via Airflow UI (authenticated with GitHub OAuth). Passes model name and version as DAG parameters.
2. **Scheduler logs DagRun** in PostgreSQL `dag_run` table.
3. **Airflow variables** already configured (`ECR_REPOSITORY_NAME`, `ECR_SAGEMAKER_IMAGE_TAG`, `AWS_REGION`).

### Phase 2: Fetch Trained Model

4. **MLflow model lookup**: Task pod queries MLflow's REST API at the internal Kubernetes DNS address `http://mlflow-service.mlflow.svc.cluster.local`.
5. **Model URI retrieved**: Returns `s3://mlplatform-{prefix}-mlflow-mlflow/{run_id}/artifacts/model`.
6. **XCom storage**: Model URI stored in Airflow XCom for downstream tasks.

### Phase 3: Container Build & Push

7. **Docker image build**: Task pod runs `mlflow sagemaker build-and-push-container`. This:
   - Downloads the MLflow model from S3.
   - Wraps it in a SageMaker-compatible container using `mlflow.sagemaker`.
   - Tags the image with the ECR repository URI.
8. **ECR authentication**: Uses IRSA-vended short-lived credentials to authenticate via `aws ecr get-login-password`.
9. **Image push**: Pushes to `{account_id}.dkr.ecr.eu-central-1.amazonaws.com/mlflow-sagemaker-deployment:{tag}`.

### Phase 4: SageMaker Endpoint Deployment

10. **Endpoint deploy**: Calls `mlflow.sagemaker.deploy()` with:
    - `mode=DEPLOY_MODE_REPLACE` (updates existing endpoint with zero-downtime rolling update).
    - `execution_role_arn`: SageMaker execution role (separate from IRSA).
    - `instance_type`: Configurable (e.g., `ml.t2.medium`).
11. **SageMaker lifecycle**:
    - Creates an endpoint configuration.
    - Pulls image from ECR.
    - Starts model server on managed infrastructure.
    - Runs health checks.
12. **Endpoint status**: Transitions `Creating → InService` (typically 5–7 minutes).

### Phase 5: Dashboard Reflection

13. **Streamlit reads endpoints**: The Streamlit app in the `sagemaker` namespace polls SageMaker's `list_endpoints` API using read-only IAM credentials (stored as K8s Secret).
14. **Dashboard displays**: Shows endpoint name, status, ARN, creation time, and instance type.

---

## IAM Roles Involved

```mermaid
graph TB
    AF_SA["Airflow ServiceAccount\n(IRSA role: airflow-iam-role)\nPermissions: S3 data bucket, MLflow S3 policy"]
    SAGE_IRSA["SageMaker Deploy Role\n(IRSA: sagemaker-access-role)\nPermissions: SageMaker:*, ECR:*, IAM:PassRole"]
    SAGE_EXEC["SageMaker Execution Role\nPassed to SageMaker service\nPermissions: S3 artifacts read, ECR pull"]
    DASH_IAM["Dashboard IAM User\n(static credentials)\nPermissions: SageMaker:ListEndpoints\nSageMaker:DescribeEndpoint (read-only)"]

    TPOD_AF[Airflow Task Pod] -->|uses| AF_SA
    TPOD_BUILD[Build Task Pod] -->|uses| SAGE_IRSA
    TPOD_DEPLOY[Deploy Task Pod] -->|uses| SAGE_IRSA
    SAGE_EXEC -->|attached to| SM[SageMaker Endpoint]
    DASH_IAM --> STREAM3[Streamlit App]
```

---

## Airflow Variables Used

| Variable | Value | Purpose |
|----------|-------|---------|
| `MLFLOW_TRACKING_URI` | `http://mlflow-service.mlflow.svc.cluster.local` | Retrieve model URI |
| `ECR_REPOSITORY_NAME` | `mlflow-sagemaker-deployment` | Container registry |
| `ECR_SAGEMAKER_IMAGE_TAG` | `{computed tag}` | Docker image version |
| `AWS_REGION` | `eu-central-1` | SageMaker API region |
| `s3_access_name` | `airflow-s3-data-bucket-access-credentials` | S3 data access secret ref |

---

## AWS Services Involved

| Service | Role |
|---------|------|
| **MLflow** (in-cluster) | Model registry, artifact URI source |
| **S3 (artifact bucket)** | Model artifact storage |
| **ECR** | Built container image storage |
| **SageMaker** | Managed endpoint provisioning + inference |
| **IAM** | IRSA for task pods, execution role for SageMaker |
| **EKS** | Runs all task pods and Streamlit dashboard |
| **RDS MySQL** | MLflow model version metadata |

---

## Deployment Modes

| Mode | Behaviour | Use Case |
|------|-----------|---------|
| `CREATE` | Create new endpoint | First deployment |
| `REPLACE` | Update endpoint (rolling, zero-downtime) | Model update |
| `ADD` | Add new variant to existing endpoint | A/B testing |
