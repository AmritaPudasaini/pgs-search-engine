# Large-Scale Recursive Scraping Architecture

To scrape 100,000 domains recursively every 15 minutes, we are dealing with millions of pages and assets per cycle. This requires a highly decoupled, asynchronous architecture where the control plane (Temporal) manages the state and retries, while the compute plane (Kubernetes) handles the raw execution.

Here is the top-down architecture and the specific Kubernetes scaling strategy, strictly focused on the scrape-and-save lifecycle.

## 1. Top-Down Architecture

### The Control Plane: Temporal Workflows

Temporal acts as our orchestrator and state manager, ensuring no page is scraped twice in a cycle and handling network timeouts automatically.

* **Master Cron Workflow:** A Temporal Cron Workflow triggers every 15 minutes. It queries our database for the 100,000 root domains.

* **Domain Child Workflows:** The Master Workflow spins up a Child Workflow for each domain (100,000 concurrent workflows). This isolates domain-specific logic (e.g., rate limits per domain).

* **Scraping Activities (The Workers):** The Domain Workflow parses the root page, identifies subpages/assets, and dispatches individual **Temporal Activities** (e.g., `ScrapeHTML`, `DownloadAsset`) to a specific Temporal Task Queue.

### The Compute Plane: Kubernetes & Docker

Our Docker containers run Temporal Workers listening to the Task Queue.

* **HTML/DOM Scraper Pods:** Optimized for CPU/RAM if running headless browsers (Puppeteer/Playwright), or strictly network I/O if doing raw HTTP requests (Go/Rust/Python requests).

* **Asset Downloader Pods:** Separate worker pools specifically for downloading and streaming large files (images, PDFs) to avoid blocking HTML parsing workers.

* **DNS Caching Layer:** At this scale, we will overwhelm standard DNS resolvers. Inject a local DNS cache (like CoreDNS or NodeLocal DNSCache) as a DaemonSet on our K8s nodes.

### The Storage Plane: Direct-to-Storage (Ceph RGW)

* **Raw Assets & HTML:** Workers stream downloaded binaries and raw HTML directly into **Ceph RGW (RADOS Gateway)**. Because RGW is S3-compatible, our workers can use standard S3 SDKs to stream data in chunks, preventing memory bloat on the worker pods.

* **Metadata & Crawl State:** Workers write the object locations (RGW S3 URIs) and crawl metadata (timestamps, HTTP status) into a high-write-throughput database.

## 2. Configuring and Triggering the Kubernetes HPA

For Temporal workers, standard CPU/Memory scaling is often too slow or inaccurate—a worker might sit idle waiting on network I/O while the Temporal Task Queue backs up with millions of scraping tasks.

We should use **KEDA (Kubernetes Event-driven Autoscaling)** to scale based on the Temporal queue length, falling back to CPU/Memory as a safety net.

### Option A: The Expert Approach (Queue-Based Scaling via KEDA)

KEDA allows us to autoscale our Kubernetes Pods based on custom metrics. We will configure KEDA to read Temporal's Prometheus metrics.

**How it triggers:** When the Master Workflow dumps 100,000 domains into the queue, the pending tasks metric spikes. KEDA instantly scales the deployment from 100 pods to 5,000 pods. As the queue drains, it scales back down.

**Configuration (ScaledObject):**

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: temporal-scraper-scaler
  namespace: scraping-ops
spec:
  scaleTargetRef:
    name: scraper-worker-deployment
  minReplicaCount: 50
  maxReplicaCount: 5000
  pollingInterval: 15     # Check the queue every 15 seconds
  cooldownPeriod:  300    # Wait 5 mins before scaling down
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus-server.monitoring.svc.cluster.local:9090
      metricName: temporal_task_queue_backlog
      # Scale up if there are more than 50 pending scraping tasks per pod
      threshold: '50'
      query: |
        sum(temporal_task_queue_backlog{task_queue="scraping-task-queue"})
```

### Option B: Standard HPA (Resource-Based Scaling)

If we cannot install KEDA, we must rely on the standard Kubernetes Horizontal Pod Autoscaler based on CPU utilization.

**How it triggers:** As our Temporal workers pick up tasks and execute heavy I/O or headless browser rendering, their CPU usage spikes. The Kubernetes Metrics Server detects this and spins up more pods to distribute the load.

**Configuration (HPA):**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: scraper-cpu-hpa
  namespace: scraping-ops
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: scraper-worker-deployment
  minReplicas: 50
  maxReplicas: 5000
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 75 # Triggers scale up when average CPU hits 75%
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80 # Triggers scale up when memory hits 80%
```

### Architecture Summary for Kubernetes Deployment

1. Define a deployment for our Temporal Workers (`scraper-worker-deployment`).

2. Do **not** set aggressive `limits` on CPU, only `requests`, so scrapers can burst during heavy DOM parsing.

3. Apply the HPA or KEDA ScaledObject pointing to that deployment.

4. The 15-minute Temporal Cron natively provides the pulse; Kubernetes dynamically expands the compute footprint to swallow the work, streams the massive data volumes to our Ceph RGW cluster, and then shrinks back to baseline.