---
type: component
title: "{title}"
parent_id: {parent_id}
status: {status}
priority: {priority}
tags: {tags}
---

<!--
=============================================================================
COMPONENT WRITING GUIDELINES
=============================================================================

A COMPONENT represents a discrete, deployable unit of functionality.
Think: "What gets built and shipped as a unit?"

Typically: 1 repository, 1 service, 1 agent, or 1 major subsystem.

FOCUS ON:
✅ What this component does and why it exists
✅ Integration context (what it connects to)
✅ Security and privacy considerations
✅ Phased delivery approach (MVP → Enhancement → Future)

AVOID:
❌ Implementation details (save for Features/Requirements)
❌ Code examples or technical specifications
❌ Detailed designs or mockups
❌ Step-by-step procedures

INTEGRATION CONTEXT:
Every component should state:
- Primary data sources (where data comes from)
- External dependencies (what systems it needs)
- Integration patterns (sync/async, real-time/batch)
- Fallback behavior (what happens if dependencies fail)

SECURITY & PRIVACY:
Address if applicable:
- Data classification (PII, financial, confidential)
- Security controls needed (encryption, audit logging)
- Compliance requirements (GDPR, SOC2, etc.)
- Privacy impact assessment

TAGGING FOR DISCOVERABILITY:
Use tags to enable cross-cutting queries:
- integration:asana, integration:xero, integration:email
- data:pii, data:financial, data:confidential
- security:encryption-required, security:audit-logging
- compliance:gdpr, compliance:soc2
- domain:sales, domain:finance, foundation, automation
- priority:p0, quick-win, high-roi

EXAMPLE:
"Lead Scoring Engine analyzes prospect behavior and assigns scores based on
engagement patterns. Integrates with CRM via API sync, processes email events
in real-time, and stores scores in PostgreSQL. Handles PII requiring encryption
and GDPR compliance. MVP: basic scoring algorithm. Enhancement: ML-based scoring."
-->

# Component: {title}

## Overview

{2-3 sentences: What this component does, why it exists, what value it delivers.}

## Core Functionality

What key capabilities does this component provide?

- [Capability 1]
- [Capability 2]
- [Capability 3]

## Integration Context

**Data Sources**:
- [Where does data come from? Databases, APIs, files, etc.]

**External Dependencies**:
- [What external systems/services does this require? Include auth needs.]

**Integration Patterns**:
- [How does data flow? Sync frequency? Real-time vs batch? Webhook vs polling?]

**Fallback Behavior**:
- [What happens if dependencies are unavailable? How does it degrade?]

**Data Ownership**:
- [Is this component the source of truth, or does it mirror external data?]

## Security & Privacy

**Data Handled**: [PII, financial, confidential, public - what types?]

**Security Controls**: [Encryption, audit logging, access control, MFA - what's required?]

**Compliance**: [GDPR, SOC2, PCI-DSS, HIPAA - what applies?]

**Privacy Impact**: [Does it collect/process personal data? What are implications?]

**Attack Surface**: [What are the main security risks to consider?]

## Implementation Phases

**Phase 1 (MVP)**:
- [Minimum viable functionality that delivers value]
- [Keep it simple - manual processes where acceptable]

**Phase 2 (Enhancement)**:
- [Improvements that make it better/faster/more reliable]
- [Build on MVP success]

**Phase 3 (Future)**:
- [Nice-to-haves that aren't time-critical]
- [Advanced features based on user feedback]

## Success Criteria

**Technical Success**:
- [ ] [Performance metrics - response times, throughput, uptime]
- [ ] [Reliability metrics - error rates, availability]
- [ ] [Integration health - sync success, data quality]

**Business Success**:
- [ ] [User outcomes - time saved, efficiency gained]
- [ ] [Adoption metrics - active users, feature usage]
- [ ] [ROI metrics - cost vs value]

## Dependencies

**Requires** (blocks this component):
- [Components/systems that must exist first]

**Enables** (this component blocks):
- [Components/capabilities that depend on this]

**Integrates With** (peers):
- [Components this works alongside]

## Notes

**Constraints**: [Limitations or boundaries to be aware of]

**Future Extensibility**: [How this might evolve]

**Key Decisions**: [Important choices made and why]
