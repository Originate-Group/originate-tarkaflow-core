---
type: requirement
title: "{title}"
parent_id: {parent_id}
tags: {tags}
depends_on: []
# IMPORTANT: Populate dependencies during creation, especially in batch operations!
# List requirement UUIDs or human-readable IDs this requirement depends on
# Example: ["RAAS-REQ-001", "RAAS-FEAT-028"]
# Missing dependencies during batch creation causes implementation issues later
adheres_to: []
# OPTIONAL: List guardrails this requirement adheres to
# Can use UUID (e.g., "123e4567-e89b-12d3-a456-426614174000")
# or human-readable ID (e.g., "GUARD-SEC-001")
# Use list_guardrails tool to discover available guardrails
# NOTE: status defaults to "draft" on creation; id and timestamps are system-managed
---

# Requirement: {title}

<!--
Requirements are OPTIONAL decomposition of a parent Feature.
Use them when a Feature is complex enough to benefit from breakdown.

A Requirement should be completable in a single focused session.
If you need Requirements, the parent Feature is probably complex.
If the Feature is simple, implement it directly without Requirements.
-->

## Description

{description}

<!--
Describe the specific CAPABILITY the system must have.
This should be implementable by one developer.

Ask yourself: "Could this be implemented 3 different valid ways?"
If no, you're being too prescriptive.

GOOD: "System must rate-limit API requests per user, returning appropriate
      error when limit exceeded, with limits surviving service restarts"

BAD: "Create Redis key rate:{user_id}:{minute}, increment on each request,
     expire after 60 seconds, return 429 if count > 100"
-->

## Acceptance Criteria

<!--
What must be TRUE when this is complete?
Focus on OBSERVABLE behavior, not implementation details.

GOOD: "Requests beyond limit receive 429 response with retry guidance"
BAD: "Redis INCR returns value > 100"
-->

- [ ] [Observable behavior 1]
- [ ] [Observable behavior 2]
- [ ] [Quality attribute if critical - e.g., "responds within 100ms"]

## Constraints

<!--
Only include constraints that MUST be followed.
These limit Code Claude's implementation choices for good reason.

GOOD: "Must use existing authentication system" (integration constraint)
GOOD: "PII must be encrypted at rest" (compliance constraint)

BAD: "Use Redis for caching" (implementation choice - let Code Claude decide)
BAD: "Create index on user_id column" (optimization detail)
-->
