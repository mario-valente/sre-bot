# Configuration

SRE Bot is configured through environment variables. This page documents all available options.

## Environment Variables

### LLM Configuration

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `LLM_PROVIDER` | LLM provider: `openai` or `anthropic` | `openai` | No |
| `OPENAI_API_KEY` | OpenAI API key | - | If using OpenAI |
| `OPENAI_MODEL` | OpenAI model to use | `gpt-4o` | No |
| `ANTHROPIC_API_KEY` | Anthropic API key | - | If using Anthropic |
| `ANTHROPIC_MODEL` | Anthropic model to use | `claude-sonnet-4-20250514` | No |
| `LLM_TEMPERATURE` | Sampling temperature (0.0-1.0) | `0.1` | No |
| `LLM_MAX_TOKENS` | Maximum response tokens | `4096` | No |

### Slack Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `SLACK_BOT_TOKEN` | Bot token (starts with `xoxb-`) | Yes |
| `SLACK_APP_TOKEN` | App token (starts with `xapp-`) | Yes |
| `SLACK_SIGNING_SECRET` | Webhook signing secret | Yes |
| `SLACK_ALERT_CHANNEL` | Channel to monitor for alerts | No |

### Observability Stack

| Variable | Description | Default |
|----------|-------------|---------|
| `PROMETHEUS_URL` | Prometheus API endpoint | `http://localhost:9090` |
| `LOKI_URL` | Loki API endpoint | `http://localhost:3100` |
| `TEMPO_URL` | Tempo API endpoint | `http://localhost:3200` |
| `ALERTMANAGER_URL` | Alertmanager API endpoint | `http://localhost:9093` |

### Kubernetes

| Variable | Description | Default |
|----------|-------------|---------|
| `KUBERNETES_ENABLED` | Enable Kubernetes integration | `true` |
| `KUBERNETES_IN_CLUSTER` | Use in-cluster config | `false` |
| `KUBERNETES_CONTEXT` | kubeconfig context to use | Current context |
| `KUBERNETES_LOG_LINES` | Number of log lines per pod | `100` |

### GitHub

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | - |
| `GITHUB_ORG` | Default organization for repos | - |

### Database

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///sre_bot.db` |

### Server

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `8000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FORMAT` | Log format: `json` or `console` | `json` |

### Query Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `QUERY_TIMEOUT_SECONDS` | Timeout for external queries | `30` |
| `METRICS_LOOKBACK_MINUTES` | How far back to query metrics | `60` |
| `LOGS_LOOKBACK_MINUTES` | How far back to query logs | `30` |
| `TRACES_LOOKBACK_MINUTES` | How far back to query traces | `30` |

---

## Example Configuration

### `.env` file

```bash
# LLM
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
LLM_TEMPERATURE=0.1

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...
SLACK_ALERT_CHANNEL=alerts

# Observability
PROMETHEUS_URL=http://prometheus.monitoring:9090
LOKI_URL=http://loki.monitoring:3100
TEMPO_URL=http://tempo.monitoring:3200
ALERTMANAGER_URL=http://alertmanager.monitoring:9093

# Kubernetes
KUBERNETES_ENABLED=true
KUBERNETES_IN_CLUSTER=true

# GitHub
GITHUB_TOKEN=ghp_...
GITHUB_ORG=my-org

# Database
DATABASE_URL=postgresql://user:pass@postgres:5432/sre_bot

# Server
LOG_LEVEL=INFO
LOG_FORMAT=json
```

---

## Helm Values

When deploying with Helm, configuration is done through `values.yaml`:

```yaml
config:
  llmProvider: anthropic
  anthropicModel: claude-sonnet-4-20250514
  prometheusUrl: http://prometheus.monitoring:9090
  lokiUrl: http://loki.monitoring:3100
  tempoUrl: http://tempo.monitoring:3200
  alertmanagerUrl: http://alertmanager.monitoring:9093
  kubernetesEnabled: true
  kubernetesInCluster: true
  slackAlertChannel: alerts
  logLevel: INFO

secrets:
  existingSecret: sre-bot-secrets
  # Or create secrets inline (not recommended for production):
  # anthropicApiKey: sk-ant-...
  # slackBotToken: xoxb-...
```

See [Helm Chart documentation](helm-chart.md) for full options.

---

## Security Best Practices

1. **Never commit secrets** to version control
2. **Use Kubernetes Secrets** for sensitive values in production
3. **Rotate API keys** regularly
4. **Limit token scopes** to minimum required permissions
5. **Use read-only tokens** where possible (GitHub, Kubernetes)

### Minimum Required Permissions

| Service | Required Permissions |
|---------|---------------------|
| Slack | `chat:write`, `app_mentions:read`, `channels:history` |
| GitHub | `repo:read` (public repos) or `repo` (private repos) |
| Kubernetes | `get`, `list` on pods, events, deployments |
