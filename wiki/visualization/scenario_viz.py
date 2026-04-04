"""
MLOps Platform on EKS -- Scenario-Based Interactive Visualization

7 interactive scenarios showing key platform workflows as highlighted paths
through the full architecture graph.

Use the dropdown (top-left) to switch between scenarios. Each scenario dims
all components except those involved in that specific workflow.

Usage:
    python scenario_viz.py
    # Opens scenario_viz.html in your default browser
"""

import webbrowser
from pathlib import Path

import networkx as nx
import plotly.graph_objects as go

# ── 1. Platform Components ────────────────────────────────────────────────────
# (id, label, layer, group/namespace, description)
NODES = [
    # Entry
    ("internet",     "Internet",              "Entry",      "external",     "Public internet -- user entry point"),
    # Networking / AWS Infra
    ("igw",          "Internet Gateway",      "Networking", "aws-infra",    "VPC Internet Gateway"),
    ("alb",          "ALB",                   "Networking", "aws-compute",  "Application Load Balancer -- path-based routing"),
    ("route53",      "Route 53",              "Networking", "aws-infra",    "DNS -> ALB IP mapping"),
    ("acm",          "ACM Cert",              "Networking", "aws-infra",    "TLS wildcard certificate"),
    ("vpc",          "VPC 10.0.0.0/16",       "Networking", "aws-infra",    "Private network boundary"),
    ("pub_subnet",   "Public Subnets (3AZ)",  "Networking", "aws-infra",    "3x public subnets for ALB"),
    ("priv_subnet",  "Private Subnets (3AZ)", "Networking", "aws-infra",    "3x private subnets for EKS nodes"),
    ("nat_gw",       "NAT Gateway",           "Networking", "aws-infra",    "Egress for private subnet traffic"),
    # Identity / Auth
    ("github",       "GitHub OAuth",          "Identity",   "external",     "OAuth2 provider for all platform UIs"),
    ("oidc",         "OIDC Provider",         "Identity",   "aws-identity", "EKS OIDC -- enables IRSA pod identity"),
    ("iam_mlflow",   "IRSA: MLflow",          "Identity",   "aws-identity", "S3 read/write on mlflow prefix"),
    ("iam_airflow",  "IRSA: Airflow",         "Identity",   "aws-identity", "S3 read/write on airflow prefix"),
    ("iam_sage",     "IRSA: SageMaker",       "Identity",   "aws-identity", "SageMaker + ECR + S3 access"),
    ("iam_eso",      "IRSA: ESO",             "Identity",   "aws-identity", "Secrets Manager: GetSecretValue"),
    ("iam_extdns",   "IRSA: ExternalDNS",     "Identity",   "aws-identity", "Route53: ChangeResourceRecordSets"),
    # Compute
    ("eks",          "EKS Cluster",           "Compute",    "aws-compute",  "EKS 1.24, private API endpoint"),
    ("ng0",          "ng0 (t3.small)",        "Compute",    "aws-compute",  "0-5 nodes, spillover workloads"),
    ("ng1",          "ng1 (t3.medium)",       "Compute",    "aws-compute",  "4-6 nodes, base platform (always on)"),
    ("ng2",          "ng2 (t3.large)",        "Compute",    "aws-compute",  "0-3 nodes, NoSchedule heavy ML"),
    ("efs",          "EFS",                   "Compute",    "aws-compute",  "ReadWriteMany -- persistent notebooks & DAG logs"),
    ("ca",           "Cluster Autoscaler",    "Compute",    "kube-system",  "Scales node groups on pending pod demand"),
    # Platform Applications
    ("alb_ctrl",     "ALB Controller",        "Platform",   "kube-system",  "Provisions ALB from Ingress resources"),
    ("ext_dns",      "ExternalDNS",           "Platform",   "kube-system",  "Syncs Ingress hostnames to Route53"),
    ("eso",          "Ext. Secrets Operator", "Platform",   "ext-secrets",  "Syncs AWS Secrets Manager to K8s Secrets"),
    ("airflow_web",  "Airflow Webserver",     "Platform",   "airflow",      "Airflow UI + REST API (port 8080)"),
    ("airflow_sch",  "Airflow Scheduler",     "Platform",   "airflow",      "DAG parsing + KubernetesExecutor"),
    ("airflow_git",  "git-sync",              "Platform",   "airflow",      "Sidecar: pulls DAGs from GitHub every 60s"),
    ("mlflow_svc",   "MLflow Server",         "Platform",   "mlflow",       "Experiment tracking + Model Registry"),
    ("mlflow_proxy", "MLflow OAuth Proxy",    "Platform",   "mlflow",       "GitHub OAuth proxy for MLflow UI"),
    ("jh_hub",       "JupyterHub Hub",        "Platform",   "jupyterhub",   "Spawns per-user notebook servers"),
    ("jh_proxy",     "JH Proxy",              "Platform",   "jupyterhub",   "Routes traffic to individual user servers"),
    ("jh_user",      "User Notebook",         "Platform",   "jupyterhub",   "jupyter-<username> pod, EFS-mounted home"),
    ("prometheus",   "Prometheus",            "Platform",   "monitoring",   "Scrapes all /metrics endpoints (15d retention)"),
    ("grafana",      "Grafana",               "Platform",   "monitoring",   "Dashboards: node, Airflow, MLflow metrics"),
    ("sage_dash",    "SageMaker Dashboard",   "Platform",   "sagemaker",    "Streamlit UI for model deployment"),
    # Data Stores
    ("s3_mlflow",    "S3: mlflow-artifacts",  "Data",       "aws-data",     "MLflow model artifacts"),
    ("s3_airflow",   "S3: airflow-data",      "Data",       "aws-data",     "Airflow pipeline I/O data"),
    ("rds_pg",       "RDS PostgreSQL",        "Data",       "aws-data",     "Airflow metadata DB (port 5000)"),
    ("rds_mysql",    "RDS MySQL",             "Data",       "aws-data",     "MLflow backend store (port 5432)"),
    ("secrets_mgr",  "Secrets Manager",       "Data",       "aws-data",     "mlplatform/* -- all platform secrets"),
    ("ecr",          "ECR",                   "Data",       "aws-data",     "Container images for ML serving"),
    ("git_repo",     "DAG Git Repo",          "Data",       "external",     "Airflow DAG source repository"),
]

