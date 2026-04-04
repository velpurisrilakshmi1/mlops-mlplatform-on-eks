"""
MLOps Platform on EKS — 3D Architecture Visualisation (Plotly + NetworkX)

Renders the full platform component graph as an interactive 3D scene.
All topology is embedded; no external files required.

Usage:
    python plotly_3d_architecture.py
    # Opens architecture_3d.html in your default browser
"""

import webbrowser
from pathlib import Path

import networkx as nx
import numpy as np
import plotly.graph_objects as go

# ─── 1. Platform Components ────────────────────────────────────────────────────
# Each node: (id, label, layer, namespace/group, description)
NODES = [
    # Infrastructure layer
    ("vpc",          "VPC 10.0.0.0/16",       "Infrastructure", "aws",        "Amazon VPC — private network boundary"),
    ("pub_subnet",   "Public Subnets (3 AZs)", "Infrastructure", "aws",        "3 × public subnets, one per AZ"),
    ("priv_subnet",  "Private Subnets (3 AZs)","Infrastructure", "aws",        "3 × private subnets for EKS nodes"),
    ("db_subnet",    "DB Subnets",             "Infrastructure", "aws",        "Isolated subnets for RDS instances"),
    ("nat_gw",       "NAT Gateway",            "Infrastructure", "aws",        "Single NAT GW in AZ1 (egress for nodes)"),
    ("igw",          "Internet Gateway",       "Infrastructure", "aws",        "VPC internet gateway (ALB egress)"),
    ("route53",      "Route 53",               "Infrastructure", "aws",        "Hosted zone: domain DNS management"),
    ("acm",          "ACM Certificate",        "Infrastructure", "aws",        "TLS certificate for *.domain"),
    ("tf_state_s3",  "TF State (S3)",          "Infrastructure", "aws",        "S3 bucket: mlplatform-terraform-state"),
    ("tf_lock_ddb",  "TF Lock (DynamoDB)",     "Infrastructure", "aws",        "DynamoDB: mlplatform-terraform-locks"),

    # Compute layer
    ("eks",         "EKS Cluster",            "Compute",        "aws",        "EKS 1.24, private endpoint"),
    ("ng0",         "NodeGroup ng0\nt3.small", "Compute",       "aws",        "0–5 nodes, spillover"),
    ("ng1",         "NodeGroup ng1\nt3.medium","Compute",       "aws",        "4–6 nodes, base platform"),
    ("ng2",         "NodeGroup ng2\nt3.large", "Compute",       "aws",        "0–3 nodes, NoSchedule, heavy ML"),
    ("alb",         "ALB (internet-facing)",  "Compute",        "aws",        "Path-based routing → all apps"),
    ("efs",         "EFS (ReadWriteMany)",     "Compute",        "aws",        "Shared filesystem for notebooks/DAGs"),
    ("cluster_as",  "Cluster Autoscaler",     "Compute",        "kube-system","Scales node groups based on pending pods"),

    # Identity / Security
    ("oidc",        "EKS OIDC Provider",      "Identity",       "aws",        "Federation: K8s SA → AWS IAM roles"),
    ("iam_mlflow",  "IRSA: mlflow",           "Identity",       "aws",        "S3 read/write on mlflow prefix"),
    ("iam_airflow", "IRSA: airflow",          "Identity",       "aws",        "S3 read/write on airflow prefix"),
    ("iam_sage",    "IRSA: sagemaker",        "Identity",       "aws",        "SageMaker + ECR + S3 full access"),
    ("iam_eso",     "IRSA: ext-secrets",      "Identity",       "aws",        "Secrets Manager GetSecretValue"),
    ("iam_extdns",  "IRSA: external-dns",     "Identity",       "aws",        "Route53 ChangeResourceRecordSets"),
    ("github_oauth","GitHub OAuth",           "Identity",       "external",   "OAuth2 for all UIs + K8s auth"),
    ("iam_users",   "Per-user IAM Roles",     "Identity",       "aws",        "Developer / User role per person"),

    # Platform Applications
    ("airflow",     "Apache Airflow 2.6.3",   "Platform",       "airflow",    "KubernetesExecutor, git-sync"),
    ("airflow_sch", "Airflow Scheduler",      "Platform",       "airflow",    "DAG parsing, task scheduling"),
    ("airflow_web", "Airflow Webserver",      "Platform",       "airflow",    "UI + REST API (GitHub OAuth)"),
    ("airflow_db",  "RDS PostgreSQL 13.11",   "Data",           "aws",        "Airflow metadata DB, port 5000"),
    ("mlflow",      "MLflow 2.4.1",           "Platform",       "mlflow",     "Experiment tracking + Model Registry"),
    ("mlflow_db",   "RDS MySQL 8.0.33",       "Data",           "aws",        "MLflow backend store, port 5432"),
    ("jupyterhub",  "JupyterHub 2.0.0",       "Platform",       "jupyterhub", "Multi-user notebook servers"),
    ("jh_proxy",    "JH Proxy/Hub",           "Platform",       "jupyterhub", "OAuth + user server management"),
    ("grafana",     "Grafana 9.5.5",          "Observability",  "monitoring", "Dashboards, GitHub OAuth"),
    ("prometheus",  "Prometheus 19.7.2",      "Observability",  "monitoring", "Metrics scraping + storage (15d)"),
    ("sagemaker",   "SageMaker Streamlit",    "Platform",       "sagemaker",  "Model deployment dashboard"),

    # Data stores
    ("s3_mlflow",   "S3: mlflow-artifacts",  "Data",           "aws",        "MLflow model artifacts"),
    ("s3_airflow",  "S3: airflow-data",       "Data",           "aws",        "Airflow DAG data / pipeline I/O"),
    ("secrets_mgr", "Secrets Manager",        "Data",           "aws",        "mlplatform/* all platform secrets"),
    ("ecr",         "ECR Repository",         "Data",           "aws",        "mlflow-sagemaker-deployment images"),

    # Networking services
    ("alb_ctrl",    "ALB Controller\n(kube-system)", "Platform","kube-system","Creates ALB from Ingress resources"),
    ("ext_dns",     "ExternalDNS\n(kube-system)","Platform",   "kube-system","Syncs Ingress hostnames → Route53"),
    ("eso",         "Ext. Secrets Operator",  "Platform",       "ext-secrets","Syncs Secrets Manager → K8s Secrets"),
]

