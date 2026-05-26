# Observability

!!! info "Status"
    **Partial** — audit emission, structured logging, and the CI smoke pipeline are built. The Grafana + Prometheus + Loki + Tempo stack is wired in `pyproject.toml` but the production dashboards are Planned (Sprint 7).

The MIS emits three streams of telemetry. The audit chain is the legally-mandated one; the other two help you keep the platform up.

## The three streams

| Stream | What it is | Where it goes today | Where it will go |
|---|---|---|---|
| **Audit events** | One `AuditEvent` per read or write of personal data | `security.AuditEvent` table with a per-row hash chain | Loki + long-term S3 archive |
| **Application logs** | Django + Celery stdout/stderr | Container stdout | Loki via promtail |
| **Metrics + traces** | OpenTelemetry from Django middleware | Disabled in dev | Prometheus + Tempo (Planned S7) |

## Audit events

Every personal-data read or write writes one `AuditEvent` row. The model has these fields:

| Field | Meaning |
|---|---|
| `id` | ULID |
| `created_at` | UTC timestamp |
| `actor` | Operator username, or `anonymous` |
| `action` | e.g. `household_read`, `dqa_rule_approved`, `dashboard_read` |
| `entity` | e.g. `household`, `dqa_rule`, `rpt_dashboard` |
| `entity_id` | Foreign reference |
| `reason` | Free text (`why`), required for sensitive reads |
| `ip_address` | Caller IP |
| `user_agent` | UA string |
| `prev_hash` | Hash of the previous AuditEvent (chains all rows) |
| `row_hash` | Hash of this row's content + prev_hash |

The PostgreSQL trigger `security/0002_auditevent_chain_trigger.py` enforces `row_hash` and `prev_hash` integrity at INSERT time. **The trigger is Postgres-only.** On sqlite the chain silently degrades to no-ops, which is why production must run on PostgreSQL (`security.E004` system check).

### Reading the audit chain

The DPO console reads from `/api/v1/security/audit-events/` with full ABAC scoping. Filters: `actor`, `action`, `entity`, `created_at__gte`, `created_at__lte`.

For local inspection:

```bash
python manage.py shell -c "from apps.security.models import AuditEvent; \
print(AuditEvent.objects.order_by('-created_at')[:10].values('actor','action','entity','entity_id','created_at'))"
```

### Anomaly detection (Planned)

The threat model (T1) calls for an anomaly feed reading the AuditEvent stream and flagging:

- Bulk reads outside business hours.
- Unusual geographic-scope drift for an operator.
- Repeated `403` reasons against the same record.

The feed will land in Sprint 9.

## Application logs

Container stdout/stderr is the source. Local dev:

```bash
docker compose logs -f web
```

Production (Planned): `promtail` ships container logs to Loki with labels `app=nsr-mis-api`, `module=<INT|DAT|DQA|...>`, `env=<pilot|prod>`.

## Metrics and traces (Planned)

The settings file is shaped to receive OpenTelemetry middleware. The configuration ships in Sprint 7 alongside the Helm chart. Expected dashboards:

- API latency p50/p95/p99 per endpoint.
- Connector run throughput and quarantine rate per SourceSystem.
- PMT recompute latency.
- Audit-event ingest rate.
- DRS extract size distribution.

## Health and readiness

| Endpoint | Purpose |
|---|---|
| `/healthz/` | Liveness (Planned) |
| `/readyz/` | Readiness, checks DB + Redis (Planned) |

Until those land, the K8s probe target is `/api/schema/` which exercises Django, the router, and DRF.

## Backups

The audit chain is the backbone. Loss of audit rows is irrecoverable.

| Asset | Backup target | Frequency |
|---|---|---|
| PostgreSQL data | NITA-U S3-compatible store (Planned) | Hourly WAL + nightly base |
| AuditEvent table | Same as DB plus long-term cold archive | Daily snapshot |
| Object store (MinIO) | Cross-region MinIO replica | Continuous |
| Keycloak realm export | Versioned in `/infrastructure/keycloak/` | On change |

Detailed RPO/RTO targets land in the DR runbook (Planned Sprint 8).

## Related

- ADR-0008 — Pagination and throttling (rate-limit shape that feeds metrics)
- `/docs/threat_model.md`
- `/docs/audit/2026-05-21_source_of_truth_audit.md`
