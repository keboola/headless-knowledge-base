# Phase 13: Web UI & Secure Edge - Verification

## How to Verify

### 1. Infrastructure State
Run:
```bash
terraform output load_balancer_ip
```
Confirm IP is allocated.

### 2. Security (IAP)
1.  Open Incognito window.
2.  Navigate to `https://ui.<your-domain>`.
3.  **Expected**: Redirected to `accounts.google.com`.
4.  Log in with authorized workspace account.
5.  **Expected**: Neodash loads.

### 3. Security (Cloud Armor)
1.  (Optional) If you configured a deny rule for a test IP, try accessing `https://db.<your-domain>` from that IP.
2.  **Expected**: 403 Forbidden or 404 (depending on config).

### 4. Application Connectivity
1.  In Neodash, connect to:
    - **Protocol**: `neo4j+s` (wss)
    - **Host**: `db.<your-domain>`
    - **Port**: 443 (Default for HTTPS/WSS through LB)
2.  **Expected**: Connection Successful. Graph visible.
