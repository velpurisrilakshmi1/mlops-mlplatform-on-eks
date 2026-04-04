# Enterprise Scaling Challenges

> **Audience**: Platform engineers, architects, CTOs — engineering leaders at large organizations like Amazon  
> **Purpose**: Identify where this platform hits scaling walls when growing from a POC for one team to a production platform serving hundreds of teams and thousands of users

---

## Executive Summary

This platform was designed as a single-team MLOps environment. At Amazon-scale — where you might have:
- **500+ ML teams** across different orgs and business units
- **5,000+ data scientists and engineers**
- **100,000+ Airflow DAG runs per day**
- **Multi-region redundancy requirements**
- **SOC2 Type II / ISO 27001 compliance mandates**
- **$50M+ annual cloud spend requiring rigorous FinOps governance**

— you need fundamentally different architecture decisions in 7 key areas.

---

## Challenge 1: Multi-Team Namespace Isolation & Quotas

### Current State

```mermaid
graph TB
    subgraph CURRENT["Current Architecture — Single Shared Namespace per Tool"]
        AF_NS["namespace: airflow\nAll teams share one Airflow"]
        MLF_NS["namespace: mlflow\nAll teams share one MLflow"]
        JHB_NS["namespace: jupyterhub\nAll teams share one JupyterHub"]
        
        TEAM_A_USER["Team A User\nFull access to all DAGs/runs"]
        TEAM_B_USER["Team B User\nCan see Team A's experiments!"]
        
        NO_NP["❌ No NetworkPolicies\nAll pods can reach all pods"]
        NO_QUOTA["❌ No ResourceQuotas\nOne team can consume all cluster resources"]
        NO_RBAC["❌ No per-team K8s RBAC\nOnly GitHub team OAuth"]
    end
```

**Gaps**:
- No data isolation: Team A can query Team B's MLflow experiments
- No resource fairness: one burst training job blocks other teams
- No blast radius containment: a bad DAG can crash the shared Airflow

### Recommended Solution (Amazon Scale)

```mermaid
graph TB
    subgraph RECOMMENDED["Recommended — Virtual Clusters + Namespace-per-Team"]
        subgraph CTRL["Control Plane Cluster"]
            PLATFORM_SVC["Shared Platform Services\n• Centralized MLflow Registry (read-only)\n• ExternalDNS, Cert-Manager\n• CrossPlane / ACK for team provisioning"]
        end

        subgraph TEAM_A_CLUSTER["vCluster: team-a (or namespace group)"]
            A_AF["airflow namespace\n(team-a)\nResourceQuota: 40 CPU, 80Gi RAM\nDAGs: team-a/* only"]
            A_MLF["mlflow namespace\n(team-a)\nExperiments isolated by team prefix"]
            A_JHB["jupyterhub namespace\n(team-a)\nOnly team-a GitHub members"]
            A_NP["NetworkPolicy:\nAllow: within team namespaces\nDeny: cross-team pod comms"]
            A_QUOTA["ResourceQuota + LimitRange:\nCPU/RAM/PVC limits per namespace\nPriorityClass per workload tier"]
        end

        subgraph TEAM_B_CLUSTER["vCluster: team-b"]
            B_SAME["Same structure for team-b\n(same Helm charts, different values)"]
        end

        subgraph TEAM_N["... team-n (GitOps provisioned)"]
            N_SAME["New team on-boarded via\nGit PR to platform repo\nCrossPlane/Argo CD auto-provisions"]
        end
    end

    CTRL --> TEAM_A_CLUSTER & TEAM_B_CLUSTER & TEAM_N
```

