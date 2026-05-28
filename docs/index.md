# SRE Bot

**AI-powered SRE assistant for autonomous incident triage and root cause analysis.**

SRE Bot integrates with your observability stack (Prometheus, Loki, Tempo) and collaboration tools (Slack, GitHub) to accelerate incident response.

---

## What is SRE Bot?

SRE Bot is an autonomous agent that:

- **Receives alerts** from Alertmanager webhooks or Slack channels
- **Collects context** from Prometheus metrics, Loki logs, Tempo traces, Kubernetes API, and GitHub
- **Analyzes root cause** using LLM (OpenAI GPT-4 or Anthropic Claude)
- **Reports findings** back to Slack with actionable insights
- **Learns from feedback** to improve future incident resolution

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────────────┐
│ Alertmanager│────▶│             │     │         Data Collection             │
└─────────────┘     │             │     │  ┌───────────┐  ┌───────────┐       │
                    │  SRE        │────▶│  │Prometheus │  │   Loki    │       │
┌─────────────┐     │  Bot        │     │  └───────────┘  └───────────┘       │
│   Slack     │◀───▶│             │     │  ┌───────────┐  ┌───────────┐       │
└─────────────┘     │             │     │  │   Tempo   │  │ Kubernetes│       │
                    │             │     │  └───────────┘  └───────────┘       │
                    │             │     │  ┌───────────┐  ┌───────────┐       │
                    │             │     │  │  GitHub   │  │Alertmanager│      │
                    └─────────────┘     │  └───────────┘  └───────────┘       │
                           │            └─────────────────────────────────────┘
                           ▼
                    ┌─────────────┐
                    │  LLM (GPT-4 │
                    │  / Claude)  │
                    └─────────────┘
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-source Alert Ingestion** | Alertmanager webhooks, Slack messages, custom API |
| **Comprehensive Data Collection** | Metrics, logs, traces, K8s events, GitHub commits |
| **Correlated Alerts** | Detects cascading failures across services |
| **Intelligent Analysis** | LLM-powered root cause synthesis with confidence scoring |
| **Learning System** | Learns from validated solutions to improve over time |
| **Cloud Native** | Helm chart, HPA, health checks, structured logging |

## Quick Start

### Install via Helm

```bash
# Add the Helm repository
helm repo add sre-bot https://mario-valente.github.io/sre-bot
helm repo update

# Create namespace and secrets
kubectl create namespace sre-bot
kubectl create secret generic sre-bot-secrets \
  --namespace sre-bot \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --from-literal=SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  --from-literal=SLACK_APP_TOKEN=$SLACK_APP_TOKEN

# Install
helm install sre-bot sre-bot/sre-bot --namespace sre-bot
```

### Run with Docker

```bash
docker run -d \
  -p 8000:8000 \
  -e LLM_PROVIDER=anthropic \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  -e PROMETHEUS_URL=http://prometheus:9090 \
  ghcr.io/mario-valente/sre-bot:latest
```

## Documentation

- [Installation Guide](installation.md) - Detailed setup instructions
- [Configuration](configuration.md) - Environment variables and options
- [Architecture](architecture.md) - How the agent works internally
- [Learning System](learning-system.md) - How the bot learns from feedback
- [API Reference](api-reference.md) - REST API endpoints
- [Helm Chart](helm-chart.md) - Kubernetes deployment options

## Status

**Alpha** - Under active development. API may change.

## License

MIT License - see [LICENSE](https://github.com/Mario-Valente/sre-bot/blob/main/LICENSE) for details.
