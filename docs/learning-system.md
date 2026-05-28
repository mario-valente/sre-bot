# Learning System

SRE Bot features a learning system that improves incident analysis over time based on human feedback.

## How It Works

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

### The Learning Loop

1. **Alert Analysis**: Bot analyzes the incident using all available data sources
2. **Human Feedback**: User validates the analysis via Slack buttons
3. **Solution Stored**: If marked "Correct", the solution is saved to the database
4. **Future Incidents**: When a similar alert occurs, the bot retrieves historical solutions
5. **Enhanced Analysis**: LLM uses past solutions as context for better recommendations

---

## Feedback Buttons

After each analysis, the bot displays three feedback buttons in Slack:

| Button | Action | Learning Effect |
|--------|--------|-----------------|
| **Correct** | Saves solution to database | Solution will be suggested for similar future incidents |
| **Partially Correct** | Records partial feedback | Tracked for improvement but not used as solution |
| **Incorrect** | Records negative feedback | Helps identify patterns where bot struggles |

---

## Solution Matching

When a new alert arrives, the bot searches for historical solutions using a priority-based matching system:

### Match Priority

1. **Exact Match** (Score: 1.0)
   - Same `alert_name` + `service_name` + `namespace`
   - Most specific and reliable match

2. **Service Match** (Score: 0.8)
   - Same `alert_name` + `service_name` (any namespace)
   - Useful when same alert type affects service in different environments

3. **Service Patterns** (Score: 0.6)
   - Same `service_name` (different alert types)
   - Captures service-specific patterns

4. **Generic Solutions** (Score: 0.5)
   - Same `alert_name` (across different services)
   - Useful for common alert types like "HighMemoryUsage"

### Example

If you have a `HighErrorRate` alert for `payment-api` in `production`:

```python
# Priority 1: Exact match
alert_name="HighErrorRate", service="payment-api", namespace="production"

# Priority 2: Same service and alert
alert_name="HighErrorRate", service="payment-api", namespace="staging"

# Priority 3: Same service
alert_name="HighLatency", service="payment-api", namespace="production"

# Priority 4: Same alert type
alert_name="HighErrorRate", service="order-api", namespace="production"
```

---

## Database Schema

The learning system uses three tables:

### `incidents`

Stores all incident investigations:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `alert_name` | String | Alert name |
| `service_name` | String | Affected service |
| `namespace` | String | Kubernetes namespace |
| `severity` | String | Alert severity |
| `analysis_summary` | Text | Generated summary |
| `root_cause` | Text | Identified root cause |
| `suggested_actions` | JSON | List of recommended actions |
| `confidence` | String | Confidence level |
| `source` | String | Alert source (slack, webhook) |
| `created_at` | DateTime | When incident occurred |

### `incident_feedback`

Human feedback on analyses:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `incident_id` | Integer | Foreign key to incidents |
| `feedback_type` | String | correct, partial, incorrect |
| `actual_root_cause` | Text | Optional: actual root cause |
| `actual_solution` | Text | Optional: what actually fixed it |
| `user_id` | String | Slack user who gave feedback |
| `created_at` | DateTime | When feedback was given |

### `learned_solutions`

Validated solutions for reuse:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `alert_name` | String | Alert name pattern |
| `service_name` | String | Service pattern |
| `namespace` | String | Namespace pattern |
| `root_cause` | Text | Validated root cause |
| `solution` | Text | Validated solution |
| `times_used` | Integer | Usage counter |
| `success_rate` | Float | Success percentage |
| `created_at` | DateTime | When created |
| `last_used_at` | DateTime | Last time used |

---

## Usage Statistics

The bot tracks how often solutions are used and their success rate:

```python
# When a historical solution is applied
solution.times_used += 1
solution.last_used_at = now()

# When feedback is received
if feedback == "correct":
    solution.success_rate = (success_rate * (times_used - 1) + 1.0) / times_used
elif feedback == "incorrect":
    solution.success_rate = (success_rate * (times_used - 1) + 0.0) / times_used
```

---

## Providing Detailed Feedback

When marking an analysis as "Partially Correct" or "Incorrect", you can provide additional details:

### Via Slack Thread

Reply in the thread with the actual root cause:

```
The actual issue was a misconfigured environment variable,
not a memory leak as suggested.
```

The bot will store this information for future improvement.

### Via API (Future)

```bash
POST /api/feedback/{incident_id}
{
  "feedback_type": "incorrect",
  "actual_root_cause": "Environment variable misconfiguration",
  "actual_solution": "Fixed DATABASE_URL in ConfigMap"
}
```

---

## Best Practices

1. **Always provide feedback** - Even if just clicking "Correct", it helps the system learn

2. **Be specific** - When providing detailed feedback, include:
   - What the actual root cause was
   - What steps fixed the issue
   - Any relevant context

3. **Correct promptly** - Feedback is most useful when given soon after the incident

4. **Review learned solutions** - Periodically audit stored solutions for accuracy

---

## Future Improvements

- [ ] Vector-based semantic search for similar incidents
- [ ] Automatic solution expiration for outdated patterns
- [ ] Confidence decay over time without validation
- [ ] Solution clustering for pattern discovery
- [ ] Export/import of learned solutions
