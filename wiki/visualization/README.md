# MLOps Platform — 3D Architecture Visualization

This folder contains **interactive Python scripts** that render the MLOps platform architecture as navigable 3D and network graphs. They read no external data — all architecture topology is embedded in the scripts based on the documented platform structure.

---

## Scripts

| File | Visualization | Output |
|------|--------------|--------|
| `plotly_3d_architecture.py` | 3D spring-layout node graph (all components layered by tier) | `architecture_3d.html` |
| `pyvis_network.py` | Interactive network graph (namespace grouping, edge labels, physics) | `mlops_platform.html` |

---

## Installation

```bash
cd wiki/visualization
pip install -r requirements.txt
```

Requires Python 3.9+.

---

## Running

```bash
# 3D architecture graph (Plotly)
python plotly_3d_architecture.py
# → Opens architecture_3d.html in default browser automatically

# Interactive network graph (PyVis)
python pyvis_network.py
# → Opens mlops_platform.html in default browser automatically
```

---

## Plotly 3D Graph (`architecture_3d.html`)

- **Axes**: X/Y/Z are the 3D spring-layout coordinates computed by NetworkX
- **Node color** = layer tier:
  - 🔵 Blue = Infrastructure (VPC, subnets, NAT, Route53, ACM)
  - 🟢 Green = Compute (EKS, node groups)
  - 🟠 Orange = Platform applications (Airflow, MLflow, JupyterHub, etc.)
  - 🟣 Purple = Observability (Prometheus, Grafana)
  - 🔴 Red = Data stores (RDS, S3, Secrets Manager, EFS)
  - ⚪ Grey = Identity / Security (IAM, GitHub OAuth)
- **Node size** = number of incoming edges (more connections = larger sphere)
- **Hover tooltip** = component name + namespace + layer
- Controls: rotate (left-drag), zoom (scroll), pan (right-drag)

---

## PyVis Network Graph (`mlops_platform.html`)

- **Node color** = K8s namespace or AWS service group
- **Physics simulation** enabled (Barnes-Hut) — drag nodes to explore
- **Edge labels** = data/connection type (e.g., "JDBC", "OAuth", "S3 API", "Helm")
- **Click** a node to highlight its direct connections
- Toggle physics on/off with the control panel in the top-right

---

## Customising

Both scripts have a `NODES` and `EDGES` data structure at the top of the file. Edit these lists to:
- Add new components as you extend the platform
- Remove components that are not deployed in your environment
- Adjust node metadata (namespace, layer, description)
