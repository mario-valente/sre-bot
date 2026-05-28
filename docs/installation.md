# Installation Guide

This guide covers all installation methods for SRE Bot.

## Prerequisites

| Component | Version | Required |
|-----------|---------|----------|
| Python | 3.11+ | Yes |
| Kubernetes | 1.28+ | For production |
| Helm | 3.x | For Helm install |
| Docker | 20.10+ | For container builds |

### Observability Stack

SRE Bot expects these services to be available:

| Service | Purpose | Default URL |
|---------|---------|-------------|
| Prometheus | Metrics queries | `http://localhost:9090` |
| Loki | Log queries | `http://localhost:3100` |
| Tempo | Trace queries | `http://localhost:3200` |
| Alertmanager | Correlated alerts | `http://localhost:9093` |

---

## Option 1: Helm (Recommended)

### Add the Repository

```bash
helm repo add sre-bot https://mario-valente.github.io/sre-bot
helm repo update
```

### Create Namespace and Secrets

```bash
kubectl create namespace sre-bot

kubectl create secret generic sre-bot-secrets \
  --namespace sre-bot \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --from-literal=SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  --from-literal=SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
  --from-literal=SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET
```

### Install the Chart

```bash
helm install sre-bot sre-bot/sre-bot \
  --namespace sre-bot \
  --set config.llmProvider=anthropic \
  --set config.prometheusUrl=http://prometheus.monitoring:9090 \
  --set config.lokiUrl=http://loki.monitoring:3100
```

### Install from Source

If you prefer to install from the repository:

```bash
git clone https://github.com/Mario-Valente/sre-bot.git
cd sre-bot

helm install sre-bot ./k8s/charts/sre-bot \
  --namespace sre-bot \
  -f my-values.yaml
```

---

## Option 2: Docker

### Using Pre-built Image

```bash
docker run -d \
  --name sre-bot \
  -p 8000:8000 \
  -e LLM_PROVIDER=anthropic \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  -e SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
  -e PROMETHEUS_URL=http://prometheus:9090 \
  -e LOKI_URL=http://loki:3100 \
  -e TEMPO_URL=http://tempo:3200 \
  ghcr.io/mario-valente/sre-bot:latest
```

### Build from Source

```bash
git clone https://github.com/Mario-Valente/sre-bot.git
cd sre-bot

docker build -t sre-bot:latest .

docker run -d \
  --name sre-bot \
  -p 8000:8000 \
  --env-file .env \
  sre-bot:latest
```

---

## Option 3: Local Development

### Clone and Setup

```bash
git clone https://github.com/Mario-Valente/sre-bot.git
cd sre-bot

# Using uv (recommended)
uv sync --all-extras

# Or using pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Run

```bash
# With uv
uv run sre-bot

# Or directly
sre-bot
```

---

## Local Kubernetes Environment

Set up a complete local environment with Kind:

```bash
# Create Kind cluster with observability stack
./k8s/scripts/setup-cluster.sh
```

This installs:
- **Prometheus** (kube-prometheus-stack): http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)
- **Loki**: http://localhost:3100
- **Tempo**: http://localhost:3200

Teardown:
```bash
./k8s/scripts/teardown-cluster.sh
```

---

## Verify Installation

### Health Check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy"}
```

### Readiness Check

```bash
curl http://localhost:8000/ready
```

### Test Webhook

```bash
curl -X POST http://localhost:8000/webhook/custom \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "test-service",
    "namespace": "default",
    "severity": "warning",
    "description": "Test alert"
  }'
```

---

## Next Steps

- [Configuration](configuration.md) - Configure environment variables
- [Architecture](architecture.md) - Understand how the agent works
- [API Reference](api-reference.md) - REST API documentation
