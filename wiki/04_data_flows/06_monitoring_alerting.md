# Data Flow — Monitoring & Alerting

> **Scenario**: Prometheus continuously scrapes all platform components; Grafana visualizes dashboards; GitHub OAuth controls read access.  
> **Actors**: Prometheus, Grafana, Platform components (Airflow, MLflow, JupyterHub, K8s), Data Scientists / Admins

---

## Overview

```mermaid
graph LR
    subgraph SCRAPED["Scraped Targets"]
        AF_M[Airflow\n/metrics :9090]
        MLF_M[MLflow\n/metrics :5000]
        JHB_M[JupyterHub Hub\n/hub/metrics]
        K8S_M[kube-state-metrics\n:8080]
        NODE_M[node-exporter\n:9100]
        CADV[cAdvisor\n(built into kubelet)]
    end

    PROM["Prometheus Server\n(prometheus-server.monitoring.svc)\nPort 80"]
    PROM_TSDB["Prometheus TSDB\n(local PVC 2Gi)\nRetention: 15d"]
    GRAF["Grafana\n/grafana endpoint\nGitHub OAuth"]
    DASH_ID["Grafana Dashboards\n• ID 2: Prometheus Stats\n• ID 315: K8s Cluster\n• ID 6417: K8s Detail"]

    AF_M & MLF_M & JHB_M & K8S_M & NODE_M & CADV -->|"HTTP GET /metrics\nevery 15s (default)"| PROM
    PROM --> PROM_TSDB
    GRAF -->|"PromQL queries\nHTTP GET"| PROM
    GRAF --> DASH_ID

    style PROM fill:#e8f5e9
    style GRAF fill:#e3f2fd
    style PROM_TSDB fill:#fff3e0
```

---

## Detailed Sequence: Prometheus Scrape Cycle

```mermaid
sequenceDiagram
    participant PROM2 as Prometheus Server\n(monitoring namespace)
    participant KSM as kube-state-metrics\n(monitoring namespace)
    participant NE as node-exporter\n(DaemonSet, kube-system)
    participant KUBELET as Kubelet\n(each node) + cAdvisor
    participant AF_POD as Airflow Webserver Pod\n(airflow namespace)
    participant TSDB as Prometheus TSDB\n(local PVC)
    participant GRAF2 as Grafana
    participant USER as Data Scientist / Admin

    Note over PROM2: Scrape cycle (every 15 seconds by default)
    
    par Cluster-level metrics
        PROM2->>KSM: GET http://kube-state-metrics:8080/metrics
        KSM->>PROM2: Deployment/Pod/Node/PVC status metrics
    and Node-level metrics
        PROM2->>NE: GET http://{node-ip}:9100/metrics
        NE->>PROM2: CPU, memory, disk, network per node
    and Container metrics
        PROM2->>KUBELET: GET https://{node-ip}:10250/metrics/cadvisor
        KUBELET->>PROM2: Container CPU/memory/filesystem usage
    and Application metrics
        PROM2->>AF_POD: GET http://airflow-web.airflow.svc:9090/metrics\n(Airflow StatsD → Prometheus exporter)
        AF_POD->>PROM2: DAG run counts, task durations, scheduler heartbeat
    end

    PROM2->>TSDB: Write time series data\n(compressed, chunked blocks)

    Note over TSDB: Time series stored with labels:\n{job, instance, namespace, pod, container}
    
    Note over GRAF2: Dashboard refresh (user navigates to /grafana)
    USER->>GRAF2: Navigate to /grafana
    GRAF2->>GRAF2: Validate GitHub OAuth session
    GRAF2->>PROM2: PromQL: rate(container_cpu_usage_seconds_total[5m])
    PROM2->>TSDB: Range query [now-1h to now]
    TSDB->>PROM2: Matched time series
    PROM2->>GRAF2: Return data points (JSON)
    GRAF2->>USER: Render graph panel

    Note over GRAF2: Alert evaluation (if AlertManager configured)
    PROM2->>PROM2: Evaluate alert rules every 1m
    Note right of PROM2: Currently: AlertManager NOT deployed\n(prometheus.alertmanager.enabled=false)
```

---

## Grafana Authentication Flow

```mermaid
sequenceDiagram
    actor USER2 as Platform User
    participant Browser2
    participant ALB4 as AWS ALB\n/grafana
    participant GRAF3 as Grafana
    participant GH6 as GitHub OAuth
    
    USER2->>Browser2: Navigate to https://domain.com/grafana
    Browser2->>ALB4: GET /grafana
    ALB4->>GRAF3: Forward request
    GRAF3->>Browser2: 302 Redirect to GitHub OAuth\n/login/oauth/authorize
    Browser2->>GH6: Authorize request\n(scopes: user:email, read:org)
    GH6->>USER2: Show authorize screen
    USER2->>GH6: Approve
    GH6->>Browser2: Callback with code
    Browser2->>GRAF3: POST /grafana/login/github?code=...
    GRAF3->>GH6: Exchange code → access token
    GRAF3->>GH6: GET /user (username + email)
    GRAF3->>GH6: GET /orgs (check allowed_organizations)
    
    alt User in allowed org
        GRAF3->>GRAF3: Map GitHub teams → Grafana roles\n(default: Viewer for org members)
        GRAF3->>Browser2: Set Grafana session cookie
        GRAF3->>USER2: Render Grafana home
    else User not in org
        GRAF3->>USER2: 403 Forbidden
    end
```

