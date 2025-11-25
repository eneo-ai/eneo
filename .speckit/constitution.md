# Audit System Constitution

## Core Principles

This constitution defines the guiding principles for audit functionality in our multi-tenant SaaS platform, balancing regulatory compliance, security, performance, and maintainability.

---

## 1. Regulatory Compliance

### 1.1 GDPR Compliance (Article 15: Right of Access)
**Principle**: Users have the right to access their personal data and understand how it's processed.

**Requirements**:
- All audit logs containing personal data must be accessible to data subjects
- Audit records must include: what data was accessed, when, by whom, and for what purpose
- Data subjects can request their complete audit trail within 30 days
- Audit data must be provided in a structured, commonly used, machine-readable format
- Audit logs must respect data retention policies (typically 1-2 years, configurable)

**Implementation Guidelines**:
- Provide API endpoints for users to query their own audit logs
- Filter audit logs by user_id to show user-specific activities
- Include clear descriptions of actions in audit entries
- Support data export in JSON/CSV formats
- Implement automated retention policy enforcement

### 1.2 Swedish Public Sector Requirements (Offentlighetsprincipen)
**Principle**: Public sector activities must be transparent and accountable.

**Requirements**:
- Audit logs for public sector tenants must support disclosure requests
- Activities by public officials must be comprehensively logged
- System must support efficient retrieval for freedom of information requests
- Sensitive operations (access to citizen data) must be auditable
- Audit logs must be tamper-evident

**Implementation Guidelines**:
- Tag audit entries with sensitivity levels (public, internal, confidential)
- Provide search/filter capabilities for disclosure officers
- Log all access to citizen/resident data with justification fields
- Implement write-once audit storage to prevent tampering
- Support audit log signing/hashing for integrity verification

---

## 2. Multi-Tenancy Isolation & Security

### 2.1 Tenant Isolation (MANDATORY)
**Principle**: Audit data must be strictly isolated between tenants. Cross-tenant data leakage is a critical security violation.

**Requirements**:
- **Every audit query MUST filter by tenant_id** - no exceptions
- Audit logs must never reveal information about other tenants
- Database constraints must enforce tenant_id presence
- Application-level guards must prevent accidental cross-tenant queries
- Tenant isolation must be validated in integration tests

**Implementation Guidelines**:
```python
# ✅ CORRECT: Always filter by tenant_id
def get_audit_logs(tenant_id: UUID, filters: AuditFilters):
    return db.query(AuditLog).filter(
        AuditLog.tenant_id == tenant_id,
        # ... other filters
    )

# ❌ WRONG: Missing tenant_id filter (security violation)
def get_audit_logs(filters: AuditFilters):
    return db.query(AuditLog).filter(...)
```

- Use database row-level security (RLS) as defense-in-depth
- Implement `@require_tenant_context` decorators for audit endpoints
- Audit queries in multi-tenant contexts must be code-reviewed
- Add linting rules to detect missing tenant_id filters

### 2.2 Access Control
**Principle**: Audit logs are sensitive; access must be controlled and logged.

**Requirements**:
- Only authorized roles can view audit logs (admin, compliance officer)
- Access to audit logs must itself be audited (meta-auditing)
- API keys and credentials used for audit access must be rotated
- Audit log access attempts must be monitored for anomalies

**Implementation Guidelines**:
- Implement RBAC for audit log access
- Log all audit log queries (who, when, what filters)
- Rate-limit audit log API endpoints
- Alert on suspicious patterns (bulk exports, unusual times)

---

## 3. Performance & Scalability

### 3.1 Asynchronous Logging
**Principle**: Audit logging must not degrade application performance.

**Requirements**:
- Audit writes must be non-blocking (async/background tasks)
- Failed audit writes must be retried with exponential backoff
- Critical operations must not fail due to audit failures (graceful degradation)
- Audit write latency must be monitored and optimized

**Implementation Guidelines**:
- Use ARQ (existing async task queue) for audit writes
- Buffer audit events in memory before batch writes
- Implement circuit breakers for audit subsystem failures
- Set SLOs: 95th percentile audit write latency < 100ms (background)

### 3.2 Query Optimization
**Principle**: Audit log queries must be efficient even with millions of records.

**Requirements**:
- All audit log queries must use indexes (tenant_id, timestamp, user_id)
- Pagination must be enforced (max 1000 records per query)
- Full-text search must use optimized solutions (Elasticsearch or PostgreSQL FTS)
- Query performance must be tested at scale (10M+ records)

**Implementation Guidelines**:
```sql
-- Required indexes
CREATE INDEX idx_audit_tenant_timestamp ON audit_logs(tenant_id, timestamp DESC);
CREATE INDEX idx_audit_tenant_user ON audit_logs(tenant_id, user_id);
CREATE INDEX idx_audit_tenant_resource ON audit_logs(tenant_id, resource_type, resource_id);
```

- Use cursor-based pagination for large result sets
- Implement query result caching for common filters
- Set query timeouts to prevent long-running queries
- Monitor slow query logs and optimize

### 3.3 Data Retention & Archival
**Principle**: Audit logs must balance compliance needs with storage costs.

**Requirements**:
- Default retention: 1 year (configurable per tenant)
- Automated archival to cold storage after retention period
- Archived logs must remain accessible for compliance
- Deletion must be irreversible and logged

**Implementation Guidelines**:
- Use PostgreSQL table partitioning by month/quarter
- Archive old partitions to S3/object storage
- Implement background jobs for retention enforcement
- Provide tenant admins with retention configuration UI