# ── 2. Platform Connections ───────────────────────────────────────────────────
# (src, dst, label)
EDGES = [
    # Entry / Networking
    ("internet",    "igw",          "internet traffic"),
    ("igw",         "pub_subnet",   "routes"),
    ("pub_subnet",  "alb",          "hosts"),
    ("pub_subnet",  "nat_gw",       "hosts"),
    ("nat_gw",      "priv_subnet",  "NAT egress"),
    ("vpc",         "pub_subnet",   "contains"),
    ("vpc",         "priv_subnet",  "contains"),
    ("acm",         "alb",          "TLS cert"),
    ("alb_ctrl",    "alb",          "provisions"),
    ("ext_dns",     "route53",      "DNS sync"),
    ("alb",         "route53",      "DNS A record"),
    # ALB routing
    ("alb",         "airflow_web",  "/airflow"),
    ("alb",         "mlflow_proxy", "/mlflow"),
    ("alb",         "jh_proxy",     "/jupyterhub"),
    ("alb",         "grafana",      "/grafana"),
    ("alb",         "sage_dash",    "/sagemaker"),
    # OAuth
    ("github",      "airflow_web",  "OAuth"),
    ("github",      "jh_hub",       "OAuth"),
    ("github",      "grafana",      "OAuth"),
    ("github",      "mlflow_proxy", "OAuth"),
    ("github",      "sage_dash",    "OAuth"),
    # EKS / Compute
    ("eks",         "ng0",          "manages"),
    ("eks",         "ng1",          "manages"),
    ("eks",         "ng2",          "manages"),
    ("eks",         "oidc",         "issues tokens"),
    ("ca",          "ng0",          "autoscales"),
    ("ca",          "ng1",          "autoscales"),
    ("ca",          "ng2",          "autoscales"),
    ("priv_subnet", "ng0",          "hosts nodes"),
    ("priv_subnet", "ng1",          "hosts nodes"),
    # IRSA
    ("oidc",        "iam_mlflow",   "federation"),
    ("oidc",        "iam_airflow",  "federation"),
    ("oidc",        "iam_sage",     "federation"),
    ("oidc",        "iam_eso",      "federation"),
    ("oidc",        "iam_extdns",   "federation"),
    ("ext_dns",     "iam_extdns",   "IRSA"),
    # Airflow flows
    ("airflow_web", "airflow_sch",  "RPC"),
    ("airflow_sch", "airflow_git",  "sidecar"),
    ("airflow_git", "git_repo",     "git pull"),
    ("airflow_sch", "rds_pg",       "JDBC metadata"),
    ("airflow_sch", "ng1",          "spawns task pods"),
    ("airflow_sch", "ng2",          "spawns ML pods"),
    ("airflow_sch", "s3_airflow",   "S3 API"),
    ("airflow_sch", "mlflow_svc",   "tracking API"),
    ("airflow_sch", "iam_airflow",  "IRSA"),
    # MLflow flows
    ("mlflow_proxy","mlflow_svc",   "proxy"),
    ("mlflow_svc",  "rds_mysql",    "JDBC backend"),
    ("mlflow_svc",  "s3_mlflow",    "artifact store"),
    ("mlflow_svc",  "iam_mlflow",   "IRSA"),
    # JupyterHub flows
    ("jh_proxy",    "jh_hub",       "proxy"),
    ("jh_hub",      "jh_user",      "spawns"),
    ("jh_user",     "efs",          "ReadWriteMany"),
    ("jh_user",     "mlflow_svc",   "tracking API"),
    ("efs",         "priv_subnet",  "Mount Targets"),
    # Observability
    ("prometheus",  "airflow_web",  "scrape /metrics"),
    ("prometheus",  "mlflow_svc",   "scrape /metrics"),
    ("prometheus",  "jh_hub",       "scrape /metrics"),
    ("prometheus",  "ng0",          "node-exporter"),
    ("prometheus",  "ng1",          "node-exporter"),
    ("grafana",     "prometheus",   "PromQL"),
    # ESO
    ("eso",         "secrets_mgr",  "GetSecretValue"),
    ("eso",         "iam_eso",      "IRSA"),
    ("eso",         "airflow_web",  "injects secrets"),
    ("eso",         "mlflow_svc",   "injects secrets"),
    ("eso",         "jh_hub",       "injects secrets"),
    # SageMaker
    ("sage_dash",   "ecr",          "push/pull images"),
    ("sage_dash",   "iam_sage",     "IRSA"),
    ("sage_dash",   "s3_mlflow",    "reads artifacts"),
    ("sage_dash",   "mlflow_svc",   "registry API"),
    # Placement
    ("rds_pg",      "priv_subnet",  "runs in (DB subnet)"),
    ("rds_mysql",   "priv_subnet",  "runs in (DB subnet)"),
]

