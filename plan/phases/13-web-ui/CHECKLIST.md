# Phase 13: Web UI (Neodash) - Checklist

## Security Review
- [x] **Decision**: Confirm moving Neo4j to Public Ingress is acceptable for the project (relying on password auth).
- [x] **Action**: If yes, proceed. If no, investigate IAP/Proxy solutions (adds complexity).

## Infrastructure
- [x] Create `deploy/terraform/cloudrun-neodash.tf`.
    - [x] Service name: `neodash`.
    - [x] Image: `neo4jlabs/neodash:2.4`.
    - [x] Port: 5005 (or 80 - check image docs).
    - [x] Env Vars: `ssoEnabled=false`, `standalone=true`.
- [x] Modify `deploy/terraform/cloudrun-neo4j.tf`.
    - [x] Change `ingress` to `INGRESS_TRAFFIC_ALL`.
- [x] Run `terraform plan` and `terraform apply`.

## Configuration
- [x] Create `src/knowledge_base/web/dashboard_config.json`.
    - [x] Define "Knowledge Base Overview" page.
    - [x] Define "Entity Search" page.
- [ ] Upload config to GCS (or embed in Docker image if we build custom).
    - *Simpler Approach*: Use the standard image and let users build/save dashboards locally first, then "publish" by hosting the JSON later.

## Documentation
- [x] Add "How to Access UI" to `README.md`.
- [x] Document credentials retrieval (`gcloud secrets versions access ...`).

## Pre-requisites (Manual Action Required)
- [ ] **Domain Name**: Identify the domain to use (e.g., `kb.dev.keboola.com` or similar).
- [ ] **OAuth Consent Screen**:
    - Go to GCP Console -> APIs & Services -> OAuth consent screen.
    - Create "Internal" app (if Org exists) or "External" (testing).
    - Add authorized domain.
- [ ] **OAuth Credentials**:
    - Create "Web Application" credentials.
    - Authorized Redirect URI: `https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect`
    - Save Client ID and Secret to Secret Manager: `iap-client-id`, `iap-client-secret`.

## Infrastructure Implementation
- [x] Create `deploy/terraform/cloudrun-neodash.tf`.
    - [x] Service: `neodash` (Ingress: Internal/Load Balancer).
    - [x] Env Vars: `STANDALONE_PROTOCOL=bolt+s` (or neo4j+s).
- [x] Create `deploy/terraform/security.tf`.
    - [x] Resource: `google_compute_security_policy` (Cloud Armor).
        - [x] Rule: Allow all (baseline).
        - [x] Rule: Rate limit (optional).
    - [x] Data: Load IAP secrets.
- [x] Create `deploy/terraform/load-balancer.tf` (or use module).
    - [x] Reserve Global IP.
    - [x] Create Managed SSL Certificate.
    - [x] Create Serverless NEGs for `neodash` and `neo4j`.
    - [x] Create Backend Services:
        - [x] `neodash-backend`: Enable IAP, Enable CDN.
        - [x] `neo4j-backend`: Enable Cloud Armor, Disable IAP (for WebSocket compat).
    - [x] Create URL Map:
        - [x] Host `ui.*` -> `neodash-backend`.
        - [x] Host `db.*` -> `neo4j-backend`.
- [ ] Run `terraform apply`.

## DNS Configuration
- [ ] Get IP from `terraform output load_balancer_ip`.
- [ ] Create A records for `ui.<domain>` and `db.<domain>`.

## Verification
- [ ] Wait for SSL provisioning (can take 15-60 mins).
- [ ] Verify IAP Login flow on UI.
- [ ] Verify Dashboard connects to DB.