# Web UI Access & Administration Guide

## Overview

The Knowledge Base provides a visual interface (**Neodash**) for exploring the graph database.
Access is secured via **Google Identity-Aware Proxy (IAP)**, meaning no VPN is required—only a valid Google Workspace account.

## Domains

| Environment | UI URL (Browser) | DB Host (Connection Settings) | Access Control |
|---|---|---|---|
| **Production** | `https://kb.internal.keboola.com` | `neo4j.internal.keboola.com` | IAP (UI) / Cloud Armor (DB) |
| **Staging** | `https://kb.staging.keboola.com` | `neo4j.staging.keboola.com` | IAP (UI) / Cloud Armor (DB) |

## User Guide: How to Connect

1.  **Open the UI**: Navigate to the UI URL (e.g., `https://kb.internal.keboola.com`).
2.  **Log In**: You will be redirected to Google Login. Use your company email.
3.  **Neodash Connect Screen**:
    *   **Protocol**: `neo4j+s` (Secure Bolt)
    *   **Hostname**: `neo4j.internal.keboola.com` (Do not add `https://`)
    *   **Port**: `443` (Default for SSL)
    *   **Username**: `neo4j`
    *   **Password**: *Ask your administrator for the read-only or admin password.*
4.  **Save Connection**: You can save these settings in your browser for next time.

---

## Administrator Setup Guide

### 1. Pre-Deployment (One Time)

Before deploying Terraform, you must configure the OAuth layer manually in Google Cloud Console.

**Step A: Configure OAuth Consent Screen**
1.  Go to **APIs & Services > OAuth consent screen**.
2.  Select **Internal** (recommended for Organization) or **External** (for testing).
3.  Fill in App Name ("Knowledge Base"), User Support Email (`support@...`), and Developer Email.
4.  Save and Continue.

**Step B: Create OAuth Credentials**
1.  Go to **APIs & Services > Credentials**.
2.  Click **Create Credentials > OAuth client ID**.
3.  Application type: **Web application**.
4.  Name: `Knowledge Base IAP`.
5.  **Authorized Redirect URIs**: Leave empty for now (we need the Client ID first).
6.  Click **Create**.
7.  Copy the **Client ID** and **Client Secret**.

**Step C: Set Redirect URI**
1.  Edit the credential you just created.
2.  Add this Redirect URI (replacing `<CLIENT_ID>` with the actual ID you just copied):
    ```
    https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect
    ```
3.  Save.

**Step D: Add Secrets to Project**
Run the helper script with your credentials:
```bash
./deploy/scripts/setup-iap-secrets.sh "YOUR_CLIENT_ID" "YOUR_CLIENT_SECRET"
```

### 2. Deployment (Terraform)

Ensure your `terraform.tfvars` has the correct domain and authorized users:
```hcl
base_domain = "keboola.com"
iap_support_email = "support@keboola.com"

# Important: Only these users can log in via IAP
iap_authorized_users = [
  "domain:keboola.com",         # Allow everyone in the company
  "user:admin@example.com"      # Allow specific external users
]
```

Run Terraform:
```bash
cd deploy/terraform
terraform apply
```

### 3. DNS Configuration

After Terraform completes, it will output the `load_balancer_ip`. You must create 4 **A Records** in your DNS provider (e.g., Cloudflare, Route53, Google Domains):

| Type | Name | Value |
|---|---|---|
| A | `kb.internal` | `<LOAD_BALANCER_IP>` |
| A | `neo4j.internal` | `<LOAD_BALANCER_IP>` |
| A | `kb.staging` | `<LOAD_BALANCER_IP>` |
| A | `neo4j.staging` | `<LOAD_BALANCER_IP>` |

Wait for DNS propagation (TTL) and Google Managed SSL provisioning (can take 15-60 minutes).

### 4. Post-Deployment Verification

1.  Visit `https://kb.internal.keboola.com`.
2.  Verify Google Login redirect works.
3.  Verify Neodash loads.
4.  Retrieve the generated Neo4j password:
    ```bash
    gcloud secrets versions access latest --secret="neo4j-password"
    ```
5.  Try connecting Neodash to `neo4j.internal.keboola.com:443`.

---

## Troubleshooting

**"Service Unavailable" / 502 Error**
*   SSL Certificates might still be provisioning. Check status:
    ```bash
    gcloud compute ssl-certificates list
    ```
*   Cloud Run service might be cold or unhealthy. Check logs.

**"Connection Refused" in Neodash**
*   Ensure you are using `neo4j+s` protocol.
*   Ensure you are using port `443` (not 7687).
*   Check Cloud Armor logs to see if your IP is blocked.

**"403 Forbidden" on UI**
*   Your Google Account might not have permission.
*   Check IAM Binding: `roles/iap.httpsResourceAccessor` must be granted to you or your group on the Backend Service `neodash-backend`.
