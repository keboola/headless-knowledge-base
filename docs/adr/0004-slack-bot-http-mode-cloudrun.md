# ADR-0004: Deploy Slack Bot in HTTP Mode on Cloud Run

## Status
Accepted

## Date
2024-12-24

## Context
The Slack bot can operate in two modes:
1. **Socket Mode**: Persistent WebSocket connection to Slack
2. **HTTP Mode**: Receives events via HTTP webhooks

For GCP deployment, we needed to choose the appropriate mode and hosting platform.

### Options Considered
| Option | Platform | Mode |
|--------|----------|------|
| Socket Mode on GCE | GCE VM | Socket |
| Socket Mode on Cloud Run | Cloud Run | Socket |
| HTTP Mode on Cloud Run | Cloud Run | HTTP |
| HTTP Mode on GKE | GKE | HTTP |

## Decision
We chose **HTTP Mode deployed on Cloud Run**.

## Rationale

### Why HTTP Mode?
1. **Serverless compatible**: No persistent connection needed
2. **Scale to zero**: No cost when not in use
3. **Stateless**: Easy horizontal scaling
4. **Standard protocol**: Works with any HTTP infrastructure

### Why Cloud Run?
1. **Auto-scaling**: 0-10 instances based on demand
2. **Pay-per-use**: Only charged for actual requests
3. **Managed TLS**: Automatic HTTPS certificates
4. **Simple deployment**: Docker container, no Kubernetes complexity

### Why Not Socket Mode?
1. **Requires persistent connection**: Can't scale to zero
2. **GCE overhead**: Would need always-on VM (~$5-15/month)
3. **Connection management**: Must handle reconnects, timeouts
4. **Not serverless**: Defeats purpose of Cloud Run

### Cost Analysis
| Approach | Monthly Cost | Notes |
|----------|-------------|-------|
| HTTP on Cloud Run | ~$0-5 | Scale to zero, free tier |
| Socket on GCE | ~$5-15 | Always-on e2-micro |
| Socket on Cloud Run | ~$15-30 | Min 1 instance required |

## Implementation

### Starlette Adapter
We use `slack_bolt.adapter.starlette` for HTTP mode:

```python
from slack_bolt.adapter.starlette import SlackRequestHandler
from starlette.applications import Starlette

handler = SlackRequestHandler(bolt_app)

starlette_app = Starlette(routes=[
    Route("/health", endpoint=health, methods=["GET"]),
    Route("/slack/events", endpoint=slack_events, methods=["POST"]),
])
```

### Cloud Run Configuration
- **Min instances**: 0 (scale to zero)
- **Max instances**: 10
- **CPU**: 1
- **Memory**: 512Mi
- **Concurrency**: 80 requests/instance

## Consequences

### Positive
- Near-zero cost during low usage periods
- Automatic scaling for traffic spikes
- Simple, stateless architecture
- Easy rollbacks and deployments

### Negative
- Cold start latency (~1-2s on first request after idle)
- Must configure Slack app for HTTP webhooks
- Request timeout limit (60s default, 3600s max)

### Slack App Configuration Required
1. Enable Event Subscriptions in Slack app settings
2. Set Request URL to: `https://<cloud-run-url>/slack/events`
3. Subscribe to events: `app_mention`, `message.im`
4. Enable Interactivity with same URL

## References
- [Slack Bolt for Python](https://slack.dev/bolt-python/)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
- [Slack Event Subscriptions](https://api.slack.com/events-api)
