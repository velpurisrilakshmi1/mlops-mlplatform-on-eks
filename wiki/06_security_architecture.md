# Security Architecture

> **Audience**: Security engineers, platform architects, compliance officers  
> **Purpose**: Complete security posture analysis — what IS hardened, what has critical gaps, and a prioritised remediation roadmap

---

## Threat Model Overview (STRIDE)

```mermaid
graph TB
    subgraph THREAT_SURFACE["Attack Surface — MLOps Platform"]
        subgraph EXTERNAL["External Threat Actors"]
            T_INTERNET["Internet User\n(Unauthenticated)"]
            T_PHISHING["Phishing / Social Eng.\n(Credential Theft)"]
            T_SUPPLY["Supply Chain\n(Compromised container image)"]
        end
        subgraph INTERNAL["Internal / Insider Threats"]
            T_INSIDER["Malicious insider\n(Privileged IAM user)"]
            T_MISCONFIG["Misconfiguration\n(Accidental data exposure)"]
            T_SCRIPT["Rogue ML script\n(Cryptomining on GPU nodes)"]
        end
    end

    subgraph COMPONENTS["Platform Components"]
        ALB["ALB\n(Internet-facing)"]
        AIRFLOW["Airflow UI/API"]
        MLFLOW["MLflow UI/API"]
        JHB["JupyterHub UI"]
        GRAFANA["Grafana UI"]
        DASH["Streamlit Dashboard"]
        EKS_API["EKS API Server\n(private endpoint)"]
        RDS_PG["RDS PostgreSQL\n(Airflow metadata)"]
        RDS_MY["RDS MySQL\n(MLflow metadata)"]
        S3_ART["S3: mlflow artifacts"]
        S3_DATA["S3: airflow data"]
        SM_SEC["Secrets Manager"]
    end

    T_INTERNET --> ALB
    ALB --> AIRFLOW & MLFLOW & JHB & GRAFANA & DASH
    T_PHISHING -->|"Stolen GitHub token"| AIRFLOW & JHB
    T_SUPPLY -->|"Malicious image"| EKS_API
    T_INSIDER -->|"IAM keys"| S3_ART & S3_DATA & RDS_PG
    T_SCRIPT -->|"Within pod"| S3_DATA & RDS_MY
```

### STRIDE Analysis Per Component

| Component | Spoofing | Tampering | Repudiation | Info Disclosure | DoS | Elevation |
|-----------|----------|-----------|-------------|-----------------|-----|-----------|
| ALB | ✅ HTTPS/TLS | ✅ WAF (not enabled) | ⚠️ No access logs | ✅ Private targets | ⚠️ No rate limiting | N/A |
| GitHub OAuth | ✅ OAuth state param | ✅ JWT signed | ❌ No audit log | ⚠️ Tokens in K8s | ✅ Short-lived | ⚠️ No MFA enforce |
| Airflow API | ✅ OAuth required | ⚠️ No API auth on internal | ❌ No API audit | ⚠️ DB password in K8s | ⚠️ No rate-limit | ❌ KubEx pod → system:masters |
| JupyterHub | ✅ OAuth required | ⚠️ User can exec arbitrary | ❌ No notebook audit | ⚠️ Shared EFS | ⚠️ No resource limits | ⚠️ Privileged pod possible |
| MLflow | ✅ OAuth proxy | ❌ No model signing | ❌ No run audit | ⚠️ S3 creds via SA | ⚠️ No API rate-limit | ⚠️ IRSA over-permissive |
| K8s API | ✅ OIDC GitHub | ✅ RBAC (partial) | ⚠️ Audit logs off | ⚠️ etcd unencrypted | ✅ etcd has auth | ❌ system:masters |
| RDS Postgres | ✅ Password auth | ✅ VPC locked | ❌ No query audit | ⚠️ Password in K8s SM | ✅ Private VPC | ✅ SG restricted |
| S3 Buckets | ✅ IAM IRSA | ✅ Block public | ❌ No access logging | ⚠️ No versioning policy | N/A | ⚠️ Broad prefix access |
| Secrets Manager | ✅ IAM auth | ✅ Encrypted | ✅ CloudTrail (if enabled) | ⚠️ Access key rotation | N/A | ⚠️ User keys long-lived |

