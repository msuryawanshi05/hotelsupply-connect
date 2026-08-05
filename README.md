# HotelSupply Connect

![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python Version](https://img.shields.io/badge/python-3.11-blue)

## Problem Statement
Legacy procurement platforms (like Avendra/iBuyEfficient, Fourth) often suffer from static PO status, slow release cycles, fragmented tooling, and missing workflow metadata. HotelSupply Connect bridges these gaps by providing a modern, cloud-native approach that brings agility, visibility, and robust performance to hotel procurement workflows.

## Architecture Overview
```
┌─────────────────────────────────────────────────────────────────┐
│                    HotelSupply Connect                          │
│                  Cloud-Native Architecture                      │
└─────────────────────────────────────────────────────────────────┘

  [Browser/Client]
        │ HTTPS (TLS)
        ▼
  ┌─────────────┐
  │   Ingress   │  ← TLS termination
  └──────┬──────┘
         │
         ▼
  ┌─────────────────────────────┐
  │   API Service (3+ replicas) │  ← HPA: 3-10 pods
  │     FastAPI + SQLModel      │
  └───┬───────────┬─────────────┘
      │           │  HTTP (NetworkPolicy enforced)
      ▼           ▼
 ┌─────────┐  ┌──────────┐
 │ Matcher │  │ Notifier │  ← Knative-ready functions
 │Function │  │Function  │
 └─────────┘  └──────────┘
      │
      ▼
  [Notifier] (also called by matcher)
  
  ┌──────────────┐    ┌───────────────┐
  │  PostgreSQL  │    │  Prometheus   │
  │  (PVC 5Gi)  │    │  + Grafana    │
  └──────────────┘    └───────────────┘
```

## Hackathon Deliverables Traceability
| # | Requirement | File(s) |
|---|---|---|
| 1 | Source code + .gitignore | All source files, `.gitignore` |
| 2 | CI/CD: test→build→scan→push→deploy | `.github/workflows/ci-cd.yaml` |
| 3 | K8s/OpenShift YAML manifests | `k8s/*.yaml` |
| 4 | Container images pushed to GHCR | `.github/workflows/ci-cd.yaml` (push job) |
| 5 | Event-driven serverless function | `functions/matcher/handler.py`, `functions/notifier/handler.py`, `k8s/functions.yaml` |
| 6 | Load balancing via K8s Service | `k8s/api-service.yaml`, `k8s/api-deployment.yaml` (3 replicas) |
| 7 | HPA on CPU and memory | `k8s/api-hpa.yaml` |
| 8 | HA: 3+ replicas, RollingUpdate | `k8s/api-deployment.yaml` |
| 9 | Security: TLS, Secrets, RBAC, NetworkPolicy, non-root | `k8s/ingress.yaml`, `k8s/secret-example.yaml`, `k8s/rbac.yaml`, `k8s/networkpolicy.yaml`, all Dockerfiles |
| 10 | Startup/liveness/readiness probes | `k8s/api-deployment.yaml`, `api/main.py` (`/startupz`, `/healthz`, `/readyz`) |
| 11 | Persistent storage (PVC) | `k8s/postgres.yaml` |
| 12 | Monitoring + logging | `api/main.py` (Prometheus metrics), Grafana setup below |
| 13 | Live demo script | Demo section below |

## Quick Start
```bash
# Clone
git clone https://github.com/your-org/hotelsupply-connect
cd hotelsupply-connect

# Start all services
docker-compose up --build

# Wait for healthy status, then:
curl http://localhost:8000/healthz
curl http://localhost:8000/dashboard/summary
```

## Live Demo Script

Step 1: Get admin token
```bash
curl -X POST http://localhost:8000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin-user", "role": "admin", "password": "demo123"}'
# Save: ADMIN_TOKEN=<token>
```

Step 2: Create a hotel
```bash
curl -X POST http://localhost:8000/hotels \
  -H 'Authorization: Bearer $ADMIN_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"name": "Grand Hyatt Mumbai", "contact_email": "procurement@grandhyatt.com"}'
# Save: HOTEL_ID=<id>
```

Step 3: Get a hotel JWT
```bash
curl -X POST http://localhost:8000/auth/token \
  -d '{"username": "$HOTEL_ID", "role": "hotel", "password": "demo123"}'
# Save: HOTEL_TOKEN=<token>
```

Step 4: Post a requirement (triggers matcher + notifier)
```bash
curl -X POST http://localhost:8000/requirements \
  -H 'Authorization: Bearer $HOTEL_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "hotel_id": "$HOTEL_ID",
    "item": "soap",
    "quantity": 500,
    "urgency": "high",
    "department": "housekeeping",
    "deadline": "2024-12-31"
  }'
# Observe: status=matched, matched_supplier_id set
```

Step 5: Check dashboard
```bash
curl http://localhost:8000/dashboard/summary
```

Step 6: Accept as supplier
```bash
# First get supplier token, then:
curl -X PATCH http://localhost:8000/requirements/$REQ_ID/accept \
  -H 'Authorization: Bearer $SUPPLIER_TOKEN'
```

Step 7: RBAC violation demo
```bash
# Hotel token trying to create a supplier (should return 403)
curl -X POST http://localhost:8000/suppliers \
  -H 'Authorization: Bearer $HOTEL_TOKEN' \
  -d '{"name": "Hack Supplier", "contact_email": "hack@example.com", "catalog_items": "soap"}'
# Expected: 403 Forbidden
```

Step 8: Metrics
```bash
curl http://localhost:8000/metrics | grep requirements
curl http://localhost:8001/metrics | grep matcher
```

## Grafana Dashboard Setup
```
1. Add Prometheus data source: http://prometheus:9090
2. Import panels:
   - Requirement throughput: rate(http_requests_total{path="/requirements",method="POST"}[5m])
   - Fulfillment rate: requirements_fulfilled_total / requirements_created_total
   - Error rate: rate(http_requests_total{status=~"5.."}[5m])
   - Matcher latency: histogram_quantile(0.95, matcher_duration_seconds_bucket)
   - Active pods: kube_deployment_status_replicas{deployment="hotelsupply-api"}
   - HPA scale events: kube_horizontalpodautoscaler_status_current_replicas
```

## Security Notes
The project uses the Sealed Secrets pattern to safely store secrets in the repository, while ensuring only the cluster has the private key to decrypt them. RBAC is strictly scoped, enforcing the principle of least privilege, and NetworkPolicies are configured to allow only necessary inter-service communication and external ingress.

## Kubernetes Deployment
```bash
# Create namespace
kubectl create namespace hotelsupply

# Apply sealed secret (not the example file)
kubeseal --format yaml < secret.yaml > k8s/sealed-secret.yaml
kubectl apply -f k8s/sealed-secret.yaml

# Apply all manifests in order
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/networkpolicy.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/functions.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/api-hpa.yaml
kubectl apply -f k8s/ingress.yaml

# Verify
kubectl get pods -n hotelsupply
kubectl get hpa -n hotelsupply
```

## HA Demo
To demonstrate High Availability (HA) capabilities, you can forcefully delete an API pod:
```bash
kubectl delete pod -l app=hotelsupply-api -n hotelsupply
```
With 3+ replicas and properly configured liveness/readiness probes, Kubernetes will immediately start routing traffic away from the terminating pod to the healthy replicas, ensuring zero dropped requests during the event.
