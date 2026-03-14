"""Constants for audit logging system.

This module defines all magic numbers and configuration constants used throughout
the audit logging system to improve maintainability and prevent inconsistencies.
"""

# Pagination and export limits
DEFAULT_PAGE_SIZE = 100
"""Default number of audit logs per page."""

MAX_PAGE_SIZE = 1000
"""Maximum number of audit logs that can be requested per page."""

EXPORT_BATCH_SIZE = 1000
"""Batch size for streaming CSV/JSONL exports to prevent memory exhaustion."""

MAX_EXPORT_RECORDS_DEFAULT = 50000
"""Default maximum records for export.

This prevents memory exhaustion and ensures reasonable response times.
Can be overridden via max_records query parameter.
"""

# Retention policy constraints
MIN_RETENTION_DAYS = 1
"""Minimum retention period for audit logs (1 day)."""

MAX_RETENTION_DAYS = 2555
"""Maximum retention period for audit logs (approximately 7 years).

This aligns with common regulatory requirements like GDPR (up to 7 years for
certain financial and legal records) and Swedish Arkivlagen.
"""

DEFAULT_RETENTION_DAYS = 365
"""Default retention period for audit logs (1 year).

Complies with Swedish Arkivlagen and GDPR requirements for most data categories.
"""

# Field length constraints
MAX_DESCRIPTION_LENGTH = 500
"""Maximum length of audit log description field."""

MAX_ERROR_MESSAGE_LENGTH = 2000
"""Maximum length of error message field (allows for stack traces)."""

MAX_USER_AGENT_LENGTH = 1000
"""Maximum length of user agent string (some browsers send very long strings)."""

# Query performance
QUERY_SLOW_THRESHOLD_MS = 500
"""Threshold in milliseconds for logging slow audit queries."""

# Worker and job settings
WORKER_QUEUE_NAME = "log_audit_event"
"""ARQ worker queue name for async audit logging."""

AUDIT_WORKER_TIMEOUT_SECONDS = 30
"""Maximum time for audit worker task execution."""

# Security
CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
"""Characters that trigger CSV injection protection."""