# ── 3. Visual Config ──────────────────────────────────────────────────────────
GROUP_COLORS = {
    "aws-infra":    "#2196F3",
    "aws-compute":  "#4CAF50",
    "aws-data":     "#F44336",
    "aws-identity": "#607D8B",
    "airflow":      "#FF9800",
    "mlflow":       "#9C27B0",
    "jupyterhub":   "#00BCD4",
    "monitoring":   "#E91E63",
    "sagemaker":    "#8BC34A",
    "kube-system":  "#795548",
    "ext-secrets":  "#FF5722",
    "external":     "#9E9E9E",
}

LAYER_Y = {
    "Entry":      6.5,
    "Networking": 5.5,
    "Identity":   4.5,
    "Compute":    3.5,
    "Platform":   2.0,
    "Data":       0.5,
}

# ── 4. Scenarios ──────────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "name": "Full Architecture Overview",
        "description": "Complete MLOps platform -- all 43 components and 70+ connections visible.",
        "color": "#58a6ff",
        "highlight_nodes": None,   # None = all nodes highlighted
        "highlight_edges": None,   # None = all edges highlighted
        "steps": [
            "Entry: Users reach the platform via Route53 DNS -> ALB",
            "Auth: GitHub OAuth secures all platform UIs",
            "Compute: EKS cluster with 3 auto-scaling node groups (ng0, ng1, ng2)",
            "Platform: Airflow, MLflow, JupyterHub, Grafana, SageMaker Dashboard",
            "Data: RDS (PostgreSQL + MySQL), S3, Secrets Manager, ECR",
            "Identity: IRSA gives pods fine-grained IAM access via OIDC federation",
            "Ops: ESO syncs secrets | ExternalDNS manages DNS | CA scales nodes",
        ],
    },
    {
        "name": "ML Training Pipeline",
        "description": "Airflow DAG triggers training -> task pods run on EKS -> MLflow tracks metrics -> artifacts saved to S3.",
        "color": "#FF9800",
        "highlight_nodes": [
            "internet", "alb", "airflow_web", "airflow_sch", "airflow_git",
            "git_repo", "ng1", "ng2", "rds_pg", "mlflow_svc", "s3_mlflow",
            "rds_mysql", "iam_airflow", "iam_mlflow",
        ],
        "highlight_edges": [
            ("internet", "igw"), ("igw", "pub_subnet"), ("pub_subnet", "alb"),
            ("alb", "airflow_web"),
            ("airflow_web", "airflow_sch"),
            ("airflow_sch", "airflow_git"), ("airflow_git", "git_repo"),
            ("airflow_sch", "rds_pg"),
            ("airflow_sch", "ng1"), ("airflow_sch", "ng2"),
            ("airflow_sch", "mlflow_svc"),
            ("mlflow_svc", "s3_mlflow"), ("mlflow_svc", "rds_mysql"),
            ("airflow_sch", "iam_airflow"), ("mlflow_svc", "iam_mlflow"),
        ],
        "steps": [
            "1. git-sync sidecar polls GitHub and pulls latest DAG code (every 60s)",
            "2. User triggers a DAG run via Airflow UI at /airflow",
            "3. Scheduler parses the DAG, writes dag_run record to RDS PostgreSQL",
            "4. KubernetesExecutor spawns ephemeral task pods on ng1 / ng2",
            "5. Task code calls MLflow Tracking API to log metrics & hyperparams",
            "6. MLflow stores run metadata in RDS MySQL, artifacts in S3: mlflow-artifacts",
            "7. Task pods report status back to Scheduler via shared RDS state",
        ],
    },
    {
        "name": "Model Deployment",
        "description": "Scientist selects MLflow model -> SageMaker dashboard builds container -> pushes to ECR -> endpoint deployed.",
        "color": "#4CAF50",
        "highlight_nodes": [
            "internet", "alb", "mlflow_proxy", "mlflow_svc", "s3_mlflow",
            "rds_mysql", "sage_dash", "ecr", "iam_sage", "iam_mlflow",
        ],
        "highlight_edges": [
            ("internet", "igw"), ("igw", "pub_subnet"), ("pub_subnet", "alb"),
            ("alb", "mlflow_proxy"), ("alb", "sage_dash"),
            ("mlflow_proxy", "mlflow_svc"),
            ("mlflow_svc", "s3_mlflow"), ("mlflow_svc", "rds_mysql"),
            ("sage_dash", "mlflow_svc"),
            ("sage_dash", "s3_mlflow"),
            ("sage_dash", "ecr"),
            ("sage_dash", "iam_sage"), ("mlflow_svc", "iam_mlflow"),
        ],
        "steps": [
            "1. Data scientist opens MLflow UI at /mlflow",
            "2. Reviews experiment runs, compares metrics across runs",
            "3. Registers best model version in MLflow Model Registry",
            "4. Opens SageMaker Dashboard at /sagemaker",
            "5. Dashboard reads registered model artifacts from S3",
            "6. Builds ML serving container image, pushes image to ECR",
            "7. Deploys SageMaker real-time inference endpoint",
        ],
    },
    {
        "name": "Notebook Session",
        "description": "User logs in via GitHub OAuth -> JupyterHub spawns pod -> mounts EFS -> runs experiments tracked in MLflow.",
        "color": "#00BCD4",
        "highlight_nodes": [
            "internet", "alb", "jh_proxy", "jh_hub", "jh_user", "efs",
            "mlflow_svc", "s3_mlflow", "github", "oidc", "iam_mlflow",
        ],
        "highlight_edges": [
            ("internet", "igw"), ("igw", "pub_subnet"), ("pub_subnet", "alb"),
            ("alb", "jh_proxy"),
            ("github", "jh_hub"),
            ("jh_proxy", "jh_hub"),
            ("jh_hub", "jh_user"),
            ("jh_user", "efs"),
            ("jh_user", "mlflow_svc"),
            ("mlflow_svc", "s3_mlflow"),
            ("mlflow_svc", "iam_mlflow"),
            ("efs", "priv_subnet"),
        ],
        "steps": [
            "1. User navigates to /jupyterhub via ALB",
            "2. GitHub OAuth authenticates the user",
            "3. JupyterHub Hub spawns jupyter-<username> pod on EKS",
            "4. Pod mounts EFS (ReadWriteMany) as the persistent home directory",
            "5. User opens notebook and begins exploration / model development",
            "6. Notebook code calls MLflow Tracking API to log experiments",
            "7. Artifacts and metrics saved to S3: mlflow-artifacts and RDS MySQL",
        ],
    },
    {
        "name": "Observability & Alerting",
        "description": "Prometheus scrapes all platform /metrics endpoints -> Grafana dashboards visualize and alert on anomalies.",
        "color": "#E91E63",
        "highlight_nodes": [
            "internet", "alb", "grafana", "prometheus",
            "airflow_web", "mlflow_svc", "jh_hub", "ng0", "ng1",
        ],
        "highlight_edges": [
            ("internet", "igw"), ("igw", "pub_subnet"), ("pub_subnet", "alb"),
            ("alb", "grafana"),
            ("grafana", "prometheus"),
            ("prometheus", "airflow_web"),
            ("prometheus", "mlflow_svc"),
            ("prometheus", "jh_hub"),
            ("prometheus", "ng0"),
            ("prometheus", "ng1"),
        ],
        "steps": [
            "1. User opens Grafana dashboards at /grafana (GitHub OAuth gated)",
            "2. Grafana queries Prometheus via PromQL expressions",
            "3. Prometheus scrapes all /metrics endpoints every 30s",
            "4. node-exporter provides CPU / memory / disk metrics from ng0, ng1",
            "5. App metrics: Airflow, MLflow, JupyterHub instrumented with prom client",
            "6. 15-day metric retention in Prometheus TSDB on EBS volume",
            "7. Alert rules configured in Grafana fire notifications on threshold breach",
        ],
    },
    {
        "name": "Secret Injection (ESO)",
        "description": "ESO assumes IRSA role -> fetches from Secrets Manager -> creates K8s Secrets -> injected into platform pods.",
        "color": "#FF5722",
        "highlight_nodes": [
            "secrets_mgr", "eso", "iam_eso", "oidc", "eks",
            "airflow_web", "mlflow_svc", "jh_hub",
        ],
        "highlight_edges": [
            ("eks", "oidc"),
            ("oidc", "iam_eso"),
            ("eso", "iam_eso"),
            ("eso", "secrets_mgr"),
            ("eso", "airflow_web"),
            ("eso", "mlflow_svc"),
            ("eso", "jh_hub"),
        ],
        "steps": [
            "1. ESO pod starts with a K8s ServiceAccount bound to iam_eso IRSA role",
            "2. EKS OIDC provider issues a signed JWT token for the ServiceAccount",
            "3. ESO assumes iam_eso IAM role, gains GetSecretValue permission",
            "4. ESO reads all mlplatform/* paths from AWS Secrets Manager",
            "5. ESO creates or updates Kubernetes Secret objects in each namespace",
            "6. Platform pods mount K8s Secrets as environment variables at startup",
            "7. Auto-rotation: ESO re-syncs K8s Secrets when AWS secret values change",
        ],
    },
    {
        "name": "Infrastructure Provisioning",
        "description": "Terraform provisions all AWS resources: VPC -> EKS -> node groups -> platform operators. State in S3.",
        "color": "#9C27B0",
        "highlight_nodes": [
            "vpc", "pub_subnet", "priv_subnet", "nat_gw", "igw",
            "eks", "ng0", "ng1", "ng2", "oidc",
            "alb_ctrl", "ext_dns", "ca", "alb", "route53",
        ],
        "highlight_edges": [
            ("vpc", "pub_subnet"), ("vpc", "priv_subnet"),
            ("igw", "pub_subnet"),
            ("nat_gw", "priv_subnet"),
            ("pub_subnet", "alb"),
            ("alb_ctrl", "alb"),
            ("ext_dns", "route53"),
            ("eks", "ng0"), ("eks", "ng1"), ("eks", "ng2"),
            ("eks", "oidc"),
            ("ca", "ng0"), ("ca", "ng1"), ("ca", "ng2"),
            ("priv_subnet", "ng0"), ("priv_subnet", "ng1"),
        ],
        "steps": [
            "1. terraform init -- configures S3 backend (mlplatform-terraform-state)",
            "2. DynamoDB table (mlplatform-terraform-locks) prevents concurrent applies",
            "3. VPC + public/private subnets provisioned across 3 AZs",
            "4. IGW + NAT Gateway deployed for public / private egress",
            "5. EKS cluster created (private API endpoint, version 1.24)",
            "6. Node groups ng0, ng1, ng2 provisioned with Auto Scaling Groups",
            "7. Helm releases: ALB Controller, ExternalDNS, Cluster Autoscaler deployed",
        ],
    },
]


