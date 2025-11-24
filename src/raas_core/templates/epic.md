---
type: epic
title: "{title}"
tags: {tags}
depends_on: []
# OPTIONAL: List epic UUIDs or human-readable IDs this epic depends on
# Epic dependencies are rare (cross-cutting concerns, shared infrastructure)
# Example: ["RAAS-EPIC-001", "RAAS-EPIC-005"]
adheres_to: []
# OPTIONAL: List guardrails this requirement adheres to
# Can use UUID (e.g., "123e4567-e89b-12d3-a456-426614174000")
# or human-readable ID (e.g., "GUARD-SEC-001")
# Use list_guardrails tool to discover available guardrails
# NOTE: status defaults to "draft" on creation; id and timestamps are system-managed
---

# Epic: {title}

## Vision

{description}

<!--
WRITE 2-4 sentences answering:
- What business problem does this solve?
- Who benefits and how?
- What does success look like from a user/business perspective?

DO NOT INCLUDE: technology choices, database designs, API structures,
deployment approaches, or any implementation details. Those decisions
belong to Code Claude during implementation.
-->

## Success Criteria

<!--
List measurable BUSINESS outcomes, not technical metrics.

GOOD: "Users can create requirements 3x faster than current process"
GOOD: "Zero requirements drift between AI tools over 30 days"
GOOD: "SOC2 compliance audit passed"

BAD: "API response time under 100ms"
BAD: "Database supports 10,000 concurrent connections"
BAD: "Docker containers deploy in under 5 minutes"
-->

- [ ] [Business outcome 1]
- [ ] [Business outcome 2]
- [ ] [Business outcome 3]

## Scope Boundaries

**In Scope**: [What capabilities this epic delivers]

**Out of Scope**: [What this epic explicitly does NOT include]

<!--
Define boundaries in terms of CAPABILITIES, not implementation.

GOOD: "In Scope: Multi-user collaboration on requirements"
BAD: "In Scope: WebSocket real-time sync with Redis pub/sub"
-->

## Business Dependencies

<!--
List only BUSINESS prerequisites - things that must be true or decided
before this work makes sense. Do NOT list technical dependencies like
databases, frameworks, or infrastructure choices.

GOOD: "Security policy must be approved before handling PII"
GOOD: "Pricing model must be finalized before building tier features"

BAD: "PostgreSQL database must be provisioned"
BAD: "Keycloak must be configured with realms"
-->
