# API Reference

SRE Bot exposes a REST API for webhook integration and health monitoring.

## Base URL

```
http://localhost:8000
```

---

## Endpoints

### Health Check

Check if the service is running.

```
GET /health
```

**Response:**

```json
{
  "status": "healthy"
}
```

---

### Readiness Check

Check if the service is ready to accept requests.

```
GET /ready
```

**Response:**

```json
{
  "status": "ready",
  "checks": {
    "llm": true,
    "database": true
  }
}
```

---

### Alertmanager Webhook

Receive alerts from Prometheus Alertmanager.

```
POST /webhook/alertmanager
Content-Type: application/json
```

**Request Body:**

Standard Alertmanager webhook payload:

```json
{
  "receiver": "sre-bot",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighErrorRate",
        "service": "payment-api",
        "namespace": "production",
        "severity": "critical"
      },
      "annotations": {
        "summary": "High error rate detected",
        "description": "Error rate > 5% for payment-api"
      },
      "startsAt": "2024-01-15T10:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "fingerprint": "abc123"
    }
  ],
  "groupLabels": {
    "alertname": "HighErrorRate"
  },
  "commonLabels": {
    "severity": "critical"
  },
  "externalURL": "http://alertmanager:9093"
}
```

**Response:**

```json
{
  "status": "accepted",
  "alerts_processed": 1,
  "investigation_id": "inv-123456"
}
```

---

### Custom Alert Webhook

Receive alerts from custom sources.

```
POST /webhook/custom
Content-Type: application/json
```

**Request Body:**

```json
{
  "service_name": "payment-api",
  "namespace": "production",
  "cluster": "main",
  "severity": "critical",
  "alert_name": "HighErrorRate",
  "description": "Error rate is above 5%",
  "labels": {
    "team": "payments",
    "environment": "production"
  },
  "slack_channel": "C123456789",
  "slack_thread_ts": "1234567890.123456"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `service_name` | string | Yes | Name of the affected service |
| `namespace` | string | No | Kubernetes namespace |
| `cluster` | string | No | Kubernetes cluster name |
| `severity` | string | No | Alert severity (critical, warning, info) |
| `alert_name` | string | No | Name of the alert |
| `description` | string | No | Alert description |
| `labels` | object | No | Additional labels |
| `slack_channel` | string | No | Slack channel to post results |
| `slack_thread_ts` | string | No | Slack thread timestamp |

**Response:**

```json
{
  "status": "accepted",
  "investigation_id": "inv-123456",
  "message": "Investigation started for payment-api"
}
```

---

### Get Investigation Status

Check the status of an investigation.

```
GET /investigations/{investigation_id}
```

**Response:**

```json
{
  "id": "inv-123456",
  "status": "completed",
  "service_name": "payment-api",
  "started_at": "2024-01-15T10:00:00Z",
  "completed_at": "2024-01-15T10:00:45Z",
  "analysis": {
    "summary": "Database connection pool exhausted",
    "root_cause": "Connection leak in v2.3.0 release",
    "confidence": "high",
    "suggested_actions": [
      "Rollback to v2.2.9",
      "Increase connection pool size"
    ]
  }
}
```

---

### Submit Feedback

Provide feedback on an analysis.

```
POST /feedback/{incident_id}
Content-Type: application/json
```

**Request Body:**

```json
{
  "feedback_type": "correct",
  "actual_root_cause": "Optional: the actual root cause",
  "actual_solution": "Optional: what actually fixed it",
  "user_id": "U123456"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `feedback_type` | string | Yes | One of: `correct`, `partial`, `incorrect` |
| `actual_root_cause` | string | No | What was the actual root cause |
| `actual_solution` | string | No | What solution actually worked |
| `user_id` | string | No | User providing feedback |

**Response:**

```json
{
  "status": "recorded",
  "feedback_id": 42,
  "learned_solution_created": true
}
```

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "error": "error_code",
  "message": "Human-readable error message",
  "details": {}
}
```

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 202 | Accepted (async processing) |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing/invalid auth |
| 404 | Not Found - Resource doesn't exist |
| 500 | Internal Server Error |
| 503 | Service Unavailable - Dependencies down |

---

## Rate Limiting

The API does not currently implement rate limiting. For production deployments, consider adding rate limiting at the ingress level.

---

## Authentication

The webhook endpoints do not require authentication by default. For production:

1. **Alertmanager**: Configure webhook authentication
2. **Custom Webhook**: Add API key header validation
3. **Use network policies** to restrict access

Example with API key:

```bash
curl -X POST http://localhost:8000/webhook/custom \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"service_name": "test"}'
```