# ── 5. Graph ──────────────────────────────────────────────────────────────────

def build_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    for node_id, label, layer, group, desc in NODES:
        G.add_node(node_id, label=label, layer=layer, group=group, desc=desc)
    for src, dst, label in EDGES:
        if src in G.nodes and dst in G.nodes:
            G.add_edge(src, dst, label=label)
    return G


def compute_layout(G: nx.DiGraph) -> dict:
    """Spring layout for X, layer-clamped Y, with intra-layer repulsion pass."""
    pos_spring = nx.spring_layout(G, seed=42, k=2.2, iterations=150)
    pos = {}
    layers: dict[str, list] = {}
    for nid in G.nodes:
        layer = G.nodes[nid]["layer"]
        y = LAYER_Y.get(layer, 3.0)
        x = pos_spring[nid][0] * 7.0
        pos[nid] = [x, y]
        layers.setdefault(layer, []).append(nid)
    # Intra-layer repulsion: enforce minimum horizontal gap
    min_gap = 0.9
    for layer_nodes in layers.values():
        layer_nodes.sort(key=lambda n: pos[n][0])
        for i in range(1, len(layer_nodes)):
            prev, curr = layer_nodes[i - 1], layer_nodes[i]
            if pos[curr][0] - pos[prev][0] < min_gap:
                pos[curr][0] = pos[prev][0] + min_gap
    return {nid: tuple(xy) for nid, xy in pos.items()}


