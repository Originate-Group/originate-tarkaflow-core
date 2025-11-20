---
type: feature
title: "{title}"
parent_id: {parent_id}
status: {status}
priority: {priority}
tags: {tags}
---

<!--
=============================================================================
FEATURE WRITING GUIDELINES
=============================================================================

A FEATURE represents a user-facing capability that delivers specific value.
Think: "What can users do? What problem does this solve for them?"

FOCUS ON:
✅ User value and benefits (the "why")
✅ User stories with clear actors
✅ Acceptance criteria from user perspective
✅ End-to-end workflows and interactions
✅ Business rules and constraints

AVOID:
❌ Implementation steps or algorithms
❌ Code examples or database schemas
❌ API endpoint definitions or HTTP methods
❌ Technology-specific details (libraries, frameworks)
❌ "How" to build it (save for Requirements)

USER STORY FORMAT:
As a [role]
I want [capability]
So that [benefit]

OUTCOME-BASED DESCRIPTIONS:
✅ GOOD: "System validates that requirements follow proper parent-child
         relationships and prevents orphaned items"
❌ BAD: "Add CHECK constraint: (type='epic' AND parent_id IS NULL) OR
         (type!='epic' AND parent_id IS NOT NULL)"

✅ GOOD: "Audit trail captures who changed what and when, supporting
         compliance requirements and debugging"
❌ BAD: "Create audit_log table with columns: id, user_id, action,
         old_value, new_value, timestamp. Add trigger on UPDATE."

DATA MODELS - Describe Structure, Not Code:
✅ GOOD: "Audit record includes: action type, changed field, old value,
         new value, timestamp, user who made change"
❌ BAD: "class AuditRecord(BaseModel):
         id: UUID = Field(default_factory=uuid4)
         action: str"

GOOD FEATURE EXAMPLE:
"As a product manager, I want to organize requirements in a 4-level hierarchy
so that I can manage large projects with clear relationships from strategic
initiatives down to implementation details. The system must enforce parent-child
relationships, prevent orphaned requirements, and show me the complete tree
structure with visual hierarchy."

BAD FEATURE EXAMPLE:
"Implement 4-level hierarchy using self-referential foreign key in PostgreSQL:
parent_id UUID REFERENCES requirements(id) ON DELETE CASCADE
Add validation: if type='epic' then parent_id IS NULL
Use recursive CTE for tree queries: WITH RECURSIVE tree AS..."

KEY QUESTIONS TO ASK:
- Who is the user and what do they need?
- What value does this provide to them?
- How will users interact with this?
- What defines success from the user's perspective?
- Could you explain this to a non-technical stakeholder?
-->

# Feature: {title}

## Overview

{2-3 sentences describing what this feature enables users to do and why it matters. Focus on user value, not technical implementation.}

## User Stories

**As a** [type of user]
**I want** [goal/desire]
**So that** [benefit/value]

**As a** [another user type if applicable]
**I want** [goal/desire]
**So that** [benefit/value]

## Acceptance Criteria

What must be true for this feature to be considered complete? Write from the user's perspective.

- [ ] [User-observable behavior or outcome]
- [ ] [Business rule or constraint that must be enforced]
- [ ] [Edge case or error handling requirement]
- [ ] [Performance or quality requirement if critical]

## Success Criteria

How will we know this feature is working correctly and delivering value?

**User Success**:
- [ ] [User can accomplish their goal]
- [ ] [User experience is intuitive/fast/reliable]
- [ ] [Common workflows are smooth]

**Business Success**:
- [ ] [Measurable business outcome]
- [ ] [Adoption or usage metric]
- [ ] [Value delivered matches expectation]

## Dependencies

**Requires** (must exist before this feature):
- [Other features or capabilities this depends on]

**Enables** (this feature blocks):
- [Features that depend on this one]

## Notes

Any additional context, constraints, or considerations:

**Constraints**:
- [Technical or business limitations to be aware of]

**Future Enhancements**:
- [Ideas for future iterations, deliberately excluded from this feature]

**Known Trade-offs**:
- [Decisions made, alternatives considered]
