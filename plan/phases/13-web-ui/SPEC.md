# Phase 13: Web UI & Secure Edge - Specification

## Goal
Deploy **Neodash** as the visualization frontend, protected by a production-grade **Secure Edge** architecture (Load Balancer, IAP, Cloud Armor).

## Architecture Upgrade
Instead of exposing Cloud Run services directly (Public Ingress), we will place them behind a Global Load Balancer.
- **`ui.example.com`**: Points to Neodash. Protected by **IAP** (Google Workspace Login).
- **`db.example.com`**: Points to Neo4j. Protected by **Cloud Armor** (WAF) + Native Auth.

## Implementation Tasks

### 13.1 Infrastructure (Terraform)
- **Files**:
    - `deploy/terraform/cloudrun-neodash.tf`: The UI service (Internal Ingress).
    - `deploy/terraform/load-balancer.tf`: GCLB, Managed SSL, Backend Services, Serverless NEGs.
    - `deploy/terraform/security.tf`: Cloud Armor Policies, IAP Configuration.
- **Configuration**:
    - Enable `iap.googleapis.com`.
    - Configure OAuth Client ID/Secret (requires manual Console step for Brand).
    - Configure Serverless NEGs for Cloud Run.

### 13.2 Dashboard Configuration
- **Default Dashboard**: A `dashboard.json` pre-loaded with useful queries:
    - "Recent Changes" (Temporal graph query).
    - "Topic Cluster" (Graph exploration).
    - "Orphaned Documents" (QA query).

## Connectivity Logic
1.  User visits `https://ui.example.com`.
2.  **IAP** challenges for Google Login.
3.  Upon success, **Neodash** loads.
4.  Neodash attempts to connect to `wss://db.example.com`.
5.  **Cloud Armor** checks IP/Rate limits.
6.  Connection established. User enters Neo4j Password (or we bake a read-only token if preferred, but password is safer for now).

## Success Criteria
- [ ] `ui` subdomain redirects to Google Login.
- [ ] Only authorized email domains can log in.
- [ ] `db` subdomain accepts secure WebSocket connections (`wss://`).
- [ ] Neodash successfully visualizes the graph.
- [ ] Cloud Armor logs show traffic inspection.
