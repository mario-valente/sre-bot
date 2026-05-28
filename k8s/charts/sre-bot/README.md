# SRE Bot Helm Chart

Helm chart for deploying SRE Bot - an AI-powered SRE assistant for autonomous incident triage and root cause analysis.

## Prerequisites

- Kubernetes 1.28+
- Helm 3.x
- Access to observability stack (Prometheus, Loki, Tempo)
- LLM API key (Anthropic or OpenAI)

## Installation

### Quick Start

```bash
# Add the Helm repository (if published)
helm repo add sre-bot https://mario-valente.github.io/sre-bot
helm repo update

# Install with default values
helm install sre-bot sre-bot/sre-bot \
  --namespace sre-bot \
  --create-namespace
```

### Install from Source

```bash
# Clone the repository
git clone https://github.com/Mario-Valente/sre-bot.git
cd sre-bot

# Install the chart
helm install sre-bot ./k8s/charts/sre-bot \
  --namespace sre-bot \
  --create-namespace \
  -f my-values.yaml
```

### Using OCI Registry (GitHub Container Registry)

```bash
# Pull and install directly from GHCR
helm install sre-bot oci://ghcr.io/mario-valente/charts/sre-bot \
  --namespace sre-bot \
  --create-namespace \
  -f my-values.yaml
```

## Configuration

### Creating Secrets

Before installing, create a Kubernetes secret with your API keys:

```bash
kubectl create namespace sre-bot

kubectl create secret generic sre-bot-secrets \
  --namespace sre-bot \
  --from-literal=ANTHROPIC_API_KEY='your-anthropic-key' \
  --from-literal=SLACK_BOT_TOKEN='xoxb-your-bot-token' \
  --from-literal=SLACK_APP_TOKEN='xapp-your-app-token' \
  --from-literal=SLACK_SIGNING_SECRET='your-signing-secret' \
  --from-literal=GITHUB_TOKEN='your-github-token'
```

### Example values.yaml

```yaml
# values.yaml
replicaCount: 2

image:
  repository: ghcr.io/mario-valente/sre-bot
  tag: "0.1.1"

# LLM Configuration
llm:
  provider: "anthropic"
  anthropicModel: "claude-sonnet-4-20250514"
  temperature: "0.1"

# Observability Stack (adjust to your cluster)
observability:
  prometheusUrl: "http://prometheus-server.monitoring:9090"
  lokiUrl: "http://loki-gateway.monitoring:80"
  tempoUrl: "http://tempo.monitoring:3200"

# Slack Configuration
slack:
  alertChannel: "alerts"

input:
  enableWebhook: "true"
  enableSlackListener: "true"

# Database (use PostgreSQL for production)
database:
  url: "postgresql+asyncpg://user:pass@postgres:5432/sre_bot"

# Use existing secret
secrets:
  create: false
  existingSecret: "sre-bot-secrets"

# Resources
resources:
  requests:
    memory: "512Mi"
    cpu: "200m"
  limits:
    memory: "1Gi"
    cpu: "1000m"

# Autoscaling
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70

# Ingress
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  hosts:
    - host: sre-bot.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: sre-bot-tls
      hosts:
        - sre-bot.example.com
```

### Install with Custom Values

```bash
helm install sre-bot ./k8s/charts/sre-bot \
  --namespace sre-bot \
  --create-namespace \
  -f values.yaml
```

## Parameters

### Image Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Image repository | `ghcr.io/mario-valente/sre-bot` |
| `image.tag` | Image tag | `""` (uses appVersion) |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `imagePullSecrets` | Image pull secrets | `[]` |

### LLM Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `llm.provider` | LLM provider (`anthropic` or `openai`) | `anthropic` |
| `llm.anthropicModel` | Anthropic model | `claude-sonnet-4-20250514` |
| `llm.temperature` | LLM temperature | `0.1` |
| `llm.maxTokens` | Max tokens | `4096` |

### Observability Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `observability.prometheusUrl` | Prometheus URL | `http://prometheus-prometheus.monitoring.svc.cluster.local:9090` |
| `observability.lokiUrl` | Loki URL | `http://loki-gateway.monitoring.svc.cluster.local:80` |
| `observability.tempoUrl` | Tempo URL | `http://tempo.monitoring.svc.cluster.local:3200` |

### Input Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `input.enableWebhook` | Enable webhook receiver | `true` |
| `input.enableSlackListener` | Enable Slack listener | `false` |
| `input.webhookHost` | Webhook host | `0.0.0.0` |
| `input.webhookPort` | Webhook port | `8000` |

### Slack Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `slack.alertChannel` | Slack alert channel | `alertas` |

### Database Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `database.url` | Database URL | `sqlite+aiosqlite:///./sre_bot.db` |

### Secrets Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.create` | Create secret from values | `false` |
| `secrets.existingSecret` | Existing secret name | `sre-bot-secrets` |
| `secrets.values.ANTHROPIC_API_KEY` | Anthropic API key | `""` |
| `secrets.values.SLACK_BOT_TOKEN` | Slack bot token | `""` |
| `secrets.values.SLACK_APP_TOKEN` | Slack app token | `""` |
| `secrets.values.SLACK_SIGNING_SECRET` | Slack signing secret | `""` |
| `secrets.values.GITHUB_TOKEN` | GitHub token | `""` |

### Service Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Service port | `8000` |

### Ingress Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `false` |
| `ingress.className` | Ingress class name | `""` |
| `ingress.hosts` | Ingress hosts | See values.yaml |

### Autoscaling Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `autoscaling.enabled` | Enable HPA | `false` |
| `autoscaling.minReplicas` | Minimum replicas | `1` |
| `autoscaling.maxReplicas` | Maximum replicas | `5` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU % | `80` |

## Upgrading

```bash
# Update repository
helm repo update

# Upgrade release
helm upgrade sre-bot sre-bot/sre-bot \
  --namespace sre-bot \
  -f values.yaml
```

## Uninstalling

```bash
helm uninstall sre-bot --namespace sre-bot
kubectl delete namespace sre-bot
```

## Alertmanager Integration

Configure Alertmanager to send alerts to SRE Bot:

```yaml
# alertmanager.yml
receivers:
  - name: 'sre-bot'
    webhook_configs:
      - url: 'http://sre-bot.sre-bot.svc.cluster.local:8000/webhook/alertmanager'
        send_resolved: false

route:
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'sre-bot'
    - match:
        severity: warning
      receiver: 'sre-bot'
```

## Troubleshooting

### Check pod status

```bash
kubectl get pods -n sre-bot
kubectl logs -n sre-bot -l app.kubernetes.io/name=sre-bot
```

### Verify connectivity

```bash
# Check health endpoint
kubectl port-forward -n sre-bot svc/sre-bot 8000:8000
curl http://localhost:8000/health
```

### Common Issues

1. **Pod not starting**: Check secrets are created correctly
2. **LLM errors**: Verify API key is valid
3. **No alerts received**: Check Alertmanager webhook configuration
4. **Slack not working**: Verify bot/app tokens and permissions

## License

MIT License - see [LICENSE](https://github.com/Mario-Valente/sre-bot/blob/main/LICENSE)