---

## Current Security Controls (What IS Implemented)

```mermaid
graph TB
    subgraph IMPL["✅ Implemented Security Controls"]
        subgraph NETWORK_SEC["Network Security"]
            VPC_ISO["VPC Isolation\n10.0.0.0/16 private"]
            PRIV_SUBNETS["EKS nodes in private subnets\nNo direct internet access to nodes"]
            SG["Security Groups per component\nAirflow SG, MLflow SG, RDS SG\nLeast-privilege port rules"]
            NAT_GW["NAT Gateway for egress only\n(no inbound from internet to nodes)"]
            ALB_TLS["ALB terminates TLS\nACM certificates"]
        end

        subgraph IAM_SEC["IAM / Identity Security"]
            IRSA["IRSA (IAM Roles for Service Accounts)\nEach service SA → dedicated IAM role\nNo shared AWS credentials in pods"]
            GITHUB_OAUTH["GitHub OAuth on all UIs\nOrg membership enforcement\nTeam-based access (Viewer/User/Admin)"]
            PER_USER_ROLES["Per-user IAM roles\n(developer vs user policy)"]
            LEAST_PRIV["Component IAM policies\nMLflow: S3 prefix-scoped only\nAirflow: S3 prefix-scoped only\nExternalDNS: Route53 hosted zone only"]
        end

        subgraph DATA_SEC["Data Security"]
            S3_BLOCK["S3 Block Public Access\non all buckets"]
            S3_AES["S3 SSE-S3 (AES256)\nServer-side encryption enabled"]
            RDS_PRIVATE["RDS in private subnet\nNo public access"]
            SM_ROT["Secrets Manager secret rotation\n(manual/ESO triggered)"]
            NO_CREDS_IN_CODE["IRSA: No AWS credentials\nin container environments"]
        end

        subgraph K8S_SEC["Kubernetes Security"]
            HELM_NS["Namespaced Helm releases\nairflow|mlflow|jupyterhub|monitoring|sagemaker"]
            ESO["External Secrets Operator\nSecrets fetched from Secrets Manager\nNot stored in Git"]
            PRIVATE_EKS["EKS API endpoint:\nprivate (accessible from VPC only)"]
            SA_ANNOT["ServiceAccount annotations with IRSA\nNo node-level IAM role overreach"]
        end
    end
```

---

## Critical Security Gaps (Immediate Action Required)

```mermaid
graph TB
    subgraph CRITICAL["🚨 CRITICAL Gaps"]
        C1["CRITICAL: webserver_secret_key\nHardcoded: 'THIS IS UNSAFE!'\nin Airflow Helm values\nAny Airflow session can be forged"]
        C2["CRITICAL: K8s etcd secrets NOT encrypted\nAll K8s Secrets (including DB passwords)\nstored in plain base64 in etcd"]
        C3["CRITICAL: EKS control plane audit logs OFF\nNo record of who called kubectl\nwhat was deleted/created/read"]
        C4["CRITICAL: system:masters for all Developers\naws-auth ConfigMap grants developer users\ncluster-admin equivalent\nOne compromised dev = full cluster access"]
    end

    subgraph HIGH["⚠️ HIGH Risk Gaps"]
        H1["No NetworkPolicies\nAny pod can reach any pod\nCompromised pod → internal network pivot"]
        H2["No Pod Security Standards\nContainers may run as root\nPrivilege escalation possible"]
        H3["S3 state bucket: no MFA delete\nState file can be deleted\ncausing mass infrastructure destruction"]
        H4["No AWS GuardDuty\nNo real-time threat detection\nCryptomining on K8s pods = invisible"]
        H5["VPC Flow Logs disabled\nNo forensic network audit trail\nIncident response blind"]
        H6["skip_final_snapshot = true in RDS\nAccidental terraform destroy → permanent data loss"]
        H7["IAM access keys long-lived\nUser access keys in Secrets Manager\nNo automatic rotation (ESO does re-read, not rotate)"]
    end

    subgraph MEDIUM["ℹ️ MEDIUM Risk Gaps"]
        M1["No WAF on ALB\nSQL injection / XSS on Airflow/MLflow possible"]
        M2["Single NAT Gateway (AZ1)\nAvailability risk if AZ1 fails"]
        M3["No S3 access logging\nNo file-level access audit trail"]
        M4["No AlertManager configured\nNo security-event alerting from Prometheus"]
        M5["RDS: no parameter group hardening\n(slow_query_log, general_log, audit_log off)"]
        M6["JupyterHub: arbitrary code execution\nUsed as cryptomining or SSRF entrypoint"]
    end
```