---

## 4. Maintainability & Team Ownership

### 4.1 Domain-Driven Design (DDD)
**Principle**: Audit functionality must follow established DDD patterns for consistency.

**Requirements**:
- Audit domain must have clear bounded context
- Use domain entities, value objects, and repositories
- Encapsulate business logic in domain services
- Follow existing project structure and conventions

**Implementation Guidelines**:
```
src/intric/
  domains/
    audit/
      entities.py        # AuditLog entity
      value_objects.py   # AuditAction, AuditResource
      repositories.py    # AuditLogRepository
      services.py        # AuditService (business logic)
      schemas.py         # Pydantic schemas for API
  api/
    audit/
      routes.py          # FastAPI endpoints
```

- Use repository pattern for data access
- Inject dependencies (database, cache) through DI
- Write domain logic in pure Python (testable)
- Keep API layer thin (validation, serialization only)

### 4.2 Proven Approaches Over Innovation
**Principle**: Prefer battle-tested solutions over novel architectures.

**Requirements**:
- Use existing project patterns (ARQ, SQLAlchemy, Pydantic)
- Avoid introducing new frameworks/libraries unless justified
- Follow team coding standards and conventions
- Document deviations from standard patterns

**Implementation Guidelines**:
- Use SQLAlchemy async for database operations (existing pattern)
- Use ARQ for background tasks (existing pattern)
- Use Pydantic for validation (existing pattern)
- Use existing authentication/authorization middleware
- Reuse existing logging, monitoring, error handling

### 4.3 Testing & Quality
**Principle**: Audit functionality is critical; testing must be comprehensive.

**Requirements**:
- Unit tests for all business logic (>80% coverage)
- Integration tests for multi-tenancy isolation (critical)
- Performance tests at scale (10M+ records)
- Security tests for tenant isolation and access control

**Implementation Guidelines**:
```python
# Critical integration test
def test_audit_logs_tenant_isolation():
    tenant1_logs = get_audit_logs(tenant_id=tenant1)
    tenant2_logs = get_audit_logs(tenant_id=tenant2)

    assert not any(log.tenant_id == tenant2 for log in tenant1_logs)
    assert not any(log.tenant_id == tenant1 for log in tenant2_logs)
```

- Test audit writes don't block application flow
- Test graceful degradation on audit failures
- Test retention policy enforcement
- Test GDPR data export functionality

---

## 5. KISS Principle (Keep It Simple, Stupid)

### 5.1 Simplicity Over Complexity
**Principle**: Choose the simplest solution that meets requirements.

**Requirements**:
- Start with database-backed audit logs (PostgreSQL)
- Avoid over-engineering (no Kafka, no event sourcing unless needed)
- Use straightforward data models (avoid premature optimization)
- Incremental complexity (add features when needed, not speculatively)

**Implementation Guidelines**:
- **Start**: Simple table in PostgreSQL with proper indexes
- **Scale**: Add table partitioning when >10M records
- **Search**: Use PostgreSQL full-text search before Elasticsearch
- **Caching**: Add Redis caching only if query latency degrades

### 5.2 Clear Data Model
**Principle**: Audit logs must have a simple, understandable schema.

**Requirements**:
```python
class AuditLog(Base):
    id: UUID
    tenant_id: UUID  # MANDATORY - enforced by DB constraint
    timestamp: datetime
    user_id: UUID | None
    action: str  # e.g., "user.login", "space.created"
    resource_type: str | None  # e.g., "Space", "Assistant"
    resource_id: UUID | None
    details: dict  # JSONB for flexible metadata
    ip_address: str | None
    user_agent: str | None
```

- Use descriptive action names (verb.object pattern)
- Store structured details in JSONB (flexible, queryable)
- Avoid deeply nested structures
- Document common query patterns

### 5.3 Pragmatic Trade-offs
**Principle**: Balance perfection with delivery; iterate based on feedback.

**Requirements**:
- MVP: Core logging + tenant isolation + GDPR export
- Phase 2: Advanced search + analytics + alerting
- Phase 3: Compliance reporting + visualization
- Avoid implementing unused features

**Implementation Guidelines**:
- Start with essential actions (login, data access, admin operations)
- Add more action types based on compliance needs
- Implement advanced analytics only if requested
- Measure feature usage; deprecate unused functionality

---

## 6. Operational Excellence

### 6.1 Monitoring & Alerting
**Principle**: Audit system health must be observable.

**Requirements**:
- Monitor audit write success/failure rates
- Alert on audit write failures exceeding threshold
- Track audit query performance (latency, volume)
- Dashboard for audit system health metrics

### 6.2 Documentation
**Principle**: Audit functionality must be well-documented.

**Requirements**:
- API documentation (OpenAPI/Swagger)
- Admin guide for tenant audit configuration
- Developer guide for adding new audit actions
- Compliance guide for GDPR/public sector requirements

---

## Decision Framework

When implementing audit features, ask:

1. **Compliance**: Does this meet GDPR/public sector requirements?
2. **Security**: Is tenant isolation guaranteed? Is access controlled?
3. **Performance**: Will this scale to millions of records?
4. **Simplicity**: Is this the simplest solution that works?
5. **Maintainability**: Does this follow project patterns?

If the answer to any is "no", revisit the design.

---

## Revision History

- **2025-01-08**: Initial constitution created
- Principles established based on regulatory requirements, security best practices, and team conventions
