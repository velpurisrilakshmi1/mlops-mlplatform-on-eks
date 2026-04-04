"""
MLOps Platform on EKS — Interactive Network Graph (PyVis)

Renders the full platform topology as a physics-simulated
interactive network in your browser. Nodes are grouped and
coloured by K8s namespace / AWS layer. Edge labels show the
type of connection between components.

Usage:
    python pyvis_network.py
    # Opens mlops_platform.html in your default browser
"""

import webbrowser
from pathlib import Path

from pyvis.network import Network

# ─── Colour scheme (namespace / AWS group) ────────────────────────────────────
GROUP_COLOURS: dict[str, str] = {
    "aws-infra":       "#2196F3",   # blue
    "aws-compute":     "#4CAF50",   # green
    "aws-data":        "#F44336",   # red
    "aws-identity":    "#607D8B",   # blue-grey
    "airflow":         "#FF9800",   # orange
    "mlflow":          "#9C27B0",   # purple
    "jupyterhub":      "#00BCD4",   # cyan
    "monitoring":      "#E91E63",   # pink
    "sagemaker":       "#8BC34A",   # light-green
    "kube-system":     "#795548",   # brown
    "external-secrets":"#FF5722",   # deep-orange
    "external":        "#9E9E9E",   # grey (3rd-party services)
    "tf-backend":      "#FFEB3B",   # yellow
}