---

## Network Security Architecture

```mermaid
graph TB
    subgraph VPC_LAYOUT["VPC 10.0.0.0/16 — Security Zones"]
        subgraph PUBLIC_SUBNETS["Public Subnets (10.0.0.0/20 each, 3 AZs)"]
            ALB_PUB["Application Load Balancer\n(internet-facing)\nIngress only: 443/TCP\nTerminates TLS"]
            NAT_PUB["NAT Gateway (1 per AZ in target state)\nEgress only — no inbound"]
        end

        subgraph PRIVATE_SUBNETS["Private Subnets (10.0.16.0/20 each, 3 AZs)"]
            subgraph EKS_NODES["EKS Node Groups"]
                NG0["ng0: t3.small (0-5)\nAirflow spillover"]
                NG1["ng1: t3.medium (4-6)\nBase platform pods"]
                NG2["ng2: t3.large (0-3)\nNoSchedule taint (heavy ML only)"]
            end
        end

        subgraph DB_SUBNETS["Database Subnets (isolated)"]
            RDS_PG2["RDS PostgreSQL 13.11\n(Airflow) port 5000\nSG: allow from EKS SG only"]
            RDS_MY2["RDS MySQL 8.0.33\n(MLflow) port 5432\nSG: allow from EKS SG only"]
        end
    end

    subgraph SG_RULES["Security Group Rules (Current)"]
        ALB_SG["ALB SG\nInbound: 443 from 0.0.0.0/0\nOutbound: 8080/8888/5000/3000 to EKS SG"]
        EKS_SG["EKS Node SG\nInbound: from ALB SG only\nInbound: 443 (K8s API) from VPC CIDR\nOutbound: all (for egress to AWS APIs)"]
        RDS_SG["RDS SG\nInbound: 5000/5432 from EKS SG only\nNo public access"]
    end

    INTERNET["Internet"] -->|"443 HTTPS"| ALB_PUB
    ALB_PUB -->|"HTTP path routing"| EKS_NODES
    EKS_NODES -->|"DB connections"| RDS_PG2 & RDS_MY2

    subgraph MISSING_SG["❌ Missing Network Controls"]
        NP_MISSING["NetworkPolicies (Calico/Cilium needed)\nCurrently: all pods can reach all pods\nNeeded: deny all by default + explicit allow"]
        FLOW_MISSING["VPC Flow Logs: disabled\nNeeded for forensic analysis"]
        WAF_MISSING["AWS WAF on ALB: not configured\nNeeded for OWASP Top 10 protection"]
    end
```

---

## IAM Trust Boundaries & IRSA Roles

