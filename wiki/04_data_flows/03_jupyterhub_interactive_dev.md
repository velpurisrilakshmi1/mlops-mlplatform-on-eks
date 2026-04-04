# Data Flow — Interactive Development in JupyterHub

> **Scenario**: A data scientist logs in with GitHub, launches a JupyterHub server, gets their workspace auto-configured with a cloned repo and MLflow connection, and runs experiments that are tracked in MLflow.  
> **Actors**: Data Scientist, GitHub OAuth, JupyterHub Hub, EKS, EFS, MLflow

---

## Overview

```mermaid
graph LR
    DS[Data Scientist\n(Browser)] -->|HTTPS /jupyterhub| ALB2[AWS ALB]
    ALB2 --> JHB_PROXY[JupyterHub Proxy]
    JHB_PROXY -->|OAuth redirect| GH[GitHub OAuth]
    GH -->|Callback + token| JHB_HUB[JupyterHub Hub\n(org membership check)]
    JHB_HUB -->|Spawn| K8S2[Kubernetes API]
    K8S2 -->|Create pod| JUSER[Single-User Server Pod\nseblum/jupyterhub-server:latest]
    JUSER -->|postStart: git clone| GIT2[Git Repository]
    JUSER -->|Mount| EFS3[EFS Volume\nPersistent home dir]
    JUSER -->|MLFLOW_TRACKING_URI\nenv var| MLF3[MLflow Server\nInternal DNS]
    MLF3 -->|Store runs| RDS3[RDS MySQL] & S3_3[S3 Artifacts]

    style DS fill:#e3f2fd
    style JUSER fill:#e8f5e9
    style EFS3 fill:#fff3e0
    style MLF3 fill:#fce4ec
```

---

## Detailed Sequence Diagram

```mermaid
sequenceDiagram
    actor DS as Data Scientist
    participant Browser
    participant ALB3 as AWS ALB\n(internet-facing)
    participant PROXY as JupyterHub Proxy\n(jupyterhub ns)
    participant HUB as JupyterHub Hub\n(jupyterhub ns)
    participant GH3 as GitHub OAuth\napi.github.com
    participant K8S3 as Kubernetes API
    participant NODE as EKS Worker Node
    participant JUSER2 as Single-User Server Pod\nseblum/jupyterhub-server:latest
    participant EFS4 as AWS EFS\nPersistent Volume
    participant GIT3 as Git Repository\n(GitHub)
    participant MLF4 as MLflow Tracking API\nhttp://mlflow-service.mlflow.svc
    participant MYSQL2 as RDS MySQL
    participant S3_4 as S3 Artifact Bucket

    DS->>Browser: Navigate to https://domain.com/jupyterhub
    Browser->>ALB3: HTTPS GET /jupyterhub
    ALB3->>PROXY: Forward request
    PROXY->>HUB: Unauthenticated request
    HUB->>Browser: Redirect to GitHub OAuth
    Browser->>GH3: GET /login/oauth/authorize\n(client_id, scope: user:email read:org)
    GH3->>DS: Show GitHub authorize screen
    DS->>GH3: Approve access
    GH3->>Browser: Redirect with authorization code
    Browser->>HUB: GET /jupyterhub/hub/oauth_callback?code=...
    HUB->>GH3: POST /login/oauth/access_token (exchange code)
    GH3->>HUB: Return access token
    HUB->>GH3: GET /user (get username + email)
    HUB->>GH3: GET /orgs/{org}/members/{username}\n(verify org membership)
    
    alt User NOT in allowed organization
        HUB->>Browser: 403 Unauthorized
    else User IS in allowed organization
        HUB->>Browser: Set session cookie, redirect to /jupyterhub/spawn
    end

    Note over HUB, K8S3: Server Spawn (if no existing pod)
    
    HUB->>K8S3: GET pods with label: hub.jupyter.org/username={username}
    
    alt Pod already exists
        K8S3->>HUB: Return existing pod IP
    else Pod does not exist
        HUB->>K8S3: POST /api/v1/namespaces/jupyterhub/pods\n(pod spec below)
        K8S3->>NODE: Schedule pod on available node
        NODE->>NODE: Pull image: seblum/jupyterhub-server:latest
        NODE->>EFS4: Mount PVC (ReadWriteOnce per user)
        
        Note over JUSER2: postStart lifecycle hook runs
        JUSER2->>GIT3: git clone {git_repository_url} /home/jovyan/work
        GIT3->>JUSER2: Repository files at /home/jovyan/work
        
        Note over JUSER2: Pod becomes Ready
        K8S3->>HUB: Pod IP + readiness
    end

    HUB->>PROXY: Register route: /jupyterhub/user/{username}/ → pod:8888
    PROXY->>Browser: Redirect to /jupyterhub/user/{username}/lab
    Browser->>PROXY: Notebook requests
    PROXY->>JUSER2: Forward to JupyterLab (port 8888)

    Note over DS, JUSER2: Data Scientist works in JupyterLab

    DS->>JUSER2: Open notebook\nNotebook code runs mlflow.log_*
    
    JUSER2->>MLF4: POST /api/2.0/mlflow/runs/create\nTracking URI from MLFLOW_TRACKING_URI env var
    MLF4->>MYSQL2: INSERT runs table
    
    JUSER2->>MLF4: POST /api/2.0/mlflow/runs/log-parameter
    MLF4->>MYSQL2: INSERT params table
    
    JUSER2->>MLF4: POST /api/2.0/mlflow/runs/log-metric
    MLF4->>MYSQL2: INSERT metrics table
    
    JUSER2->>MLF4: PUT /api/2.0/mlflow/runs/log-artifact\n(large files streamed)
    MLF4->>S3_4: PutObject artifacts\n(MLflow server's IRSA role)

    Note over JUSER2, EFS4: Notebook files auto-saved to EFS
    JUSER2->>EFS4: Write /home/jovyan/{username}/*.ipynb

    Note over HUB: After inactivity timeout (culling)
    HUB->>K8S3: DELETE pod jupyter-{username}
    note right of EFS4: User data persists on EFS\nAvailable on next login
```

