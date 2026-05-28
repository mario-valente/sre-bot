# Helm Chart

SRE Bot provides a Helm chart for Kubernetes deployment.

## Installation

### Add Repository

```bash
helm repo add sre-bot https://mario-valente.github.io/sre-bot
helm repo update
```

### Install

```bash
helm install sre-bot sre-bot/sre-bot \
  --namespace sre-bot \
  --create-namespace \
  -f values.yaml
```

### Upgrade

```bash
helm upgrade sre-bot sre-bot/sre-bot \
  --namespace sre-bot \
  -f values.yaml
```

### Uninstall

```bash
helm uninstall sre-bot --namespace sre-bot
```

---

## Prerequisites

1. **Create secrets** before installing:

```bash
kubectl create namespace sre-bot

kubectl create secret generic sre-bot-secrets \
  --namespace sre-bot \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --from-literal=SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  --from-literal=SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
  --from-literal=SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET \
  --from-literal=GITHUB_TOKEN=$GITHUB_TOKEN
```

---

## Configuration

### Basic Configuration

```yaml
# values.yaml
replicaCount: 1

image:
  repository: ghcr.io/mario-valente/sre-bot
  tag: latest
  pullPolicy: IfNotPresent

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
  logFormat: json

secrets:
  existingSecret: sre-bot-secrets
```

### Full Values Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `1` |
| `image.repository` | Image repository | `ghcr.io/mario-valente/sre-bot` |
| `image.tag` | Image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `config.llmProvider` | LLM provider (openai/anthropic) | `anthropic` |
| `config.anthropicModel` | Anthropic model | `claude-sonnet-4-20250514` |
| `config.openaiModel` | OpenAI model | `gpt-4o` |
| `config.prometheusUrl` | Prometheus URL | `http://localhost:9090` |
| `config.lokiUrl` | Loki URL | `http://localhost:3100` |
| `config.tempoUrl` | Tempo URL | `http://localhost:3200` |
| `config.alertmanagerUrl` | Alertmanager URL | `http://localhost:9093` |
| `config.kubernetesEnabled` | Enable K8s integration | `true` |
| `config.kubernetesInCluster` | Use in-cluster config | `true` |
| `config.slackAlertChannel` | Slack channel to monitor | `""` |
| `config.githubOrg` | Default GitHub org | `""` |
| `config.logLevel` | Log level | `INFO` |
| `config.logFormat` | Log format (json/console) | `json` |
| `secrets.existingSecret` | Name of existing secret | `""` |
| `secrets.anthropicApiKey` | Anthropic API key (inline) | `""` |
| `secrets.openaiApiKey` | OpenAI API key (inline) | `""` |
| `secrets.slackBotToken` | Slack bot token (inline) | `""` |
| `secrets.slackAppToken` | Slack app token (inline) | `""` |
| `secrets.slackSigningSecret` | Slack signing secret (inline) | `""` |
| `secrets.githubToken` | GitHub token (inline) | `""` |
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Service port | `8000` |
| `ingress.enabled` | Enable ingress | `false` |
| `ingress.className` | Ingress class | `""` |
| `ingress.hosts` | Ingress hosts | `[]` |
| `resources.limits.cpu` | CPU limit | `500m` |
| `resources.limits.memory` | Memory limit | `512Mi` |
| `resources.requests.cpu` | CPU request | `100m` |
| `resources.requests.memory` | Memory request | `256Mi` |
| `autoscaling.enabled` | Enable HPA | `false` |
| `autoscaling.minReplicas` | Minimum replicas | `1` |
| `autoscaling.maxReplicas` | Maximum replicas | `3` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU % | `80` |
| `serviceAccount.create` | Create service account | `true` |
| `serviceAccount.name` | Service account name | `""` |
| `rbac.create` | Create RBAC resources | `true` |

---

## Examples

### Production Configuration

```yaml
replicaCount: 2

image:
  repository: ghcr.io/mario-valente/sre-bot
  tag: "0.1.1"
  pullPolicy: IfNotPresent

config:
  llmProvider: anthropic
  anthropicModel: claude-sonnet-4-20250514
  prometheusUrl: http://prometheus.monitoring.svc:9090
  lokiUrl: http://loki.monitoring.svc:3100
  tempoUrl: http://tempo.monitoring.svc:3200
  alertmanagerUrl: http://alertmanager.monitoring.svc:9093
  kubernetesEnabled: true
  kubernetesInCluster: true
  slackAlertChannel: sre-alerts
  githubOrg: my-company
  logLevel: INFO
  logFormat: json

secrets:
  existingSecret: sre-bot-secrets

resources:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 200m
    memory: 512Mi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: sre-bot.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: sre-bot-tls
      hosts:
        - sre-bot.example.com

podDisruptionBudget:
  enabled: true
  minAvailable: 1
```

### Development Configuration

```yaml
replicaCount: 1

image:
  repository: ghcr.io/mario-valente/sre-bot
  tag: latest
  pullPolicy: Always

config:
  llmProvider: anthropic
  prometheusUrl: http://prometheus:9090
  lokiUrl: http://loki:3100
  tempoUrl: http://tempo:3200
  kubernetesEnabled: true
  kubernetesInCluster: true
  logLevel: DEBUG
  logFormat: console

secrets:
  # For development only - use existingSecret in production
  anthropicApiKey: sk-ant-...
  slackBotToken: xoxb-...
  slackAppToken: xapp-...

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi
```

---

## RBAC

The chart creates a ServiceAccount with permissions to:
- `get`, `list`, `watch` pods, events, deployments
- `get` pod logs

If you need to customize RBAC:

```yaml
serviceAccount:
  create: true
  name: sre-bot
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/sre-bot

rbac:
  create: true
  rules:
    - apiGroups: [""]
      resources: ["pods", "events", "services"]
      verbs: ["get", "list", "watch"]
    - apiGroups: ["apps"]
      resources: ["deployments", "replicasets"]
      verbs: ["get", "list", "watch"]
```

---

## Monitoring

### Prometheus ServiceMonitor

Enable metrics scraping:

```yaml
serviceMonitor:
  enabled: true
  interval: 30s
  labels:
    release: prometheus
```

### Pod Annotations

Or use annotations:

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/metrics"
```