```mermaid
graph TB
    subgraph AWS_IAM["AWS IAM — IRSA Trust Chain"]
        OIDC_EP["EKS OIDC Provider\nhttps://oidc.eks.{region}.amazonaws.com/id/{cluster_id}"]

        subgraph COMPONENT_ROLES["Component-level IAM Roles (IRSA)"]
            ROLE_MLF["mlflow-irsa-role\nTrust: K8s SA mlflow/mlflow\nPermissions: S3 GetObject/PutObject/DeleteObject\non mlflow-artifacts/* prefix only"]
            ROLE_AF["airflow-irsa-role\nTrust: K8s SA airflow/airflow\nPermissions: S3 GetObject/PutObject\non airflow-data/* prefix"]
            ROLE_SAGE["sagemaker-irsa-role\nTrust: K8s SA sagemaker/*\nPermissions: SageMaker:CreateEndpoint\nECR:GetAuthToken, S3 full on mlflow bucket"]
            ROLE_ESO["external-secrets-irsa-role\nTrust: K8s SA external-secrets/*\nPermissions: SecretsManager:GetSecretValue\non mlplatform/* prefix only"]
            ROLE_EXTDNS["external-dns-irsa-role\nTrust: K8s SA monitoring/external-dns\nPermissions: Route53 ChangeResourceRecordSets\non specific hosted zone only"]
        end

        subgraph USER_ROLES["Per-User IAM Roles"]
            DEV_ROLE["Developer IAM Role\nPermissions:\n• EKS:DescribeCluster\n• EC2: Describe*\n• S3: Full access on data bucket\n• RDS: Describe*, Connect\n• VPC: Describe*\nK8s binding: system:masters (⚠️ over-broad)"]
            USER_ROLE["User IAM Role (read-only)\nPermissions:\n• SageMaker: Describe*/List*\n• S3: GetObject on mlflow prefix\nK8s binding: none"]
        end
    end

    OIDC_EP -->|"assumeRoleWithWebIdentity"| COMPONENT_ROLES
    USER_ROLES -->|"explicit assume-role"| DEV_ROLE & USER_ROLE
```

---

## Secrets Management Architecture

```mermaid
graph TB
    subgraph SECRETS_ARCH["Secrets Flow (Current + Gaps)"]
        subgraph STORED["Where Secrets Live"]
            SM["AWS Secrets Manager\nmlplatform/ prefix\nAll platform secrets"]
        end

        subgraph ESO_FLOW["External Secrets Operator Flow"]
            CSS["ClusterSecretStore\n(uses external-secrets IRSA role)"]
            ES_MLFLOW["ExternalSecret: mlflow-secrets\nMLFLOW_TRACKING_URI\nMYSQL_USER / MYSQL_PASSWORD"]
            ES_AIRFLOW["ExternalSecret: airflow-secrets\nDB_HOST, DB_USER, DB_PASSWORD\nGITHUB_CLIENT_ID/SECRET\nwebserver_secret_key ← ⚠️ was 'THIS IS UNSAFE!'"]
            K8S_SEC["Kubernetes Secrets\n(populated by ESO)\nMounted as env vars in pods"]
        end

        subgraph GAPS_SEC["Security Gaps in Secrets"]
            G_ETCD["❌ K8s Secrets stored unencrypted in etcd\nAnyone with etcd access reads all secrets\nRemediation: EKS KMS envelope encryption"]
            G_ROTATION["❌ IAM access keys not auto-rotated\nUser access keys (Developers/Users)\nremain valid indefinitely unless manually rotated"]
            G_LOGS["❌ Secrets Manager access NOT audited\nCloudTrail not capturing GetSecretValue calls"]
        end
    end

    SM --> CSS --> ES_MLFLOW & ES_AIRFLOW --> K8S_SEC
```

---

## Container Security

```mermaid
graph TB
    subgraph CONTAINER_SEC["Container Image Security"]
        subgraph CURRENT_IMAGES["Current Images (DockerHub)"]
            I1["seblum/airflow:2.6.3-python3.11-custom-light"]
            I2["seblum/mlflow:v2.4.1"]
            I3["seblum/jupyterhub-server:latest  ← ⚠️ :latest tag = non-deterministic"]
            I4["seblum/streamlit-sagemaker-app:v1.0.0"]
            I5["seblum/vuejs-ml-dashboard:latest  ← ⚠️ :latest"]
        end

        subgraph IMAGE_RISKS["Image Security Risks"]
            R1["⚠️ Images from DockerHub\n(public registry — no SLA, can disappear)\nRemediation: Mirror to private ECR"]
            R2["⚠️ :latest tag on 2 images\nNon-deterministic — different behaviour across\ndeploys/restarts\nRemediation: Pin to digest sha256:..."]
            R3["⚠️ No image vulnerability scanning\nTrivy / Amazon ECR scanning not configured\nCritical CVEs in base images undetected"]
            R4["⚠️ No image signing (Cosign/Notary)\nImage tampering undetected"]
        end

        subgraph IMAGE_HARDENING["Recommended Hardening"]
            H_ECR["Migrate to ECR private registry\n(replicate from DockerHub)\nECR image scanning: on-push + on-schedule"]
            H_SCAN["Trivy in CI pipeline\nBlock deployment if CRITICAL CVEs"]
            H_SIGN["Cosign image signing\nVerify signature before deploy (OPA)"]
            H_SBOM["Generate SBOM (syft)\nFor compliance artifact delivery"]
        end
    end

    CURRENT_IMAGES --> IMAGE_RISKS
    IMAGE_RISKS --> IMAGE_HARDENING
```