---

## Single-User Pod Specification

```yaml
# Pod created by JupyterHub Hub for each logged-in user
apiVersion: v1
kind: Pod
metadata:
  name: jupyter-{username}
  namespace: jupyterhub
  labels:
    hub.jupyter.org/username: "{username}"
    component: singleuser-server
spec:
  containers:
    - name: notebook
      image: seblum/jupyterhub-server:latest
      ports:
        - containerPort: 8888
      env:
        - name: MLFLOW_TRACKING_URI
          value: "http://mlflow-service.mlflow.svc.cluster.local"
        - name: JUPYTERHUB_API_URL
          value: "http://hub.jupyterhub.svc:8081/jupyterhub/hub/api"
        - name: JPY_API_TOKEN
          valueFrom:
            secretKeyRef:
              name: jupyterhub-hub-secret
              key: hub.config
      volumeMounts:
        - name: home
          mountPath: /home/jovyan
      lifecycle:
        postStart:
          exec:
            command:
              - /bin/sh
              - -c
              - "git clone {git_repository_url} /home/jovyan/work || true"
  volumes:
    - name: home
      persistentVolumeClaim:
        claimName: claim-{username}        # Dynamically provisioned per user on EFS
  automountServiceAccountToken: false
```

---

## User Workspace Layout

```
/home/jovyan/                    ← EFS persistent volume (per-user PVC)
├── work/                        ← Cloned from git_repository_url (postStart)
│   ├── notebooks/
│   ├── src/
│   └── requirements.txt
├── .ipynb_checkpoints/          ← Auto-saved checkpoint files
└── {user-created files}
```

---

## Environment Variables in User Pods

| Variable | Value | Source |
|----------|-------|--------|
| `MLFLOW_TRACKING_URI` | `http://mlflow-service.mlflow.svc.cluster.local` | Helm values → JupyterHub config |
| `JUPYTERHUB_BASE_URL` | `/jupyterhub` | JupyterHub internal |
| `PATH` | Includes conda envs | Docker image |
| `AWS_DEFAULT_REGION` | (Not injected by default) | User can set in notebook |

---

## JupyterHub Authn/Authz Configuration

```mermaid
graph TB
    GITHUB_AUTH[GitHubOAuthenticator\njupyterhub/oauthenticator]

    GITHUB_AUTH -->|configures| CB_URL["oauth_callback_url:\nhttps://{domain}/jupyterhub/hub/oauth_callback"]
    GITHUB_AUTH -->|configures| CLIENT_ID["client_id:\n{jupyterhub_git_client_id}"]
    GITHUB_AUTH -->|configures| ORG["allowed_organizations:\n['{github_org}']"]
    GITHUB_AUTH -->|configures| SCOPE["scope: ['user:email', 'read:org']"]

    ORG -->|Effect| ORG_CHECK["Only members of\nspecified GitHub org\ncan access JupyterHub"]
    
    subgraph ACCESS_CHECK["Access Decision Logic"]
        CHECK1{User authenticated\nwith GitHub?}
        CHECK2{User is member of\nallowed org?}
        ALLOW[Allow + Spawn server]
        DENY[Deny: 403 Unauthorized]
        
        CHECK1 -->|Yes| CHECK2
        CHECK1 -->|No| DENY
        CHECK2 -->|Yes| ALLOW
        CHECK2 -->|No| DENY
    end
```

---

## Server Lifecycle (Culling)

```mermaid
stateDiagram-v2
    [*] --> Spawning: User logs in / clicks Start Server
    Spawning --> Ready: Pod running, git clone complete
    Ready --> Active: User sends requests
    Active --> Idle: No notebook activity (kernels paused)
    Idle --> Culled: After cull.timeout = 3600s
    Culled --> [*]: Pod deleted; EFS data retained
    
    note right of Culled: Next login re-spawns pod\nUser data on EFS intact\ngit clone skipped (dir exists)
```

---

## AWS Services Involved

| Service | Role |
|---------|------|
| **EKS** | Runs Hub, Proxy, and single-user server pods |
| **EFS** | Per-user persistent home directories (`ReadWriteOnce` per pod) |
| **ALB** | Routes `/jupyterhub` traffic; handles HTTPS termination |
| **Route 53** | DNS for the JupyterHub domain |
| **IAM** | Hub uses K8s ServiceAccount to create/delete pods |
| **RDS MySQL** | MLflow stores experiment tracking data |
| **S3** | MLflow stores model artifacts uploaded from notebooks |
| **GitHub** | OAuth authentication + org membership check |

---

## Common Issues & Solutions

| Issue | Root Cause | Solution |
|-------|------------|---------|
| Pod stuck at `Spawning` | Docker image pull timeout | Pre-pull image on nodes with DaemonSet |
| EFS mount fails | Security group missing port 2049 | Check `allow_nfs` SG attached to EFS mount targets |
| git clone fails | Wrong token / SSH vs HTTPS mismatch | Use HTTPS with personal access token |
| 403 on login | User not in allowed GitHub org | Add user to GitHub org `{github_org}` |
| MLflow connection refused | Pod DNS can't resolve `mlflow-service.mlflow.svc` | Check CoreDNS; verify MLflow pod is running |
