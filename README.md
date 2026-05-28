# SRE bot

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/svg/1f98e.svg" alt="Lagarto" width="120"/>
</p>

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28+-326CE5.svg?logo=kubernetes&logoColor=white)](https://kubernetes.io/)

AI-powered SRE assistant for autonomous incident triage and root cause analysis. Integrates with your observability stack (Prometheus, Loki, Tempo) and collaboration tools (Slack, GitHub) to accelerate incident response.

## Overview

SRE bot is an autonomous agent that:

- **Receives alerts** from Alertmanager webhooks or Slack channels
- **Collects context** from Prometheus metrics, Loki logs, Tempo traces, Kubernetes API, and GitHub
- **Analyzes root cause** using LLM (OpenAI GPT-4 or Anthropic Claude)
- **Reports findings** back to Slack with actionable insights

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────────────┐
│ Alertmanager│────▶│             │     │         Data Collection             │
└─────────────┘     │             │     │  ┌───────────┐  ┌───────────┐       │
                    │  SRE        │────▶│  │Prometheus │  │   Loki    │       │
┌─────────────┐     │  bot        │     │  └───────────┘  └───────────┘       │
│   Slack     │◀───▶│             │     │  ┌───────────┐  ┌───────────┐       │
└─────────────┘     │             │     │  │   Tempo   │  │ Kubernetes│       │
                    │             │     │  └───────────┘  └───────────┘       │
                    │             │     │  ┌───────────┐                      │
                    │             │     │  │  GitHub   │                      │
                    └─────────────┘     │  └───────────┘                      │
                           │            └─────────────────────────────────────┘
                           ▼
                    ┌─────────────┐
                    │  LLM (GPT-4 │
                    │  / Claude)  │
                    └─────────────┘
```

## Features

- **Multi-source Alert Ingestion**: Alertmanager webhooks, Slack messages, custom API
- **Comprehensive Data Collection**:
  - Prometheus: metrics, SLIs, error rates, latency percentiles
  - Loki: application logs with automatic error pattern detection
  - Tempo: distributed traces for failed requests
  - Kubernetes: pod status, events, logs, deployment info
  - GitHub: recent commits, deployments, PR context
  - Alertmanager: correlated alerts for cascading failure detection
- **Intelligent Analysis**: LLM-powered root cause synthesis with confidence scoring
- **Learning System**: Learns from validated solutions to improve future incident resolution
- **Slack Integration**: Real-time alerts, interactive commands, threaded responses, feedback buttons
- **Cloud Native**: Helm chart, HPA, health checks, structured logging

## Status

**Alpha** - Under active development. API may change.

## Prerequisites

| Component | Version | Required |
|-----------|---------|----------|
| Python | 3.11+ | Yes |
| Kubernetes | 1.28+ | For production |
| Helm | 3.x | For Helm install |
| Docker | 20.10+ | For container builds |

### Observability Stack

SRE bot expects these services to be available:

| Service | Purpose | Default URL |
|---------|---------|-------------|
| Prometheus | Metrics queries | `http://localhost:9090` |
| Loki | Log queries | `http://localhost:3100` |
| Tempo | Trace queries | `http://localhost:3200` |

## Installation

### Option 1: Helm (Recommended for Kubernetes)

```bash
# Create namespace and secrets first
kubectl create namespace sre-bot

kubectl create secret generic sre-bot-secrets \
  --namespace sre-bot \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --from-literal=SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  --from-literal=SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
  --from-literal=SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET

# Install from source
helm install sre-bot ./k8s/charts/sre-bot \
  --namespace sre-bot \
  -f my-values.yaml
```

See [Helm Chart README](./k8s/charts/sre-bot/README.md) for detailed configuration options.

### Option 2: Docker

```bash
docker build -t sre-bot:latest .

docker run -d \
  --name sre-bot \
  -p 8000:8000 \
  -e LLM_PROVIDER=openai \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  -e SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
  -e PROMETHEUS_URL=http://prometheus:9090 \
  sre-bot:latest
```

### Option 3: Local Development

```bash
# Clone the repository
git clone https://github.com/Mario-Valente/sre-bot.git
cd sre-bot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run
sre-bot
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

#### LLM Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | `openai` or `anthropic` | `openai` |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `OPENAI_MODEL` | Model to use | `gpt-4o` |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `ANTHROPIC_MODEL` | Model to use | `claude-sonnet-4-20250514` |
| `LLM_TEMPERATURE` | Sampling temperature | `0.1` |

#### Slack Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `SLACK_BOT_TOKEN` | Bot token (`xoxb-...`) | Yes |
| `SLACK_APP_TOKEN` | App token (`xapp-...`) | Yes |
| `SLACK_SIGNING_SECRET` | Webhook verification | Yes |
| `SLACK_ALERT_CHANNEL` | Channel to monitor | No |

#### Observability Stack

| Variable | Description | Default |
|----------|-------------|---------|
| `PROMETHEUS_URL` | Prometheus API endpoint | `http://localhost:9090` |
| `LOKI_URL` | Loki API endpoint | `http://localhost:3100` |
| `TEMPO_URL` | Tempo API endpoint | `http://localhost:3200` |

#### Kubernetes (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `KUBERNETES_ENABLED` | Enable K8s integration | `true` |
| `KUBERNETES_IN_CLUSTER` | Use in-cluster config | `false` |
| `KUBERNETES_CONTEXT` | kubeconfig context | Current context |

See [`.env.example`](.env.example) for all options.

## Usage

### Via Alertmanager Webhook

Configure Alertmanager to send alerts:

```yaml
# alertmanager.yml
receivers:
  - name: 'sre-bot'
    webhook_configs:
      - url: 'http://sre-bot:8000/webhook/alertmanager'
        send_resolved: false

route:
  receiver: 'sre-bot'
  routes:
    - match:
        severity: critical
      receiver: 'sre-bot'
```

### Via Slack

**Automatic Detection**: Post alerts in the configured channel - the bot analyzes automatically.

**Direct Mention**:
```
@sre-bot analyze payment-api
```

**Slash Command**:
```
/sre-analyze payment-api production
```

### Feedback System

After each analysis, the bot displays feedback buttons:

- **Correct** - Saves the solution to the learning database for future use
- **Partially Correct** - Records feedback for improvement
- **Incorrect** - Records that the analysis was wrong

When you mark an analysis as "Correct", the bot learns from it and will suggest this solution for similar future incidents.

### Via REST API

```bash
curl -X POST http://localhost:8000/webhook/custom \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "payment-api",
    "namespace": "production",
    "severity": "critical",
    "description": "High error rate detected"
  }'
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/alertmanager` | POST | Alertmanager webhook receiver |
| `/webhook/custom` | POST | Custom alert ingestion |
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |

## Learning System

SRE bot features a learning system that improves over time based on human feedback.

### How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Alert     │────▶│  Analysis   │────▶│  Feedback   │────▶│  Learning   │
│  Received   │     │  Generated  │     │  Received   │     │   Stored    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                                                                   │
                    ┌──────────────────────────────────────────────┘
                    │
                    ▼
              ┌─────────────┐     ┌─────────────┐
              │   Similar   │────▶│  Enhanced   │
              │   Alert     │     │  Analysis   │
              └─────────────┘     └─────────────┘
```

1. **Alert Analysis**: Bot analyzes the incident using all available data sources
2. **Human Feedback**: User validates the analysis via Slack buttons
3. **Solution Stored**: If marked "Correct", the solution is saved to the database
4. **Future Incidents**: When a similar alert occurs, the bot retrieves historical solutions
5. **Enhanced Analysis**: LLM uses past solutions as context for better recommendations

### Solution Matching

Solutions are matched by priority:
1. **Exact Match**: Same `alert_name` + `service_name` + `namespace`
2. **Service Match**: Same `alert_name` + `service_name` (any namespace)
3. **Service Patterns**: Same `service_name` (different alerts)
4. **Generic Solutions**: Same `alert_name` (across services)

### Database Schema

The learning system uses SQLAlchemy with support for SQLite (dev) or PostgreSQL (production):

| Table | Purpose |
|-------|---------|
| `incidents` | Stores all incident investigations |
| `incident_feedback` | Human feedback on analyses |
| `learned_solutions` | Validated solutions for reuse |

## Local Development Environment

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

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests with coverage
pytest

# Run specific test file
pytest tests/test_agent.py -v

# Run with markers
pytest -m "not integration"
```

### Code Quality

```bash
# Linting
ruff check src/ tests/

# Formatting
ruff format src/ tests/

# Type checking
mypy src/

# All checks (via pre-commit)
pre-commit run --all-files
```

### Project Structure

```
sre-bot/
├── src/sre_bot/
│   ├── agent/           # LangGraph agent definition
│   │   └── nodes/       # Agent workflow nodes
│   ├── clients/         # External service clients
│   │   ├── prometheus.py
│   │   ├── loki.py
│   │   ├── tempo.py
│   │   └── kubernetes.py
│   ├── integrations/    # Slack, webhook handlers
│   ├── llm/             # LLM provider abstraction
│   ├── queries/         # PromQL, LogQL query builders
│   └── db/              # Database models
├── k8s/
│   ├── charts/          # Helm chart
│   ├── scripts/         # Setup scripts
│   └── manifests/       # Raw K8s manifests
├── tests/
└── pyproject.toml
```

## Roadmap

- [x] Learning system with feedback loop
- [x] Correlated alerts detection
- [ ] PagerDuty integration
- [ ] Datadog support
- [ ] Runbook automation
- [ ] Multi-cluster support
- [ ] Custom analysis plugins
- [ ] Incident timeline visualization
- [ ] Vector-based semantic search for solutions

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/sre-bot.git

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

## Community

- **Issues**: [GitHub Issues](https://github.com/Mario-Valente/sre-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Mario-Valente/sre-bot/discussions)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with:
- [LangChain](https://langchain.com/) / [LangGraph](https://langchain-ai.github.io/langgraph/) - Agent framework
- [Slack Bolt](https://slack.dev/bolt-python/) - Slack integration
- [FastAPI](https://fastapi.tiangolo.com/) - Webhook receiver
- [kubernetes-client](https://github.com/kubernetes-client/python) - Kubernetes API
