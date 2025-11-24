---
type: component
title: "{title}"
parent_id: {parent_id}
tags: {tags}
depends_on: []
# IMPORTANT: Populate dependencies during creation, especially in batch operations!
# List requirement UUIDs or human-readable IDs this component depends on
# Example: ["RAAS-COMP-001", "RAAS-FEAT-042"]
# Missing dependencies during batch creation causes implementation issues later
adheres_to: []
# OPTIONAL: List guardrails this requirement adheres to
# Can use UUID (e.g., "123e4567-e89b-12d3-a456-426614174000")
# or human-readable ID (e.g., "GUARD-SEC-001")
# Use list_guardrails tool to discover available guardrails
# NOTE: status defaults to "draft" on creation; id and timestamps are system-managed
---

# Component: {title}

## Purpose

{description}

<!--
2-3 sentences: What this component does and why it exists.
Focus on the CAPABILITY it provides, not HOW it's built.

GOOD: "Manages lead scoring to help sales prioritize prospects by engagement level"
BAD: "PostgreSQL-backed service using Redis for caching that exposes REST APIs"
-->

## Capabilities

<!--
List what users/systems can DO with this component.
Each capability should be testable without knowing implementation.

GOOD: "Score leads based on engagement patterns"
GOOD: "Query historical scores for trend analysis"

BAD: "Expose GET /leads/:id/score endpoint"
BAD: "Store scores in leads.score_history table"
-->

- [Capability 1]
- [Capability 2]
- [Capability 3]

## Integrations

<!--
List WHICH systems this component exchanges data with.
Do NOT specify HOW (webhooks vs polling, sync vs async, etc.)

GOOD: "Exchanges data with: CRM system, Email platform, Analytics dashboard"
BAD: "Polls CRM API every 5 minutes, pushes to Analytics via webhook"
-->

**Connects To**: [List external systems by name]

**Data Ownership**: [Source of truth, or mirrors external data?]

## Data & Privacy

<!--
Describe WHAT data is handled and WHAT protection it needs.
Do NOT specify HOW to implement that protection.

GOOD: "Handles PII (names, emails) requiring encryption at rest"
BAD: "Use Fernet encryption with AES-256 for PII fields"
-->

**Data Classification**: [PII, financial, confidential, public]

**Compliance Requirements**: [GDPR, SOC2, etc. - if applicable]

## Success Criteria

<!--
Business outcomes only. Code Claude will determine technical metrics.

GOOD: "Sales team can identify top 10 prospects in under 30 seconds"
BAD: "API p95 latency under 200ms"
-->

- [ ] [Business outcome 1]
- [ ] [Business outcome 2]

## Scope Boundaries

**In Scope**: [What this component handles]

**Out of Scope**: [What belongs elsewhere]