# ─── 1. Nodes ─────────────────────────────────────────────────────────────────
# (id, label, group, size, title/tooltip)
NODES = [
    # AWS Infra
    ("vpc",          "VPC",              "aws-infra",       25, "10.0.0.0/16 — VPC boundary"),
    ("pub_subnet",   "Public\nSubnets",  "aws-infra",       18, "3 × public subnets (one per AZ)"),
    ("priv_subnet",  "Private\nSubnets", "aws-infra",       18, "3 × private subnets for EKS nodes"),
    ("db_subnet",    "DB Subnets",       "aws-infra",       14, "Isolated subnets for RDS"),
    ("igw",          "IGW",              "aws-infra",       14, "Internet Gateway"),
    ("nat_gw",       "NAT GW",           "aws-infra",       16, "NAT Gateway (AZ1) — egress for nodes"),
    ("route53",      "Route 53",         "aws-infra",       20, "Hosted zone → maps domain to ALB IPs"),
    ("acm",          "ACM\nCert",        "aws-infra",       14, "TLS certificate for *.domain"),

    # AWS Compute
    ("alb",          "ALB",              "aws-compute",     30, "Application Load Balancer — path routing"),
    ("eks",          "EKS\nCluster",     "aws-compute",     35, "EKS 1.24, private endpoint"),
    ("ng0",          "ng0\nt3.small",    "aws-compute",     16, "0–5 nodes, spillover workloads"),
    ("ng1",          "ng1\nt3.medium",   "aws-compute",     20, "4–6 nodes, base platform (always on)"),
    ("ng2",          "ng2\nt3.large",    "aws-compute",     16, "0–3 nodes, NoSchedule, heavy ML only"),
    ("efs",          "EFS",              "aws-compute",     18, "ReadWriteMany — notebooks, DAG logs"),

    # AWS Data
    ("s3_mlflow",    "S3\nArtifacts",    "aws-data",        22, "MLflow model artifacts"),
    ("s3_airflow",   "S3\nData",         "aws-data",        22, "Airflow pipeline data / I/O"),
    ("rds_pg",       "RDS\nPostgreSQL",  "aws-data",        24, "Airflow metadata DB, port 5000"),
    ("rds_mysql",    "RDS\nMySQL",       "aws-data",        24, "MLflow backend store, port 5432"),
    ("secrets_mgr",  "Secrets\nManager", "aws-data",        20, "mlplatform/* all platform secrets"),
    ("ecr",          "ECR",              "aws-data",        18, "mlflow-sagemaker-deployment images"),

    # AWS Identity
    ("oidc",         "OIDC\nProvider",   "aws-identity",    20, "EKS OIDC → enables IRSA"),
    ("iam_mlflow",   "IRSA\nMLflow",     "aws-identity",    14, "S3 read/write on mlflow prefix"),
    ("iam_airflow",  "IRSA\nAirflow",    "aws-identity",    14, "S3 read/write on airflow prefix"),
    ("iam_sage",     "IRSA\nSageMaker",  "aws-identity",    14, "SageMaker + ECR + S3 access"),
    ("iam_eso",      "IRSA\nESO",        "aws-identity",    14, "Secrets Manager:GetSecretValue"),
    ("iam_extdns",   "IRSA\nExtDNS",     "aws-identity",    14, "Route53:ChangeResourceRecordSets"),
    ("iam_users",    "User IAM\nRoles",  "aws-identity",    18, "Per-user developer or user role"),

    # External
    ("github",       "GitHub\n(OAuth)",  "external",        22, "OAuth2 provider for all platform UIs"),
    ("git_repo",     "DAG Git\nRepo",    "external",        16, "Airflow DAG repository (git-sync source)"),

    # Terraform backend
    ("tf_s3",        "TF State\n(S3)",   "tf-backend",      16, "S3: mlplatform-terraform-state"),
    ("tf_ddb",       "TF Lock\n(DDB)",   "tf-backend",      14, "DynamoDB: mlplatform-terraform-locks"),

    # kube-system
    ("alb_ctrl",     "ALB\nController",  "kube-system",     18, "Provisions ALB from Ingress resources"),
    ("ext_dns",      "ExternalDNS",      "kube-system",     18, "Syncs Ingress hostnames → Route53"),
    ("ca",           "Cluster\nAutoscaler","kube-system",   18, "Scales node groups on pending pods"),

    # external-secrets
    ("eso",          "Ext. Secrets\nOperator","external-secrets",20, "Syncs AWS Secrets Manager → K8s Secrets"),

    # airflow namespace
    ("airflow_web",  "Airflow\nWebserver","airflow",         26, "Airflow UI + REST API, port 8080"),
    ("airflow_sch",  "Airflow\nScheduler","airflow",         22, "DAG parsing + KubernetesExecutor"),
    ("airflow_gitsync","git-sync\nsidecar","airflow",        14, "Pulls DAGs from GitHub every 60s"),

    # mlflow namespace
    ("mlflow_svc",   "MLflow\nServer",   "mlflow",          26, "Experiment tracking + Model Registry"),
    ("mlflow_proxy", "OAuth\nProxy",     "mlflow",          14, "Authenticates MLflow requests via GitHub OAuth"),

    # jupyterhub namespace
    ("jh_hub",       "JupyterHub\nHub",  "jupyterhub",      26, "Spawns single-user notebook servers"),
    ("jh_proxy",     "JH\nProxy",        "jupyterhub",      18, "Routes traffic to user servers"),
    ("jh_user",      "User\nNotebook",   "jupyterhub",      16, "jupyter-<username> pod, EFS-mounted"),

    # monitoring
    ("prometheus",   "Prometheus",       "monitoring",      26, "Scrapes all /metrics endpoints"),
    ("grafana",      "Grafana",          "monitoring",      26, "Dashboards (IDs 2, 315, 6417)"),

    # sagemaker
    ("sage_dash",    "Streamlit\nDashboard","sagemaker",    22, "SageMaker endpoint manager UI"),
]