**Implementation Steps**:
1. Deploy [vcluster](https://www.vcluster.com/) or use Namespace groups per team
2. Add `ResourceQuota` and `LimitRange` per namespace:
   ```yaml
   apiVersion: v1
   kind: ResourceQuota
   metadata:
     name: team-a-quota
     namespace: airflow-team-a
   spec:
     hard:
       requests.cpu: "40"
       requests.memory: 80Gi
       limits.cpu: "80"
       limits.memory: 160Gi
       persistentvolumeclaims: "20"
       pods: "200"
   ```
3. Add `NetworkPolicy` to deny cross-namespace traffic by default
4. Use `PriorityClass` for critical vs. batch workloads
5. GitOps (Argo CD) + CrossPlane for automated team provisioning from a Git PR

---

## Challenge 2: Hundreds/Thousands of Users — IAM & OAuth Scaling

### Current State

```mermaid
graph TB
    subgraph CURRENT_IAM["Current Architecture — Per-User IAM Resources"]
        TF_LOOP["Terraform for_each loop\nover user-list.yaml"]
        TF_LOOP -->|"× N users"| IAM_USER["aws_iam_user (×N)"]
        TF_LOOP -->|"× N users"| IAM_KEYS["aws_iam_access_key (×N)"]
        TF_LOOP -->|"× N users"| IAM_ROLE["aws_iam_role (×N)"]
        TF_LOOP -->|"× N users"| SM_SECRET["Secrets Manager\nsecret (×N)"]

        LIMIT1["❌ AWS IAM limit:\n5,000 IAM users per account"]
        LIMIT2["❌ All users in one YAML file\nTerraform state grows unbounded\nApply time: O(N²) as N→5000"]
        LIMIT3["❌ Manual GitHub team\nmembership management"]
        LIMIT4["❌ Hard-coded GitHub org\nin WebServerConfig.py\nCannot support multiple orgs"]
    end
```

**Gaps at 5,000+ users**:
- IAM user limit (5,000) hit per AWS account → need multiple accounts
- `terraform apply` on 5,000-user YAML is slow and risky
- GitHub OAuth doesn't scale to 3rd party identity providers (LDAP, SAML)
- Single GitHub org hard-coded in Airflow config

### Recommended Solution (Amazon Scale)

```mermaid
graph TB
    subgraph IDP["Identity Layer (Centralized)"]
        OKTA["Okta / PingFederate / AWS IAM Identity Center\n(SAML 2.0 / OIDC)"]
        GROUPS["Group-based access control\nTeam membership managed in IdP"]
    end

    subgraph PLATFORM_AUTH["Platform Authentication"]
        DEXIDP["Dex IDP\n(Kubernetes native OIDC broker)\nTranslates: Okta → OIDC for K8s/Airflow/JupyterHub/Grafana"]
        OAUTH2P["OAuth2 Proxy\n(sidecar for apps that don't support OIDC natively)"]
    end

    subgraph IAM_STRATEGY["AWS IAM Strategy at Scale"]
        PERMISSION_SETS["IAM Identity Center\nPermission Sets (not individual IAM users)\n• ML-Developer set\n• ML-User set\n• ML-Admin set"]
        AWS_ACCOUNTS["Multi-Account Strategy\n• dev account (sandbox)\n• staging account\n• prod account per BU"]
        IRSA_GROUPS["Group-level IRSA\n(not per-user)\nTeam SA → team IAM role"]
    end

    OKTA --> DEXIDP --> PLATFORM_AUTH
    PLATFORM_AUTH --> AIRFLOW_AUTH["Airflow: GenericOIDCAuthenticator\nvs. current GitHub-only"]
    PLATFORM_AUTH --> JHB_AUTH["JupyterHub: LDAPAuthenticator or OIDCAuthenticator"]
    PERMISSION_SETS --> AWS_ACCOUNTS
    AWS_ACCOUNTS --> IRSA_GROUPS

    style IDP fill:#e3f2fd
    style PLATFORM_AUTH fill:#e8f5e9
    style IAM_STRATEGY fill:#fff3e0
```

**Key Changes**:
1. Replace `aws_iam_user` per person with **IAM Identity Center Permission Sets** per role
2. Replace GitHub OAuth with **Dex IDP** (proxies Okta/SAML) for all apps
3. Replace `user-list.yaml` manual management with **SCIM provisioning** from Okta
4. Use **multi-account AWS Organizations** (one account per team/BU for blast radius)
5. Role-based IRSA instead of user-based

---

## Challenge 3: Cost Governance Per Team

### Current State

```mermaid
graph TB
    subgraph CURRENT_COST["Current Cost Architecture — No Visibility"]
        SINGLE_ACCT["Single AWS Account\nAll teams share resources"]
        NO_TAGGING["❌ No consistent resource tagging\nby team or project"]
        NO_BUDGETS["❌ No AWS Budgets per team\nNo spending alerts"]
        NO_SHOWBACK["❌ No chargeback/showback\nFinance can't attribute costs"]
        SPOT_NONE["❌ No Spot instances\nt3.medium On-Demand only\n~$0.0376/hr × 4 always-on"]
        IDLE_NODES["❌ 4× t3.medium always running\neven if 0 ML jobs active"]
    end
```

**Annual cost estimate** (current): 4× `t3.medium` ($0.0376/hr) × 8,760hrs = **~$1,317/year base** just for the always-on nodes. At Amazon scale with 100 teams each with their own cluster, this becomes $131,700/year in idle compute.

### Recommended Solution (Amazon Scale)

```mermaid
graph TB
    subgraph COST_ARCH["Cost Governance Architecture"]
        subgraph TAGGING["Resource Tagging Strategy"]
            TAGS["Mandatory tags on all resources:\nteam: {team-name}\nproject: {project-name}\ncost-center: {code}\nenvironment: dev|staging|prod\ncomponent: airflow|mlflow|training|serving"]
        end

        subgraph BUDGETS["AWS Budgets + Cost Allocation"]
            B1["AWS Budget per team account:\n• Monthly alert at 80% → email\n• Monthly alert at 100% → PagerDuty\n• Anomaly detection (ML-based)"]
            B2["AWS Cost Explorer tags\nFilter by team= tag\nShowback reports to team leads monthly"]
            B3["Kubecost / OpenCost\n(in-cluster cost attribution)\nLabel-based K8s cost visibility"]
        end

        subgraph COMPUTE_OPT["Compute Optimisation"]
            SPOT["Spot Instance Node Groups\n• Airflow task pods: 70% Spot\n• JupyterHub servers: 50% Spot\n• Training pods: 90% Spot\n• Karpenter for smart provisioning"]
            KARP["Karpenter\n(replaces Cluster Autoscaler)\n• Consolidation: bin-packs pods, removes idle nodes\n• Spot fallback to On-Demand\n• Scale-to-zero when idle"]
            SCHED["Scheduled Scaling\n• Scale ng1 down to 0 at night/weekends\n• CronJob in K8s for predictable off-hours"]
        end

        subgraph STORAGE_OPT["Storage Optimisation"]
            S3_LC["S3 Lifecycle Policies:\n• 30d → S3-IA (infrequent access)\n• 90d → S3 Glacier\n• 365d → Delete (configurable per team)"]
            EFS_OPT["EFS intelligent tiering:\n• Access pattern analysis\n• Auto-move cold files to IA tier"]
        end
    end

    TAGGING --> BUDGETS
    COMPUTE_OPT --> STORAGE_OPT

    style TAGGING fill:#e8f5e9
    style BUDGETS fill:#e3f2fd
    style COMPUTE_OPT fill:#fff3e0
    style STORAGE_OPT fill:#fce4ec
```

**Cost Reduction Levers**:

| Lever | Current | Optimized | Savings |
|-------|---------|-----------|---------|
| Node type | t3.medium On-Demand | Spot + Karpenter | 60–70% |
| Idle nodes | 4 base, always on | Scale-to-zero w/ Karpenter | 40–80% off-hours |
| S3 storage class | Standard | Lifecycle → IA/Glacier | 40–60% |
| RDS | db.t3.micro always-on | Stop during off-hours (non-prod) | 50% non-prod |
| EFS | Standard | Intelligent tiering | 20–30% |

---

## Challenge 4: Multi-Region / Multi-Cluster Federation

### Current State

```mermaid
graph TB
    subgraph CURRENT_REGION["Current — Single Region, Single Cluster"]
        SINGLE["eu-central-1\nSingle AZ NAT Gateway\n(SPOF for egress)\nSingle EKS cluster"]
        LIMIT5["❌ No DR/failover strategy"]
        LIMIT6["❌ Single NAT Gateway (AZ1 only)\nEgress SPOF if AZ1 fails"]
        LIMIT7["❌ RDS: skip_final_snapshot=true\nData loss on terraform destroy"]
        LIMIT8["❌ No cross-region artifact replication"]
    end
```

### Recommended Solution (Amazon Scale)

```mermaid
graph TB
    subgraph GLOBAL_ARCH["Global Multi-Cluster Architecture"]
        subgraph PRIMARY["Primary Region: us-east-1"]
            EKS_P["EKS Cluster (production)\n3 AZs\n3 NAT Gateways (1 per AZ)"]
            RDS_P["RDS Multi-AZ\nAuto failover < 60s\nfinal_snapshot_identifier set"]
            S3_P["S3 Primary Bucket\nCross-region replication enabled"]
        end

        subgraph SECONDARY["DR Region: eu-west-1"]
            EKS_S["EKS Cluster (standby/DR)\nWarm standby or active-active"]
            RDS_S["RDS Read Replica → promote on failover"]
            S3_S["S3 Replica Bucket\nRPO: seconds (S3 replication)"]
        end

        subgraph REGIONAL["Regional Clusters (per geo)"]
            EKS_APAC["APAC Cluster: ap-southeast-1\n(teams in Asia-Pacific)"]
            EKS_EU["EU Cluster: eu-central-1\n(GDPR-constrained data)"]
        end

        subgraph FEDERATION["Cluster Federation Layer"]
            ARGO_CD["Argo CD Hub\n(manage all clusters from single pane)\nApplicationSets for cross-cluster deploy"]
            MLF_CENTRAL["Centralized MLflow Registry\n(Aurora Global Database)\nPrimary in us-east-1\nReplicas in all regions"]
            R53_GEO["Route 53 Geolocation Routing\n• /jupyterhub → nearest cluster\n• /mlflow → primary (read-writes)\n• /airflow → team's cluster"]
        end
    end

    PRIMARY <-->|"S3 CRR"| SECONDARY
    PRIMARY <-->|"RDS replication"| SECONDARY
    ARGO_CD --> EKS_P & EKS_S & EKS_APAC & EKS_EU
    MLF_CENTRAL --> EKS_P & EKS_S & EKS_APAC & EKS_EU
    R53_GEO --> PRIMARY & REGIONAL

    style PRIMARY fill:#e8f5e9
    style SECONDARY fill:#fff3e0
    style FEDERATION fill:#e3f2fd
```

**Key RTO/RPO Targets**:

| Component | Current RTO | Target RTO | Approach |
|-----------|-------------|-----------|----------|
| Airflow (metadata) | Hours (rebuild) | 15 min | RDS Multi-AZ + warm standby |
| MLflow (experiments) | Hours | 5 min | Aurora Global DB + replica promotion |
| S3 artifacts | N/A (durable) | Seconds | S3 Cross-Region Replication |
| EKS cluster | Hours | 30 min | GitOps + bootstrap script |
| DNS | Minutes | < 1 min | Route 53 health checks + failover |

---

## Challenge 5: Data Lake Governance (S3 Access Controls)

### Current State

```mermaid
graph TB
    subgraph CURRENT_DL["Current Data Access — Minimal Governance"]
        TWO_BUCKETS["Only 2 S3 Buckets:\n• mlflow-mlflow (artifacts)\n• airflow-data-storage (pipeline data)"]
        COARSE_ACCESS["Airflow SA → Full S3 access on data bucket\n❌ No path-based prefix restrictions\n❌ No dataset-level access control\n❌ No data classification tags"]
        NO_CATALOG["❌ No data catalog (Glue/Lake Formation)\n❌ No schema registry\n❌ No column-level security (PII masking)"]
        NO_AUDIT["❌ No S3 access logging\n❌ No CloudTrail S3 data events\n❌ No data lineage tracking"]
    end
```

### Recommended Solution (Amazon Scale)

```mermaid
graph TB
    subgraph DL_ARCH["Data Lake Governance Architecture"]
        subgraph ZONES["Data Lake Zones (S3)"]
            RAW["s3://mlplatform-raw/\nteam-a/project-x/\nteam-b/project-y/\nRetention: 90d"]
            CURATED["s3://mlplatform-curated/\nCleaned, validated data\nRetention: 1 year"]
            FEATURES["s3://mlplatform-features/\nFeature store outputs\nRetention: per-feature config"]
            ARTIFACTS["s3://mlplatform-artifacts/\nMLflow models and artifacts\nRetention: per-model lifecycle"]
        end

        subgraph ACCESS_CTRL["AWS Lake Formation Governance"]
            LF["AWS Lake Formation\n• Database and table-level permissions\n• Column-level security (PII masking)\n• Row-level filtering\n• Cross-account access grants"]
            GLUE["AWS Glue Data Catalog\n• Schema registry\n• Table definitions\n• Column metadata + tags"]
            LF_TAGS["LF-Tags on columns:\npii: true/false\nclassification: public/internal/confidential\nretention: 30d/90d/1y/indefinite"]
        end

        subgraph LINEAGE["Data Lineage"]
            MARQUEZ["OpenLineage / Marquez\n• Integrates with Airflow (OpenLineage provider)\n• Tracks dataset → job → dataset\n• Visualize data provenance"]
        end

        subgraph AUDIT["Audit + Compliance"]
            CT["CloudTrail S3 Data Events\n• Log every GetObject/PutObject\n• Retain 7 years (SOX/SOC2)"]
            S3_LOG["S3 Server Access Logging\n→ CloudWatch Logs\n→ Athena queries for access reports"]
            SF["AWS Macie\n• PII detection in S3\n• Auto-classify sensitive data\n• Alert on exposure"]
        end
    end

    RAW -->|"Glue ETL jobs"| CURATED
    CURATED -->|"Feature engineering pipeline"| FEATURES
    CURATED & FEATURES -->|"Training data"| AIRFLOW_JOBS["Airflow ML Jobs"]
    AIRFLOW_JOBS -->|"Lineage events"| MARQUEZ
    LF --> RAW & CURATED & FEATURES & ARTIFACTS
    GLUE --> LF
    CT --> S3_LOG
    SF --> CT

    style ZONES fill:#e8f5e9
    style ACCESS_CTRL fill:#e3f2fd
    style LINEAGE fill:#fff3e0
    style AUDIT fill:#fce4ec
```

---

## Challenge 6: Compliance & Audit Logging (SOC2 / ISO 27001)

### Current State — Missing Controls

```mermaid
graph TB
    subgraph GAPS["Current Compliance Gaps"]
        G1["❌ EKS control plane audit logs DISABLED\n(default: off)\nSecurity events not captured"]
        G2["❌ No VPC Flow Logs\nNo network traffic audit trail"]
        G3["❌ No CloudTrail for all API calls\nIAM, EKS, S3 events not centralized"]
        G4["❌ RDS: skip_final_snapshot=true\nData destruction risk on terraform destroy"]
        G5["❌ S3 state bucket: no MFA delete\nState files can be accidentally deleted"]
        G6["❌ Secrets in K8s etcd not encrypted\n(requires EKS secret envelope encryption)"]
        G7["❌ No Pod Security Standards\nContainers can run as root\nPrivileged containers allowed"]
        G8["❌ Airflow webserver_secret = 'THIS IS UNSAFE!'\nHardcoded insecure default"]
        G9["❌ No centralized log aggregation\nLogs lost when pods are deleted"]
        G10["❌ No intrusion detection\n(GuardDuty not enabled)"]
    end
```

### Recommended Solution (Amazon Scale — SOC2 Type II Ready)

```mermaid
graph TB
    subgraph COMPLIANCE_ARCH["Compliance Architecture"]
        subgraph LOGGING["Centralised Logging (ELK / OpenSearch)"]
            FB["Fluent Bit DaemonSet\n(all namespaces)\nForward container logs"]
            CW["CloudWatch Logs\n• /eks/cluster/audit → audit logs\n• /eks/cluster/api → API server\n• VPC Flow Logs\n• RDS error/slow query logs\nRetention: 7 years (configurable)"]
            OS["Amazon OpenSearch\n(optional: enhanced search)\nKibana dashboards for log analysis"]
            FB --> CW --> OS
        end

        subgraph AUDIT_TRAIL["Audit Trail"]
            CT2["CloudTrail (organisation-wide)\n• All regions\n• Management + data events\n• S3 destination (immutable)\n• SNS alerts on sensitive API calls"]
            CONFIG["AWS Config Rules\n• eks-cluster-logging-enabled\n• s3-bucket-ssl-requests-only\n• rds-snapshot-backup-enabled\n• iam-no-inline-policy-check\n• restricted-ssh (SG rules)"]
            GUARD["Amazon GuardDuty\n• Threat detection (crypto mining, exfil)\n• EKS audit log analysis\n• S3 malicious activity\n• Findings → Security Hub"]
            MACIE["Amazon Macie\n• PII detection in S3\n• Data classification"]
            SECHUB["AWS Security Hub\n• Aggregated security findings\n• CIS Benchmark checks\n• SOC2 control mapping"]
        end

        subgraph POD_SECURITY["Pod Security"]
            PSS["Pod Security Standards (Restricted)\nfor all non-system namespaces:\n• runAsNonRoot: true\n• allowPrivilegeEscalation: false\n• readOnlyRootFilesystem: true\n• drop ALL capabilities"]
            OPA["OPA Gatekeeper\nAdmission controller policies:\n• Require resource limits\n• Require team= label\n• Block privileged containers\n• Require image digest (not :latest)"]
        end

        subgraph ENCRYPT["Encryption at Rest + Transit"]
            KMS["AWS KMS\n• EKS secrets envelope encryption\n• RDS encryption CMK\n• S3 SSE-KMS (not SSE-S3)\n• Secrets Manager auto-rotation"]
            TLS["TLS everywhere:\n• cert-manager for internal certs\n• ACM for ALB\n• mTLS between services (Istio/Linkerd — optional)"]
        end
    end

    LOGGING --> AUDIT_TRAIL
    POD_SECURITY --> COMPLIANCE_ARCH
    ENCRYPT --> COMPLIANCE_ARCH

    style LOGGING fill:#e8f5e9
    style AUDIT_TRAIL fill:#e3f2fd
    style POD_SECURITY fill:#fff3e0
    style ENCRYPT fill:#fce4ec
```

**SOC2 Control Mapping**:

| SOC2 Control | Current Status | Recommended Action |
|-------------|---------------|-------------------|
| CC6.1 (Logical access) | ⚠️ Partial (GitHub OAuth) | Add SAML SSO + MFA enforcement |
| CC6.2 (New access provisioning) | ⚠️ Manual (user-list.yaml) | SCIM auto-provisioning |
| CC6.3 (Access removal) | ⚠️ Manual (terraform taint) | Auto-deprovisioning on IdP offboard |
| CC7.1 (Change detection) | ❌ Missing | Enable AWS Config + CloudTrail |
| CC7.2 (Intrusion detection) | ❌ Missing | GuardDuty + Security Hub |
| CC8.1 (Change management) | ⚠️ IaC only | Add PR review + manual approval gates |
| A1.1 (Availability) | ❌ Single AZ NAT | Multi-AZ NAT + Cross-Region DR |
| C1.1 (Confidentiality) | ❌ Missing | KMS encryption + Macie + Lake Formation |

---

## Challenge 7: Platform Self-Service & GitOps Automation

### Current State — Manual Everything

```mermaid
graph TB
    subgraph CURRENT_OPS["Current Operations — All Manual"]
        NEW_TEAM["New team onboarding:\n1. Admin manually edits user-list.yaml\n2. Runs terraform apply\n3. Creates GitHub team (manual)\n4. Shares credentials manually\n→ Hours per team"]
        NEW_COMP["New component deploy:\n1. Admin manually edits .tfvars\n2. Runs terraform apply\n3. Tests manually\n→ Only infra team can do this"]
        DAG_DEP["DAG deployment:\n1. Engineer pushes to git-sync repo\n2. Airflow picks up in 60 seconds\n→ OK but no preview/testing"]
        NO_GITOPS["❌ No GitOps\n❌ No automated PR → deploy pipeline\n❌ No automated testing (Terratest exists but not wired)\n❌ No drift detection"]
    end
```

### Recommended Solution (Amazon Scale — Full Self-Service)

```mermaid
graph TB
    subgraph SELF_SERVICE["Self-Service Platform Architecture"]
        subgraph PORTAL["Team Onboarding Portal"]
            BACKSTAGE["Backstage.io (developer portal)\n• Team registration form\n• Auto-creates GitHub team\n• Triggers Terraform via API\n• Generates access credentials\n• Documenation in one place"]
        end

        subgraph GITOPS["GitOps — Argo CD"]
            ARGOCD["Argo CD\n• Watches platform-config Git repo\n• Auto-deploys Helm chart changes\n• Drift detection + auto-remediation\n• Multi-cluster deployment from single repo"]
            APP_SETS["ApplicationSets\n• One template → N team deployments\n• Matrix generator: teams × environments\n• Automatic on new team yaml added to repo"]
        end

        subgraph IDP_PLATFORM["Internal Developer Platform (IDP)"]
            CROSSPLANE["CrossPlane\n• K8s-native cloud resource provisioning\n• XRDs: MLTeam, MLProject, MLPipeline CRDs\n• Teams create K8s objects → cloud resources auto-created"]
            COMPOSITES["Composite Resources (XRDs)\napiVersion: mlplatform.io/v1\nkind: MLTeam\nspec:\n  name: team-a\n  size: medium        # maps to node quotas\n  region: us-east-1\n  adminGitHubTeam: team-a-engineers"]
        end

        subgraph CI_CD["CI/CD for Platform Changes"]
            GH_ACTIONS["GitHub Actions\n• PR checks: terraform fmt, validate, plan\n• Auto-comment: plan output on PR\n• Required reviewers for prod apply\n• atlantis for Terraform plan-on-PR"]
            ATLANTIS["Atlantis\n• PR-triggered terraform plan\n• Comment-triggered terraform apply\n• Per-workspace locking\n• Full audit log on PR"]
            TERRATEST["Terratest (existing)\n• Unit tests for each module\n• Integration tests: deploy → validate → destroy\n• Run on every PR to module"]
        end
    end

    BACKSTAGE --> CROSSPLANE
    CROSSPLANE --> ARGOCD --> APP_SETS
    GH_ACTIONS --> ATLANTIS
    ATLANTIS --> TERRATEST

    style PORTAL fill:#e3f2fd
    style GITOPS fill:#e8f5e9
    style IDP_PLATFORM fill:#fff3e0
    style CI_CD fill:#fce4ec
```

**Team Onboarding: Current vs. Target**:

| Step | Current (Manual) | Target (Self-Service) | Time |
|------|-----------------|----------------------|------|
| Request access | Email Platform team | Fill Backstage form | 2 min |
| Create GitHub team | Admin logs in | SCIM auto-creates | Instant |
| Provision AWS resources | `terraform apply` by admin | CrossPlane reconcile | 5 min |
| Airflow namespace | Shared (no isolation) | Separate namespace via Argo CD | 5 min |
| Issue credentials | Admin emails | Secrets Manager → user's vault | Instant |
| **Total time** | **Hours–Days** | **~10 minutes** | |

---

## Summary: Scaling Roadmap

```mermaid
gantt
    title Platform Scaling Roadmap
    dateFormat YYYY-Q[Q]
    
    section Quick Wins (Q1)
    NetworkPolicies per namespace         :active, q1a, 2026-Q1, 2026-Q2
    ResourceQuotas + LimitRanges          :q1b, 2026-Q1, 2026-Q2
    CloudTrail + VPC Flow Logs            :q1c, 2026-Q1, 2026-Q2
    Spot instances + Karpenter            :q1d, 2026-Q1, 2026-Q2
    AlertManager enable                   :q1e, 2026-Q1, 2026-Q1

    section Medium-term (Q2-Q3)
    Multi-account AWS Organizations       :q2a, 2026-Q2, 2026-Q3
    IAM Identity Center + SAML SSO        :q2b, 2026-Q2, 2026-Q3
    Argo CD GitOps                        :q2c, 2026-Q2, 2026-Q3
    Kubecost cost attribution             :q2d, 2026-Q2, 2026-Q3
    EKS control plane audit logging       :q2e, 2026-Q2, 2026-Q2
    GuardDuty + Security Hub              :q2f, 2026-Q2, 2026-Q3
    S3 Lifecycle Policies                 :q2g, 2026-Q2, 2026-Q2

    section Strategic (Q4+)
    Multi-region cluster federation       :q3a, 2026-Q4, 2027-Q1
    CrossPlane team self-service          :q3b, 2026-Q4, 2027-Q1
    Backstage developer portal            :q3c, 2026-Q4, 2027-Q2
    Lake Formation data governance        :q3d, 2026-Q4, 2027-Q2
    OpenLineage data lineage              :q3e, 2027-Q1, 2027-Q2
    SOC2 Type II audit readiness          :q3f, 2027-Q1, 2027-Q3
```