# ── 6. Trace Factory ──────────────────────────────────────────────────────────

def _edge_segments(G: nx.DiGraph, pos: dict, edge_set=None):
    """Return x/y arrays of None-separated edge segments for Scatter lines."""
    xs, ys = [], []
    for src, dst in G.edges():
        if edge_set is None or (src, dst) in edge_set:
            x0, y0 = pos[src]
            x1, y1 = pos[dst]
            xs += [x0, x1, None]
            ys += [y0, y1, None]
    return xs, ys


def build_all_traces(G: nx.DiGraph, pos: dict) -> tuple[list, int]:
    """
    Build all traces upfront so updatemenus can toggle visibility.

    Trace layout (total = 2 + 2 * len(SCENARIOS)):
      [0]         base dim edges   (always visible)
      [1]         base dim nodes   (always visible)
      [2 + s*2]   scenario-s bright edges
      [2 + s*2+1] scenario-s bright nodes + labels
    """
    traces = []

    # Base: all edges, very faint
    xs, ys = _edge_segments(G, pos)
    traces.append(go.Scatter(
        x=xs, y=ys, mode="lines",
        line=dict(width=0.6, color="rgba(55,60,85,0.22)"),
        hoverinfo="none", showlegend=False, visible=True,
    ))

    # Base: all nodes, greyed out
    traces.append(go.Scatter(
        x=[pos[n][0] for n in G.nodes],
        y=[pos[n][1] for n in G.nodes],
        mode="markers",
        marker=dict(size=7, color="rgba(65,70,100,0.35)"),
        hoverinfo="none", showlegend=False, visible=True,
    ))

    # Per-scenario traces (2 per scenario)
    for sc_idx, sc in enumerate(SCENARIOS):
        hl_nodes = sc["highlight_nodes"]
        hl_edges = sc["highlight_edges"]
        color = sc["color"]
        is_first = (sc_idx == 0)

        hl_node_set = None if hl_nodes is None else set(hl_nodes)
        hl_edge_set = None if hl_edges is None else set(map(tuple, hl_edges))

        # Bright edges
        ex, ey = _edge_segments(G, pos, hl_edge_set)
        traces.append(go.Scatter(
            x=ex, y=ey, mode="lines",
            line=dict(width=3.2, color=color),
            hoverinfo="none", showlegend=False,
            visible=is_first,
        ))

        # Bright nodes + labels (only active nodes in this trace)
        nxs, nys, labels, hovers, colors = [], [], [], [], []
        for nid, data in G.nodes(data=True):
            if hl_node_set is not None and nid not in hl_node_set:
                continue
            nxs.append(pos[nid][0])
            nys.append(pos[nid][1])
            # Trim suffixes like " (t3.small)" for readability
            short = data["label"].split(" (")[0]
            labels.append(short)
            hovers.append(
                f"<b>{data['label']}</b><br>"
                f"{data['desc']}<br>"
                f"<i>group: {data['group']} | layer: {data['layer']}</i>"
            )
            colors.append(GROUP_COLORS.get(data["group"], "#9E9E9E"))

        traces.append(go.Scatter(
            x=nxs, y=nys,
            mode="markers+text",
            text=labels,
            textposition="top center",
            textfont=dict(size=8, color="rgba(220,228,255,0.92)"),
            marker=dict(
                size=16, color=colors,
                line=dict(width=1.5, color="rgba(255,255,255,0.5)"),
                opacity=0.95,
            ),
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
            showlegend=False, visible=is_first,
        ))

    return traces, len(SCENARIOS)