# ─── 2. Edges ─────────────────────────────────────────────────────────────────
# (from, to, label, bidirectional)
EDGES = [
    # Internet → ALB
    ("igw",         "alb",          "routes",               False),
    ("acm",         "alb",          "TLS cert",             False),
    ("alb",         "route53",      "DNS A record",         False),
    ("ext_dns",     "route53",      "upserts records",      False),
    ("alb_ctrl",    "alb",          "provisions",           False),

    # ALB → Apps
    ("alb",         "airflow_web",  "/airflow",             False),
    ("alb",         "mlflow_proxy", "/mlflow",              False),
    ("alb",         "jh_proxy",     "/jupyterhub",          False),
    ("alb",         "grafana",      "/grafana",             False),
    ("alb",         "sage_dash",    "/sagemaker",           False),

    # OAuth
    ("github",      "airflow_web",  "OAuth",                False),
    ("github",      "jh_hub",       "OAuth",                False),
    ("github",      "grafana",      "OAuth",                False),
    ("github",      "mlflow_proxy", "OAuth",                False),
    ("github",      "sage_dash",    "OAuth",                False),

    # EKS topology
    ("eks",         "ng0",          "manages",              False),
    ("eks",         "ng1",          "manages",              False),
    ("eks",         "ng2",          "manages",              False),
    ("ca",          "ng0",          "autoscales",           False),
    ("ca",          "ng1",          "autoscales",           False),
    ("ca",          "ng2",          "autoscales",           False),

    # IRSA federation
    ("oidc",        "iam_mlflow",   "assumes",              False),
    ("oidc",        "iam_airflow",  "assumes",              False),
    ("oidc",        "iam_sage",     "assumes",              False),
    ("oidc",        "iam_eso",      "assumes",              False),
    ("oidc",        "iam_extdns",   "assumes",              False),
    ("eks",         "oidc",         "issues tokens",        False),

    # External DNS IRSA
    ("ext_dns",     "iam_extdns",   "IRSA",                 False),

    # Airflow flows
    ("airflow_gitsync","git_repo",  "git pull",             False),
    ("airflow_sch", "airflow_gitsync","side-car",           False),
    ("airflow_sch", "rds_pg",       "JDBC metadata",        True),
    ("airflow_sch", "ng1",          "spawns task pods",     False),
    ("airflow_sch", "s3_airflow",   "S3 API",               True),
    ("airflow_sch", "mlflow_svc",   "tracking API",         False),
    ("airflow_web", "airflow_sch",  "RPC/REST",             True),
    ("airflow_sch", "iam_airflow",  "IRSA",                 False),

    # MLflow flows
    ("mlflow_svc",  "rds_mysql",    "JDBC backend",         True),
    ("mlflow_svc",  "s3_mlflow",    "S3 artifact store",    True),
    ("mlflow_svc",  "iam_mlflow",   "IRSA",                 False),
    ("mlflow_proxy","mlflow_svc",   "proxy",                False),

    # JupyterHub flows
    ("jh_proxy",    "jh_hub",       "proxy",                True),
    ("jh_hub",      "jh_user",      "spawns",               False),
    ("jh_user",     "efs",          "ReadWriteMany",        True),
    ("jh_user",     "mlflow_svc",   "tracking API",         False),

    # Observability
    ("prometheus",  "airflow_web",  "scrape /metrics",      False),
    ("prometheus",  "mlflow_svc",   "scrape /metrics",      False),
    ("prometheus",  "jh_hub",       "scrape /metrics",      False),
    ("prometheus",  "ng0",          "node-exporter",        False),
    ("prometheus",  "ng1",          "node-exporter",        False),
    ("grafana",     "prometheus",   "PromQL queries",       False),

    # ESO flows
    ("eso",         "secrets_mgr",  "GetSecretValue",       False),
    ("eso",         "iam_eso",      "IRSA",                 False),
    ("eso",         "airflow_web",  "injects secrets",      False),
    ("eso",         "mlflow_svc",   "injects secrets",      False),
    ("eso",         "jh_hub",       "injects secrets",      False),

    # SageMaker
    ("sage_dash",   "ecr",          "push/pull images",     True),
    ("sage_dash",   "iam_sage",     "IRSA",                 False),
    ("sage_dash",   "s3_mlflow",    "reads artifacts",      False),

    # Networking
    ("vpc",         "pub_subnet",   "contains",             False),
    ("vpc",         "priv_subnet",  "contains",             False),
    ("vpc",         "db_subnet",    "contains",             False),
    ("nat_gw",      "priv_subnet",  "NAT egress",           False),
    ("efs",         "priv_subnet",  "Mount Targets",        False),
    ("rds_pg",      "db_subnet",    "runs in",              False),
    ("rds_mysql",   "db_subnet",    "runs in",              False),

    # Terraform state
    ("tf_ddb",      "tf_s3",        "locks",                False),

    # User IAM
    ("iam_users",   "eks",          "kubectl access",       False),
    ("iam_users",   "s3_mlflow",    "S3 access",            False),
]


