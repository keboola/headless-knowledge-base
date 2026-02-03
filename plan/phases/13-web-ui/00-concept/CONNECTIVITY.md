# Connectivity Strategy: Public vs Private

## The Problem
We are building a "Headless Knowledge Base" where the core components (Neo4j, Vector DB) are internal services. However, a Web UI (Neodash) runs in the client's browser.

## Constraints
1.  **Neo4j Cloud Run**: Currently `Internal Only`.
2.  **Neodash**: Client-side React App. Needs direct Bolt connection to DB.
3.  **Cloud Run Limitations**: Can only expose one port (currently mapped to Bolt 7687 on internal container, exposed as 443 externally).

## Solution: Public Ingress
To allow the browser to talk to Neo4j, we must make the Neo4j Cloud Run service **Public**.

### Risks
-   Anyone with the URL can attempt to connect.
-   DDOS potential (though Cloud Run scales/limits helps).
-   Brute force password attacks.

### Mitigations
-   **Strong Passwords**: We use 32+ char random passwords stored in Secret Manager.
-   **Rate Limiting**: Cloud Armor could be added (extra cost).
-   **Obscurity**: The URL is random/generated.

## Alternative: Proxy (Not Selected)
We could run a proxy server (Nginx) that sits on the public internet and tunnels traffic to the private Cloud Run instance.
-   **Pros**: Neo4j stays private.
-   **Cons**: Requires managing a proxy container, handling WebSocket tunneling, certificate management. Adds significant complexity for a "visualization tool".

## Conclusion
For this phase, we will switch Neo4j to **Public Ingress**.