# ─── 2. Platform Connections ───────────────────────────────────────────────────
# Each edge: (source_id, target_id, label)
EDGES = [
    # VPC topology
    ("vpc",         "pub_subnet",   "contains"),
    ("vpc",         "priv_subnet",  "contains"),
    ("vpc",         "db_subnet",    "contains"),
    ("igw",         "pub_subnet",   "routes"),
    ("pub_subnet",  "nat_gw",       "hosts"),
    ("nat_gw",      "priv_subnet",  "NAT egress"),
    ("pub_subnet",  "alb",          "hosts"),

    # EKS and nodes
    ("eks",         "ng0",          "manages"),
    ("eks",         "ng1",          "manages"),
    ("eks",         "ng2",          "manages"),
    ("priv_subnet", "ng0",          "runs in"),
    ("priv_subnet", "ng1",          "runs in"),
    ("priv_subnet", "ng2",          "runs in"),
    ("cluster_as",  "ng0",          "scales"),
    ("cluster_as",  "ng1",          "scales"),
    ("cluster_as",  "ng2",          "scales"),

    # IRSA
    ("oidc",        "iam_mlflow",   "federation"),
    ("oidc",        "iam_airflow",  "federation"),
    ("oidc",        "iam_sage",     "federation"),
    ("oidc",        "iam_eso",      "federation"),
    ("oidc",        "iam_extdns",   "federation"),

    # ALB + DNS
    ("alb",         "airflow_web",  "routes /airflow"),
    ("alb",         "mlflow",       "routes /mlflow"),
    ("alb",         "jh_proxy",     "routes /jupyterhub"),
    ("alb",         "grafana",      "routes /grafana"),
    ("alb",         "sagemaker",    "routes /sagemaker"),
    ("alb_ctrl",    "alb",          "provisions"),
    ("ext_dns",     "route53",      "syncs DNS"),
    ("acm",         "alb",          "TLS cert"),
    ("route53",     "alb",          "DNS → ALB"),

    # Auth
    ("github_oauth","airflow_web",  "OAuth provider"),
    ("github_oauth","jupyterhub",   "OAuth provider"),
    ("github_oauth","grafana",      "OAuth provider"),
    ("github_oauth","mlflow",       "OAuth provider"),
    ("github_oauth","sagemaker",    "OAuth provider"),

    # Airflow data flows
    ("airflow_sch", "ng1",          "spawns task pods"),
    ("airflow_web", "airflow_sch",  "UI → scheduler"),
    ("airflow_sch", "airflow_db",   "JDBC metadata"),
    ("airflow",     "s3_airflow",   "S3 API"),
    ("airflow",     "iam_airflow",  "IRSA"),
    ("airflow",     "mlflow",       "MLflow API"),

    # MLflow data flows
    ("mlflow",      "mlflow_db",    "JDBC backend store"),
    ("mlflow",      "s3_mlflow",    "S3 artifact store"),
    ("mlflow",      "iam_mlflow",   "IRSA"),

    # JupyterHub data flows
    ("jupyterhub",  "efs",          "ReadWriteMany"),
    ("jh_proxy",    "jupyterhub",   "manages servers"),

    # SageMaker
    ("sagemaker",   "ecr",          "push/pull images"),
    ("sagemaker",   "iam_sage",     "IRSA"),
    ("sagemaker",   "s3_mlflow",    "reads artifacts"),

    # Observability
    ("prometheus",  "ng0",          "scrapes /metrics"),
    ("prometheus",  "ng1",          "scrapes /metrics"),
    ("prometheus",  "airflow",      "scrapes metrics"),
    ("prometheus",  "mlflow",       "scrapes metrics"),
    ("grafana",     "prometheus",   "queries PromQL"),

    # Secrets
    ("eso",         "secrets_mgr",  "GetSecretValue"),
    ("eso",         "iam_eso",      "IRSA"),
    ("eso",         "airflow",      "injects secrets"),
    ("eso",         "mlflow",       "injects secrets"),
    ("eso",         "jupyterhub",   "injects secrets"),

    # EFS
    ("efs",         "priv_subnet",  "Mount Targets"),

    # Terraform state
    ("tf_state_s3", "vpc",          "stores state"),
    ("tf_state_s3", "eks",          "stores state"),
    ("tf_lock_ddb", "tf_state_s3",  "locks state"),

    # Per-user IAM
    ("iam_users",   "s3_mlflow",    "access"),
    ("iam_users",   "eks",          "kubectl access"),
]