---

## Kubernetes RBAC Analysis

```mermaid
graph TB
    subgraph K8S_RBAC["Kubernetes RBAC (Current State)"]
        subgraph CRB["ClusterRoleBindings"]
            MASTERS_BIND["system:masters group\n← Bound to all Developer IAM users\nvia aws-auth ConfigMap\n⚠️ FULL CLUSTER ADMIN for all devs"]
            CA_BIND["cluster-autoscaler SA\n← ClusterRole: describe nodes/pods\nappropriate least-privilege"]
            ESO_BIND["external-secrets SA\n← ClusterRole: manage Secrets\nappropriate for ESO function"]
        end

        subgraph REC_RBAC["Recommended RBAC Improvement"]
            NAMESPACED_ROLE["Per-team namespace roles:\nRole: team-a-developer\n• get/list/watch: pods/logs/events\n• create/delete: only in team namespace\n• NO: clusterroles, nodes, pv"]
            ADMIN_SPLIT["Platform Admin SA:\n• system:masters for Terraform only\n• Ops team: cluster-admin (MFA required)\n• Developers: namespace-scoped only"]
            AUDIT_RBAC["K8s audit policy:\nlog level=Metadata for\n• create/delete/update verbs\n• secrets access\nlog level=Request for:\n• exec/portforward (high risk)"]
        end
    end
```

---

## Security Remediation Roadmap

### Immediate (P0 — within 1 week)

| Issue | Severity | Action |
|-------|----------|--------|
| `webserver_secret_key = 'THIS IS UNSAFE!'` | CRITICAL | Rotate to random 32-char secret in Secrets Manager |
| EKS control plane audit logs | CRITICAL | `aws eks update-cluster-config --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'` |
| etcd secret encryption | CRITICAL | Enable KMS envelope encryption on EKS cluster |
| `system:masters` for all developers | CRITICAL | Create namespace-scoped Roles; reserve system:masters for Terraform SA only |
| `skip_final_snapshot = true` | HIGH | Change to `false`; set `final_snapshot_identifier` |

### Short-term (P1 — within 1 month)

| Issue | Severity | Action |
|-------|----------|--------|
| NetworkPolicies | HIGH | Deploy Calico; add deny-all + allow-same-namespace policies |
| VPC Flow Logs | HIGH | Enable on all VPC subnets → CloudWatch Logs |
| GuardDuty | HIGH | Enable GuardDuty + EKS protection in account settings |
| S3 state bucket MFA delete | HIGH | Enable MFA delete on `mlplatform-terraform-state` |
| Pod Security Standards | HIGH | Apply `Restricted` profile on all non-system namespaces |
| IAM access key rotation | MEDIUM | Implement Lambda rotation in Secrets Manager for user keys |
| S3 access logging | MEDIUM | Enable access logging on both S3 buckets |
| Docker :latest tags | MEDIUM | Pin `jupyterhub-server` and `vuejs-ml-dashboard` to digests |

### Medium-term (P2 — within 1 quarter)

| Issue | Severity | Action |
|-------|----------|--------|
| AWS WAF on ALB | MEDIUM | Enable managed rule groups (OWASP Top 10) |
| Image scanning (ECR + Trivy) | MEDIUM | Mirror images to ECR; add Trivy to GitHub Actions |
| AWS Security Hub CIS baseline | MEDIUM | Enable Security Hub; achieve CIS Level 1 compliance |
| Secrets Manager CloudTrail | MEDIUM | Enable CloudTrail data events for Secrets Manager API |
| RDS audit logging | LOW | Enable `general_log`, `slow_query_log` via Parameter Group |
| Multi-AZ NAT gateway | LOW | Add NAT GW in AZ2 and AZ3 |