---

## Prometheus Targets Configuration

### ServiceMonitor Targets (via CRDs — Prometheus Operator)

```yaml
# ServiceMonitor for Airflow (example)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: airflow
  namespace: monitoring
spec:
  namespaceSelector:
    matchNames: [airflow]
  selector:
    matchLabels:
      app: airflow
  endpoints:
    - port: metrics
      interval: 15s
      path: /metrics
```

### Prometheus Static Scrape Config (fallback for apps without ServiceMonitor)

```yaml
scrape_configs:
  - job_name: "kubernetes-pods"
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: "true"
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod

  - job_name: "kube-state-metrics"
    static_configs:
      - targets: ["kube-state-metrics.monitoring.svc.cluster.local:8080"]

  - job_name: "node-exporter"
    kubernetes_sd_configs:
      - role: node
    relabel_configs:
      - source_labels: [__address__]
        action: replace
        regex: (.+):(.+)
        replacement: ${1}:9100
        target_label: __address__
```

---

## Grafana Dashboard Breakdown

```mermaid
graph TB
    subgraph DASHBOARDS["Grafana Dashboards Configured"]
        D2["Dashboard ID: 2\nPrometheus 2.0 Stats\n• Total time series\n• Samples/sec ingestion\n• Active targets\n• TSDB size"]
        
        D315["Dashboard ID: 315\nKubernetes cluster monitoring\n(via Prometheus)\n• CPU usage per namespace\n• Memory usage\n• Network I/O\n• Pod count by namespace"]
        
        D6417["Dashboard ID: 6417\nKubernetes Cluster\n(Prometheus)\n• Node resource utilisation\n• Pod resource requests vs limits\n• Persistent volume usage\n• Deployment replica status"]
    end

    subgraph DATASOURCE["Data Source"]
        DS3["prometheus-server.monitoring.svc.cluster.local\nPort 80"]
    end

    D2 & D315 & D6417 -->|PromQL| DS3
```

---

## Key Metrics to Monitor

| Metric | Component | PromQL Example | Alert Threshold |
|--------|-----------|---------------|-----------------|
| Node CPU usage | EC2 + kube-system | `1 - avg(irate(node_cpu_seconds_total{mode="idle"}[5m]))` | > 80% |
| Pod memory RSS | All namespaces | `container_memory_rss{namespace="airflow"}` | > node capacity |
| DAG run duration | Airflow | `airflow_dagrun_duration_success` | > SLA |
| Task failure rate | Airflow | `rate(airflow_ti_failures_total[5m])` | > 0 per 5m |
| MLflow request latency | MLflow | `flask_http_request_duration_seconds` | > 2s p99 |
| EFS IOPS | EFS via node-exporter | `node_filesystem_files_free` | < 10% free |
| PVC usage | All | `kubelet_volume_stats_used_bytes` | > 80% |
| Node count | EC2 Auto Scaling | `kube_node_status_condition{status="true",condition="Ready"}` | < min nodes |

---

## Monitoring Stack Deployment Detail

```mermaid
graph TB
    subgraph HELM_RELEASES["Helm Releases — monitoring namespace"]
        CRD_RELEASE["prometheus-operator-crds\n(prometheus-community 5.1.0)\nCRDs: ServiceMonitor, PodMonitor,\nPrometheusRule, Alertmanager, etc."]
        
        PROM_RELEASE["kube-prometheus-stack\n(prometheus-community 19.7.2)\nComponents deployed:\n• prometheus-server (Deployment)\n• kube-state-metrics (Deployment)\n• node-exporter (DaemonSet)\n• prometheus config (ConfigMap)\nalertmanager.enabled: false\npushgateway.enabled: false"]
        
        GRAF_RELEASE["grafana\n(grafana.github.io 6.57.4)\nComponents:\n• grafana (Deployment)\n• Persistent volume 1Gi\n• GitHub OAuth enabled\n• 3 dashboards auto-provisioned"]
    end

    CRD_RELEASE -->|"CRDs must exist before"| PROM_RELEASE
    PROM_RELEASE -->|"Metrics available"| GRAF_RELEASE
```

---

## AWS Services Involved

| Service | Role |
|---------|------|
| **EKS** | Runs Prometheus, Grafana, kube-state-metrics, node-exporter |
| **EBS** | PersistentVolumeClaims for Prometheus TSDB and Grafana data |
| **ALB** | Routes `/grafana` and `/monitoring` traffic |
| **Route 53** | DNS for Grafana domain |
| **GitHub** | OAuth for Grafana authentication |

---

## Missing Capabilities (Current Gaps)

| Gap | Impact | Recommended Solution |
|-----|--------|---------------------|
| AlertManager disabled | No notifications on failures | Enable `alertmanager.enabled=true`; configure PagerDuty/Slack routes |
| No ML-specific metrics | No experiment tracking visibility | Add MLflow custom Prometheus exporter |
| No log aggregation | Logs scattered per pod | Add Fluent Bit → CloudWatch Logs or Loki stack |
| Prometheus retention 15d | Limited historical analysis | Extend retention or add Thanos/Cortex for long-term storage |
| No business metrics | No SLA tracking | Instrument Airflow DAG-level metrics with StatsD |