# ─── 3. Layer Colours ─────────────────────────────────────────────────────────
LAYER_COLOURS = {
    "Infrastructure": "#2196F3",   # blue
    "Compute":        "#4CAF50",   # green
    "Platform":       "#FF9800",   # orange
    "Observability":  "#9C27B0",   # purple
    "Data":           "#F44336",   # red
    "Identity":       "#607D8B",   # blue-grey
}

LAYER_SIZES = {
    "Infrastructure": 16,
    "Compute":        18,
    "Platform":       22,
    "Observability":  20,
    "Data":           20,
    "Identity":       16,
}


def build_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    for node_id, label, layer, ns, desc in NODES:
        G.add_node(node_id, label=label, layer=layer, namespace=ns, description=desc)
    for src, dst, lbl in EDGES:
        G.add_edge(src, dst, label=lbl)
    return G


def layout_3d(G: nx.DiGraph) -> dict[str, np.ndarray]:
    """
    Spring layout in 3D, with a Y-axis bias so nodes separate
    by layer tier (Infrastructure at bottom, Platform at top).
    """
    layer_y = {
        "Infrastructure": 0.0,
        "Compute":        1.5,
        "Identity":       2.0,
        "Data":           2.5,
        "Platform":       3.5,
        "Observability":  4.5,
    }
    pos_2d = nx.spring_layout(G, seed=42, k=1.2)
    pos_3d: dict[str, np.ndarray] = {}
    for node_id in G.nodes:
        layer = G.nodes[node_id]["layer"]
        x, z = pos_2d[node_id]
        y = layer_y.get(layer, 2.0) + np.random.default_rng(abs(hash(node_id)) % (2**32)).uniform(-0.2, 0.2)
        pos_3d[node_id] = np.array([x * 3, y, z * 3])
    return pos_3d


