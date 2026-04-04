"""
MLOps Platform on EKS -- Mermaid Diagram Suite

Generates a clean, tabbed HTML page with 7 focused architecture and workflow
diagrams. Each diagram is scoped to one concern so it stays readable.

Usage:
    python mermaid_diagrams.py
    # Opens platform_diagrams.html in your browser
"""

import html
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Diagram definitions
# Each entry: id, tab label, title, subtitle, mermaid diagram text
# ---------------------------------------------------------------------------
DIAGRAMS = [
    # ── 1. Platform overview ─────────────────────────────────────────────────
    {
        "id": "overview",
        "tab": "Platform Overview",
        "title": "Platform Services Map",
        "subtitle": (
            "All platform services, their public access paths, backing data stores, "
            "and key data flows — the complete picture on one page."
        ),
        "mermaid": """\
flowchart TD
    User(["User / Data Scientist"])

    subgraph edge [" AWS Edge "]
        R53["Route 53  |  DNS"]
        ACM["ACM Certificate  |  TLS"]
        ALB["Application Load Balancer\nPath-based routing to all apps"]
        GH["GitHub OAuth\nSSO for every platform UI"]
    end

    subgraph eks [" EKS Cluster 1.24  —  Private API Endpoint "]
        subgraph apps [" Platform Applications "]
            AF["Airflow 2.6.3\nWorkflow orchestration"]
            ML["MLflow 2.4.1\nExperiment tracking + Model Registry"]
            JH["JupyterHub 2.0\nManaged notebook environment"]
            GF["Grafana 9.5.5\nDashboards and alerting"]
            SD["SageMaker Dashboard\nModel deployment UI"]
        end
        subgraph ops [" Cluster Operators "]
            PROM["Prometheus\nMetrics store  15-day retention"]
            ESO["External Secrets Operator\nAWS Secrets Manager sync"]
            CA["Cluster Autoscaler\nNode group scaling"]
        end
        subgraph ngs [" Node Groups "]
            ng0["ng0  t3.small  0-5 nodes\nSpillover"]
            ng1["ng1  t3.medium  4-6 nodes\nBase platform — always on"]
            ng2["ng2  t3.large  0-3 nodes\nHeavy ML — NoSchedule taint"]
        end
    end

    subgraph storage [" AWS Storage & Data "]
        S3["S3\nmlflow-artifacts  |  airflow-data"]
        RDS["RDS\nPostgreSQL — Airflow metadata\nMySQL — MLflow backend"]
        EFS["EFS  |  ReadWriteMany\nPersistent notebook storage"]
        ECR["ECR\nContainer image registry"]
        SEC["Secrets Manager\nmlplatform/* secrets"]
    end

    User --> R53 --> ALB
    ACM -.->|"TLS"| ALB
    GH -.->|"OAuth2 — all UIs"| ALB

    ALB -->|"/airflow"| AF
    ALB -->|"/mlflow"| ML
    ALB -->|"/jupyterhub"| JH
    ALB -->|"/grafana"| GF
    ALB -->|"/sagemaker"| SD

    AF -->|"metadata"| RDS
    AF -->|"data I/O"| S3
    AF -->|"tracking API"| ML
    AF -->|"task pods"| ng1 & ng2
    ML -->|"metadata"| RDS
    ML -->|"artifacts"| S3
    JH -->|"notebooks"| EFS
    SD -->|"model files"| S3
    SD -->|"images"| ECR
    ESO -->|"GetSecretValue"| SEC
    ESO -.->|"inject secrets"| AF & ML & JH
    GF -->|"PromQL"| PROM
    PROM -.->|"scrapes /metrics"| AF & ML & JH
    CA -->|"autoscales"| ng0 & ng1 & ng2
""",
    },

    # ── 2. ML training pipeline ──────────────────────────────────────────────
    {
        "id": "training",
        "tab": "ML Training Pipeline",
        "title": "ML Training Pipeline",
        "subtitle": (
            "Step-by-step flow when a data scientist triggers an Airflow training DAG — "
            "from code sync to model artifacts stored in S3."
        ),
        "mermaid": """\
sequenceDiagram
    actor DS as Data Scientist
    participant AW as Airflow Webserver
    participant GS as git-sync sidecar
    participant GH as GitHub DAG Repo
    participant SCH as Airflow Scheduler
    participant POD as Task Pod  (ng1 / ng2)
    participant MLF as MLflow Server
    participant RDS_PG as RDS PostgreSQL
    participant RDS_MY as RDS MySQL
    participant S3 as S3: mlflow-artifacts

    loop Every 60 seconds
        GS->>GH: git pull
        GH-->>GS: Latest DAG code
    end

    DS->>AW: Trigger DAG run via Airflow UI
    AW->>SCH: RPC — schedule DAG execution
    SCH->>RDS_PG: Write dag_run record  (Airflow metadata DB)

    SCH->>POD: KubernetesExecutor — spawn task pod on ng1 or ng2

    Note over POD: Training code executes inside pod

    POD->>MLF: mlflow.start_run()
    POD->>MLF: log_metric() / log_param() / log_model()
    MLF->>RDS_MY: Persist run metadata
    MLF->>S3: Upload model artifacts

    POD-->>SCH: Task complete  (exit 0)
    SCH->>RDS_PG: Update task instance state to SUCCESS

    DS->>AW: View DAG run status
    DS->>MLF: Compare experiment runs in MLflow UI
""",
    },

    # ── 3. Model deployment ──────────────────────────────────────────────────
    {
        "id": "deployment",
        "tab": "Model Deployment",
        "title": "Model Deployment Flow",
        "subtitle": (
            "How a trained model moves from the MLflow Registry through the "
            "SageMaker Dashboard to a live inference endpoint."
        ),
        "mermaid": """\
flowchart LR
    subgraph step1 [" 1 — Track & Register "]
        direction TB
        EXP["MLflow Experiment\nRun logged during training"]
        REG["MLflow Registry\nModel version registered"]
        EXP -->|"promote best run"| REG
    end

    subgraph step2 [" 2 — Build Container "]
        direction TB
        DASH["SageMaker Dashboard\nSelect model from Registry"]
        S3["S3: mlflow-artifacts\nModel files & weights"]
        BUILD["Build serving container\nfrom model + base image"]
        ECR["ECR\nPush container image"]
        DASH -->|"read artifacts"| S3
        S3 --> BUILD
        BUILD --> ECR
    end

    subgraph step3 [" 3 — Deploy Endpoint "]
        direction TB
        ENDPT["SageMaker Endpoint\nReal-time inference"]
        SCALE["Auto Scaling policy\nTarget tracking"]
        ENDPT --> SCALE
    end

    subgraph step4 [" 4 — Consume "]
        direction TB
        APP["Application\nor API consumer"]
        CW["CloudWatch\nLatency & invocation metrics"]
    end

    REG -->|"select version"| DASH
    ECR -->|"deploy image"| ENDPT
    ENDPT -->|"REST predictions"| APP
    ENDPT -->|"metrics"| CW
""",
    },

    # ── 4. Notebook session ──────────────────────────────────────────────────
    {
        "id": "notebook",
        "tab": "Notebook Session",
        "title": "Notebook Session — User Journey",
        "subtitle": (
            "Complete flow from login through GitHub OAuth to an active JupyterHub "
            "notebook with persistent EFS storage and MLflow experiment tracking."
        ),
        "mermaid": """\
sequenceDiagram
    actor DS as Data Scientist
    participant ALB as ALB  /jupyterhub
    participant GH as GitHub OAuth
    participant HUB as JupyterHub Hub
    participant POD as Notebook Pod  (ng1)
    participant EFS as EFS Volume
    participant MLF as MLflow Server
    participant S3 as S3: mlflow-artifacts

    DS->>ALB: GET /jupyterhub
    ALB->>GH: Redirect to GitHub for authorization
    GH-->>DS: Authorization prompt
    DS->>GH: Authorize application
    GH-->>ALB: OAuth callback with token
    ALB->>HUB: Authenticated request

    alt First login
        HUB->>POD: Spawn jupyter-username pod on ng1
        POD->>EFS: Mount /home/username  (ReadWriteMany)
        Note over POD,EFS: Home directory persists across sessions
    else Returning user
        HUB->>POD: Start existing user server
        POD->>EFS: Re-mount home directory
    end

    HUB-->>DS: Notebook interface ready

    DS->>POD: Open notebook — run cells
    POD->>MLF: mlflow.set_experiment("my-experiment")
    POD->>MLF: mlflow.start_run()

    loop Training loop
        POD->>MLF: log_metric("loss", value, step)
    end

    POD->>MLF: log_model(model, "model")
    MLF->>S3: Upload model artifacts
    MLF-->>POD: run_id returned

    DS->>MLF: View run in MLflow UI at /mlflow
""",
    },

    # ── 5. Observability ─────────────────────────────────────────────────────
    {
        "id": "observability",
        "tab": "Observability",
        "title": "Observability & Alerting Stack",
        "subtitle": (
            "How Prometheus collects metrics from every platform component every 30s, "
            "and how Grafana surfaces dashboards and fires alerts."
        ),
        "mermaid": """\
flowchart TD
    subgraph sources [" Metrics Sources — scraped every 30 seconds "]
        AF["Airflow Webserver\n/metrics  (StatsD exporter)"]
        ML["MLflow Server\n/metrics"]
        JH["JupyterHub Hub\n/metrics"]
        NE0["node-exporter on ng0\nCPU / memory / disk / network"]
        NE1["node-exporter on ng1\nCPU / memory / disk / network"]
        KSM["kube-state-metrics\nPod and deployment state"]
    end

    PROM["Prometheus\nTime series database\n15-day retention on EBS"]

    AF -->|"pull"| PROM
    ML -->|"pull"| PROM
    JH -->|"pull"| PROM
    NE0 -->|"node stats"| PROM
    NE1 -->|"node stats"| PROM
    KSM -->|"k8s objects"| PROM

    subgraph grafana [" Grafana Dashboards  —  /grafana  (GitHub OAuth gated) "]
        D1["Dashboard #2\nKubernetes Cluster Overview"]
        D2["Dashboard #315\nNode Exporter Full"]
        D3["Dashboard #6417\nKubernetes Pod Resources"]
    end

    PROM -->|"PromQL"| D1 & D2 & D3

    ALERTS["Alert Rules\nThreshold-based in Grafana"]
    NOTIFY["Notification Channels\nEmail / Slack / PagerDuty"]

    PROM --> ALERTS
    ALERTS -->|"threshold breached"| NOTIFY

    User(["User via /grafana"]) -->|"views"| D1 & D2 & D3
""",
    },

    # ── 6. Secret management ─────────────────────────────────────────────────
    {
        "id": "secrets",
        "tab": "Secret Management",
        "title": "Secret Management — ESO + IRSA",
        "subtitle": (
            "How the External Secrets Operator uses IRSA to fetch secrets from "
            "AWS Secrets Manager and inject them into Airflow, MLflow, and JupyterHub pods."
        ),
        "mermaid": """\
sequenceDiagram
    participant TF as Terraform
    participant SM as AWS Secrets Manager
    participant OIDC as EKS OIDC Provider
    participant ESO as External Secrets Operator
    participant IAM as IRSA Role: iam_eso
    participant K8S as Kubernetes Secrets API
    participant AF as Airflow Pod
    participant ML as MLflow Pod
    participant JH as JupyterHub Pod

    TF->>SM: Provision secrets under mlplatform/*
    Note over TF,SM: DB passwords, OAuth secrets, API keys

    Note over ESO: ESO pod starts with K8s ServiceAccount
    Note over ESO: annotated with iam_eso IAM role ARN

    ESO->>OIDC: Request IRSA token for ServiceAccount
    OIDC-->>ESO: Signed JWT  (proof of pod identity)
    ESO->>IAM: AssumeRoleWithWebIdentity  (present JWT)
    IAM-->>ESO: Temporary AWS credentials

    ESO->>SM: GetSecretValue  mlplatform/airflow
    ESO->>SM: GetSecretValue  mlplatform/mlflow
    ESO->>SM: GetSecretValue  mlplatform/jupyterhub
    SM-->>ESO: Secret values  (DB URLs, tokens, keys)

    ESO->>K8S: Create / update Kubernetes Secret objects
    Note over ESO,K8S: One Secret per namespace

    AF->>K8S: Mount as env var — DB_PASSWORD, FERNET_KEY
    ML->>K8S: Mount as env var — MLFLOW_TRACKING_TOKEN
    JH->>K8S: Mount as env var — GITHUB_CLIENT_SECRET

    Note over ESO,SM: Auto-rotation: ESO polls every 1h
    Note over ESO,SM: Re-syncs K8s Secrets on AWS value change
""",
    },

    # ── 7. Network & identity ────────────────────────────────────────────────
    {
        "id": "network",
        "tab": "Network & Identity",
        "title": "Network Topology & IRSA Identity Chain",
        "subtitle": (
            "VPC layout across 3 AZs, EKS node placement in private subnets, "
            "and the OIDC-based IRSA chain that gives each pod fine-grained AWS IAM access."
        ),
        "mermaid": """\
flowchart TD
    Internet(["Internet"])

    subgraph vpc [" VPC  10.0.0.0/16 "]
        subgraph pub [" Public Subnets  —  3 AZs "]
            IGW["Internet Gateway"]
            NAT["NAT Gateway  (AZ1)\nShared egress for all nodes"]
            ALBN["ALB Nodes\ninternet-facing"]
        end

        subgraph priv [" Private Subnets  —  3 AZs "]
            EKS["EKS Control Plane\nPrivate API endpoint only"]
            ng0["ng0  t3.small  0-5 nodes"]
            ng1["ng1  t3.medium  4-6 nodes"]
            ng2["ng2  t3.large  0-3 nodes"]
        end

        subgraph db [" DB Subnets  —  isolated, no public route "]
            PG["RDS PostgreSQL\nport 5000  —  Airflow metadata"]
            MY["RDS MySQL\nport 5432  —  MLflow backend"]
            EFS["EFS Mount Targets\nReadWriteMany  —  notebooks"]
        end
    end

    subgraph dns [" DNS & TLS "]
        R53["Route 53\nHosted zone"]
        ACM["ACM Certificate\nWildcard TLS"]
    end

    subgraph irsa [" AWS Identity  —  IRSA chain "]
        OIDC["EKS OIDC Provider\nFederation hub"]
        IAM_AF["IRSA: Airflow\nS3 airflow prefix read/write"]
        IAM_ML["IRSA: MLflow\nS3 mlflow prefix read/write"]
        IAM_SM["IRSA: SageMaker\nSageMaker + ECR + S3"]
        IAM_ESO["IRSA: ESO\nSecrets Manager GetSecretValue"]
        IAM_DNS["IRSA: ExternalDNS\nRoute53 ChangeResourceRecordSets"]
    end

    Internet --> IGW --> ALBN
    NAT -->|"outbound only"| Internet
    ng0 & ng1 & ng2 -->|"egress via"| NAT

    R53 -->|"A record"| ALBN
    ACM -.->|"TLS cert"| ALBN

    EKS -->|"manages"| ng0 & ng1 & ng2
    EKS -->|"issues tokens via"| OIDC

    OIDC --> IAM_AF
    OIDC --> IAM_ML
    OIDC --> IAM_SM
    OIDC --> IAM_ESO
    OIDC --> IAM_DNS
""",
    },
]


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(diagrams: list[dict]) -> str:
    tab_buttons = "\n    ".join(
        f'<button class="tab-btn{" active" if i == 0 else ""}" '
        f'id="btn-{d["id"]}" onclick="showTab(\'{d["id"]}\')">'
        f'{d["tab"]}</button>'
        for i, d in enumerate(diagrams)
    )

    panels = "\n".join(
        f"""  <div class="panel{"" if i else " active"}" id="panel-{d["id"]}">
    <h2>{d["title"]}</h2>
    <p class="subtitle">{d["subtitle"]}</p>
    <div class="diagram-box">
      <pre class="mermaid" id="mermaid-{d["id"]}">{html.escape(d["mermaid"])}</pre>
    </div>
  </div>"""
        for i, d in enumerate(diagrams)
    )

    first_id = diagrams[0]["id"]
    all_ids = ", ".join(f'"{d["id"]}"' for d in diagrams)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MLOps Platform on EKS — Architecture Diagrams</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    min-height: 100vh;
  }}

  /* ── Header ── */
  header {{
    padding: 20px 32px 14px;
    border-bottom: 1px solid #21262d;
  }}
  header h1 {{
    font-size: 18px;
    font-weight: 600;
    color: #e6edf3;
  }}
  header p {{
    font-size: 13px;
    color: #8b949e;
    margin-top: 4px;
  }}

  /* ── Tabs ── */
  nav.tabs {{
    display: flex;
    gap: 0;
    padding: 0 32px;
    border-bottom: 1px solid #21262d;
    overflow-x: auto;
  }}
  .tab-btn {{
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #8b949e;
    cursor: pointer;
    font-family: inherit;
    font-size: 13px;
    padding: 11px 16px;
    white-space: nowrap;
    transition: color 0.15s, border-color 0.15s;
  }}
  .tab-btn:hover {{ color: #c9d1d9; }}
  .tab-btn.active {{
    color: #58a6ff;
    border-bottom-color: #58a6ff;
    font-weight: 500;
  }}

  /* ── Content ── */
  main {{ padding: 28px 32px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  .panel h2 {{
    font-size: 17px;
    font-weight: 600;
    color: #e6edf3;
    margin-bottom: 6px;
  }}
  .subtitle {{
    font-size: 13px;
    color: #8b949e;
    line-height: 1.55;
    max-width: 820px;
    margin-bottom: 22px;
  }}

  /* ── Diagram box ── */
  .diagram-box {{
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 36px 32px;
    overflow: auto;
    min-height: 360px;
    display: flex;
    justify-content: center;
    align-items: flex-start;
  }}
  .diagram-box svg {{
    max-width: 100%;
    height: auto;
  }}
  .mermaid {{ display: none; }}  /* hide raw text */

  /* ── Error state ── */
  .diagram-error {{
    color: #f85149;
    font-size: 13px;
    font-family: "SF Mono", Consolas, monospace;
    white-space: pre-wrap;
    padding: 12px;
  }}
</style>
</head>
<body>

<header>
  <h1>MLOps Platform on EKS — Architecture Diagrams</h1>
  <p>{len(diagrams)} focused diagrams covering platform topology, workflows, and operational flows. Click a tab to switch.</p>
</header>

<nav class="tabs">
    {tab_buttons}
</nav>

<main>
{panels}
</main>

<script>
  mermaid.initialize({{
    startOnLoad: false,
    theme: "dark",
    themeVariables: {{
      darkMode: true,
      background:         "#161b22",
      primaryColor:       "#1f3a5f",
      primaryTextColor:   "#e6edf3",
      primaryBorderColor: "#388bfd",
      lineColor:          "#58a6ff",
      secondaryColor:     "#21262d",
      tertiaryColor:      "#0d1117",
      edgeLabelBackground:"#21262d",
      clusterBkg:         "#161b22",
      clusterBorder:      "#30363d",
      titleColor:         "#e6edf3",
      fontFamily:         '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
      fontSize:           "14px",
      actorBkg:           "#1f3a5f",
      actorBorder:        "#388bfd",
      actorTextColor:     "#e6edf3",
      activationBkgColor: "#21262d",
      noteBkgColor:       "#21262d",
      noteTextColor:      "#c9d1d9",
      labelBoxBkgColor:   "#21262d",
      sequenceNumberColor:"#e6edf3",
    }},
    flowchart: {{ curve: "basis", padding: 24, htmlLabels: true }},
    sequence: {{ actorMargin: 80, useMaxWidth: false, mirrorActors: false }},
  }});

  const DIAGRAM_IDS = [{all_ids}];
  const rendered    = new Set();

  async function renderDiagram(id) {{
    if (rendered.has(id)) return;
    const pre = document.getElementById("mermaid-" + id);
    const box = pre.closest(".diagram-box");
    if (!pre || !box) return;

    try {{
      const {{ svg }} = await mermaid.render("svg-" + id, pre.textContent.trim());
      // Replace <pre> with rendered SVG
      const wrapper = document.createElement("div");
      wrapper.innerHTML = svg;
      box.replaceChildren(wrapper);
      rendered.add(id);
    }} catch (err) {{
      const msg = document.createElement("pre");
      msg.className = "diagram-error";
      msg.textContent = "Diagram error: " + err.message;
      box.replaceChildren(msg);
    }}
  }}

  function showTab(id) {{
    document.querySelectorAll(".panel").forEach(p  => p.classList.remove("active"));
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.getElementById("panel-" + id).classList.add("active");
    document.getElementById("btn-"   + id).classList.add("active");
    renderDiagram(id);
  }}

  // Render the first tab on load
  document.addEventListener("DOMContentLoaded", () => renderDiagram("{first_id}"));
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    output_path = Path(__file__).parent / "platform_diagrams.html"
    html_content = generate_html(DIAGRAMS)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"Saved -> {output_path}")
    webbrowser.open(output_path.as_uri())
    print("Opened in browser.")


if __name__ == "__main__":
    main()