# ── 7. Figure Assembly ────────────────────────────────────────────────────────

def build_figure(G: nx.DiGraph, pos: dict, traces: list, n_scenarios: int) -> go.Figure:
    total = len(traces)

    # Layer rail labels (right margin, data Y coords)
    rail_anns = [
        dict(
            x=1.01, y=y_val, xref="paper", yref="y",
            text=f"<b>{layer}</b>",
            showarrow=False,
            font=dict(size=9, color="rgba(130,140,200,0.6)"),
            xanchor="left",
        )
        for layer, y_val in LAYER_Y.items()
    ]

    def steps_annotation(sc: dict) -> dict:
        return dict(
            x=1.02, y=0.99, xref="paper", yref="paper",
            text="<b>Workflow Steps</b><br><br>" + "<br>".join(sc["steps"]),
            showarrow=False, align="left",
            xanchor="left", yanchor="top",
            font=dict(size=10, color="rgba(210,218,245,0.92)",
                      family="Inter, Arial, sans-serif"),
            bgcolor="rgba(10,14,28,0.90)",
            bordercolor=sc["color"],
            borderwidth=2,
            borderpad=11,
        )

    def title_text(sc: dict) -> str:
        return (
            f"<b>{sc['name']}</b>"
            f"<span style='color:rgba(160,170,220,0.8);font-size:13px'>"
            f"  --  {sc['description']}</span>"
        )

    # Build dropdown buttons
    buttons = []
    for sc_idx, sc in enumerate(SCENARIOS):
        # Base traces always visible; toggle scenario pairs
        visible = [True, True]
        for i in range(n_scenarios):
            visible += [i == sc_idx, i == sc_idx]

        buttons.append(dict(
            label=f"  {sc['name']}",
            method="update",
            args=[
                {"visible": visible},
                {
                    "title.text": title_text(sc),
                    "annotations": rail_anns + [steps_annotation(sc)],
                },
            ],
        ))

    # Legend annotation (bottom-left)
    legend_items = "".join(
        f"<span style='color:{c}'>&#9632;</span> {g}  "
        for g, c in GROUP_COLORS.items()
    )
    legend_ann = dict(
        x=0.0, y=-0.01, xref="paper", yref="paper",
        text=f"<b>Group colors:</b>  {legend_items}",
        showarrow=False, align="left",
        xanchor="left", yanchor="top",
        font=dict(size=9, color="rgba(180,185,220,0.75)"),
    )

    s0 = SCENARIOS[0]
    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(
            text=title_text(s0),
            font=dict(size=17, color="#dde4ff"),
            x=0.5, xanchor="center",
        ),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.01, y=0.985,
            xanchor="left", yanchor="top",
            bgcolor="rgba(10,14,28,0.97)",
            font=dict(color="#c9d1d9", size=12),
            bordercolor="rgba(88,166,255,0.45)",
            borderwidth=1,
            buttons=buttons,
            showactive=True,
            active=0,
            pad=dict(r=12, t=5),
        )],
        annotations=rail_anns + [steps_annotation(s0), legend_ann],
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=20, r=295, t=75, b=60),
        hoverlabel=dict(bgcolor="rgba(12,18,40,0.97)", font_size=12,
                        font_color="white"),
        height=840,
    )
    return fig


# ── 8. Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("Building scenario visualization...")
    G = build_graph()
    print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")

    print("  Computing layout...")
    pos = compute_layout(G)

    print("  Building traces...")
    traces, n_sc = build_all_traces(G, pos)
    print(f"  Total traces: {len(traces)} (2 base + {n_sc * 2} scenario)")

    print("  Rendering figure...")
    fig = build_figure(G, pos, traces, n_sc)

    output_path = Path(__file__).parent / "scenario_viz.html"
    fig.write_html(
        str(output_path),
        include_plotlyjs="cdn",
        full_html=True,
        config={"displayModeBar": True, "scrollZoom": True},
    )
    print(f"Saved -> {output_path}")
    webbrowser.open(output_path.as_uri())
    print("Opened in browser.")


if __name__ == "__main__":
    main()