def make_figure(G: nx.DiGraph, pos: dict[str, np.ndarray]) -> go.Figure:
    # ── Edge traces (one per edge for label hover) ───────────────────────────
    edge_traces = []
    for src, dst, data in G.edges(data=True):
        x0, y0, z0 = pos[src]
        x1, y1, z1 = pos[dst]
        # Midpoint for invisible hover marker
        xm, ym, zm = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
        edge_traces.append(go.Scatter3d(
            x=[x0, x1, None], y=[y0, y1, None], z=[z0, z1, None],
            mode="lines",
            line=dict(width=1.5, color="rgba(120,120,120,0.45)"),
            hoverinfo="none",
            showlegend=False,
        ))
        # hover label at midpoint
        edge_traces.append(go.Scatter3d(
            x=[xm], y=[ym], z=[zm],
            mode="markers",
            marker=dict(size=3, color="rgba(0,0,0,0)"),
            text=[data.get("label", "")],
            hovertemplate="<b>%{text}</b><extra></extra>",
            showlegend=False,
        ))

    # ── Node traces grouped by layer  ────────────────────────────────────────
    in_degree = dict(G.in_degree())
    node_traces = []
    for layer, colour in LAYER_COLOURS.items():
        layer_nodes = [n for n, d in G.nodes(data=True) if d["layer"] == layer]
        if not layer_nodes:
            continue
        xs, ys, zs, texts, hovers, sizes = [], [], [], [], [], []
        for nid in layer_nodes:
            x, y, z = pos[nid]
            nd = G.nodes[nid]
            xs.append(x); ys.append(y); zs.append(z)
            texts.append(nd["label"].replace("\n", "<br>"))
            hovers.append(
                f"<b>{nd['label']}</b><br>"
                f"Layer: {nd['layer']}<br>"
                f"Namespace: {nd['namespace']}<br>"
                f"{nd['description']}<br>"
                f"In-degree: {in_degree.get(nid, 0)}"
            )
            base_size = LAYER_SIZES.get(layer, 16)
            sizes.append(base_size + in_degree.get(nid, 0) * 1.5)

        node_traces.append(go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="markers+text",
            name=layer,
            text=texts,
            textposition="top center",
            textfont=dict(size=8, color=colour),
            marker=dict(
                size=sizes,
                color=colour,
                opacity=0.85,
                line=dict(width=1, color="rgba(255,255,255,0.6)"),
            ),
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
        ))

    fig = go.Figure(data=edge_traces + node_traces)

    fig.update_layout(
        title=dict(
            text="MLOps Platform on EKS — 3D Architecture Graph",
            font=dict(size=18, color="white"),
            x=0.5,
        ),
        scene=dict(
            xaxis=dict(showbackground=False, showgrid=False, zeroline=False, showticklabels=False, title=""),
            yaxis=dict(showbackground=False, showgrid=False, zeroline=False, showticklabels=False, title="Layer (bottom=Infra, top=Apps)"),
            zaxis=dict(showbackground=False, showgrid=False, zeroline=False, showticklabels=False, title=""),
            bgcolor="rgb(10,10,20)",
            camera=dict(eye=dict(x=1.5, y=0.8, z=1.5)),
        ),
        paper_bgcolor="rgb(10,10,20)",
        plot_bgcolor="rgb(10,10,20)",
        legend=dict(
            title="Layer",
            font=dict(color="white"),
            bgcolor="rgba(30,30,50,0.8)",
            bordercolor="rgba(255,255,255,0.3)",
            borderwidth=1,
        ),
        margin=dict(l=0, r=0, b=0, t=60),
        hoverlabel=dict(bgcolor="rgba(30,30,60,0.95)", font_size=12, font_color="white"),
    )

    # Annotation: layer guide
    fig.add_annotation(
        text=(
            "<b>Layer guide</b>: "
            "🔵&nbsp;Infrastructure &nbsp;|&nbsp; "
            "🟢&nbsp;Compute &nbsp;|&nbsp; "
            "🟠&nbsp;Platform &nbsp;|&nbsp; "
            "🟣&nbsp;Observability &nbsp;|&nbsp; "
            "🔴&nbsp;Data &nbsp;|&nbsp; "
            "⚫&nbsp;Identity<br>"
            "Node size ∝ number of incoming connections. Rotate: left-drag. Zoom: scroll. Pan: right-drag."
        ),
        xref="paper", yref="paper",
        x=0.5, y=0.01,
        showarrow=False,
        font=dict(size=10, color="rgba(200,200,200,0.7)"),
        align="center",
    )

    return fig


def main() -> None:
    print("Building graph…")
    G = build_graph()
    print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")

    print("Computing 3D layout…")
    pos = layout_3d(G)

    print("Rendering figure…")
    fig = make_figure(G, pos)

    output_path = Path(__file__).parent / "architecture_3d.html"
    fig.write_html(str(output_path), include_plotlyjs="cdn", full_html=True)
    print(f"Saved -> {output_path}")

    webbrowser.open(output_path.as_uri())
    print("Opened in browser.")


if __name__ == "__main__":
    main()