def build_network() -> Network:
    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#0d1117",
        font_color="#c9d1d9",
        directed=True,
        notebook=False,
        cdn_resources="remote",
    )

    # Physics config (Barnes-Hut for large graphs)
    net.set_options("""
    {
      "nodes": {
        "font": { "size": 11, "face": "Inter, Arial, sans-serif" },
        "borderWidth": 2,
        "borderWidthSelected": 4,
        "shadow": { "enabled": true, "size": 6, "x": 3, "y": 3 }
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.6 } },
        "color": { "color": "rgba(120,120,140,0.5)", "highlight": "#58a6ff" },
        "font": { "size": 9, "face": "Inter, Arial, sans-serif",
                  "color": "rgba(180,180,200,0.75)", "strokeWidth": 0 },
        "smooth": { "type": "curvedCW", "roundness": 0.15 },
        "width": 1.2,
        "selectionWidth": 2.5
      },
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.3,
          "springLength": 160,
          "springConstant": 0.04,
          "damping": 0.09,
          "avoidOverlap": 0.5
        },
        "stabilization": { "iterations": 200 }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 150,
        "navigationButtons": true,
        "keyboard": true,
        "multiselect": true
      }
    }
    """)

    # Add nodes
    for node_id, label, group, size, title in NODES:
        colour = GROUP_COLOURS.get(group, "#9E9E9E")
        net.add_node(
            node_id,
            label=label,
            title=f"<b>{label.replace(chr(10), ' ')}</b><br>{title}<br><i>Group: {group}</i>",
            color={
                "background": colour,
                "border": "#ffffff",
                "highlight": {"background": "#ffffff", "border": colour},
                "hover": {"background": "#ffffff", "border": colour},
            },
            size=size,
            group=group,
            font={"color": "#ffffff" if group not in ("tf-backend",) else "#000000"},
        )

    # Add edges
    for src, dst, label, bidirectional in EDGES:
        net.add_edge(
            src, dst,
            title=label,
            label=label,
            arrows="to;from" if bidirectional else "to",
        )

    return net


def add_legend(net: Network) -> None:
    """Inject a colour legend as an HTML overlay into the generated file."""
    legend_html = """
<style>
  #legend {
    position: fixed; top: 12px; left: 12px; z-index: 9999;
    background: rgba(22,27,34,0.93); border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px; padding: 10px 14px; font-family: Inter, Arial, sans-serif;
    font-size: 12px; color: #c9d1d9; max-width: 200px; line-height: 1.8;
  }
  #legend h4 { margin: 0 0 6px; font-size: 13px; color: #58a6ff; }
  .leg-dot { display: inline-block; width:12px; height:12px;
             border-radius:50%; margin-right:6px; vertical-align:middle; }
</style>
<div id="legend">
  <h4>Namespace / Layer</h4>
  <div><span class="leg-dot" style="background:#2196F3"></span>AWS Infrastructure</div>
  <div><span class="leg-dot" style="background:#4CAF50"></span>AWS Compute</div>
  <div><span class="leg-dot" style="background:#F44336"></span>AWS Data Stores</div>
  <div><span class="leg-dot" style="background:#607D8B"></span>Identity (IAM / IRSA)</div>
  <div><span class="leg-dot" style="background:#FF9800"></span>airflow</div>
  <div><span class="leg-dot" style="background:#9C27B0"></span>mlflow</div>
  <div><span class="leg-dot" style="background:#00BCD4"></span>jupyterhub</div>
  <div><span class="leg-dot" style="background:#E91E63"></span>monitoring</div>
  <div><span class="leg-dot" style="background:#8BC34A"></span>sagemaker</div>
  <div><span class="leg-dot" style="background:#795548"></span>kube-system</div>
  <div><span class="leg-dot" style="background:#FF5722"></span>external-secrets</div>
  <div><span class="leg-dot" style="background:#9E9E9E"></span>External Services</div>
  <div><span class="leg-dot" style="background:#FFEB3B"></span>Terraform Backend</div>
  <br>
  <small>Drag nodes | Scroll to zoom | Click to highlight | ⌘/Ctrl+click multi-select</small>
</div>
"""
    # PyVis stores the full HTML — inject legend before </body>
    return legend_html


def main() -> None:
    print("Building network graph…")
    net = build_network()

    output_path = Path(__file__).parent / "mlops_platform.html"
    net.write_html(str(output_path))

    # Inject legend
    html = output_path.read_text(encoding="utf-8")
    legend = add_legend(net)
    html = html.replace("</body>", f"{legend}</body>")
    output_path.write_text(html, encoding="utf-8")

    print(f"Saved -> {output_path}")
    webbrowser.open(output_path.as_uri())
    print("Opened in browser.")


if __name__ == "__main__":
    main()
