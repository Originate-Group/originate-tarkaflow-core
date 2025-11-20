---
type: requirement
title: "{title}"
parent_id: {parent_id}
status: {status}
priority: {priority}
tags: {tags}
---

<!--
=============================================================================
REQUIREMENT WRITING GUIDELINES
=============================================================================

A REQUIREMENT is an atomic, implementable work item that one developer can complete.
Think: "What specific capability must the system have?"

FOCUS ON:
✅ Specific capability or behavior
✅ Technical acceptance criteria
✅ Quality attributes (performance, security, reliability)
✅ What success looks like
✅ Data structures and models (by name and fields)

AVOID:
❌ Code snippets or pseudocode
❌ Step-by-step algorithms or procedures
❌ Specific library API calls
❌ Configuration file examples
❌ SQL queries or ORM code

OUTCOME vs IMPLEMENTATION:
✅ GOOD: "Validate JWT tokens using public key cryptography with signature
          verification, expiration checking, and claims validation"
❌ BAD: "Use python-jose library:
          jwt.decode(token, public_key, algorithms=['RS256'],
          options={'verify_exp': True})"

DATA MODELS - Structure, Not Code:
✅ GOOD: "User model contains: id (UUID, primary key), email (unique, indexed),
          role (enum: admin|developer|viewer), organization_id (foreign key),
          created_at (timestamp)"
❌ BAD: "class User(BaseModel):
          id: UUID = Field(default_factory=uuid4)
          email: EmailStr = Field(..., unique=True)
          role: Literal['admin', 'developer', 'viewer']"

TECHNOLOGY CHOICES - Name Tools, Not Usage:
✅ GOOD: "Use PostgreSQL row-level security policies to enforce tenant isolation"
❌ BAD: "CREATE POLICY tenant_isolation ON requirements
          FOR ALL USING (organization_id = current_setting('app.org_id')::uuid)"

API DESIGN - Describe Behavior, Not Syntax:
✅ GOOD: "Provide paginated list endpoint that returns 50 items per page by
          default, supports cursor-based navigation, and accepts filtering by
          status and tags"
❌ BAD: "GET /requirements?page=1&per_page=50&status=approved&tags=security
          Response: { items: [], next_cursor: string, total: number }"

GOOD REQUIREMENT EXAMPLE:
"Implement distributed rate limiting using token bucket algorithm to prevent
API abuse. System must track requests per user with 1-minute sliding windows,
limit to 100 requests per minute, return 429 status when exceeded, and include
Retry-After header. Rate limit data must survive service restarts."

BAD REQUIREMENT EXAMPLE:
"Implement rate limiting:
1. Create Redis key: rate:{user_id}:{minute}
2. redis.incr(key)
3. redis.expire(key, 60)
4. if count > 100: return 429
Use redis-py client with connection pooling"

KEY QUESTIONS TO ASK:
- Could this be implemented in 3 different valid ways? (If no, too prescriptive)
- Does this describe a capability or a recipe? (Capability = good)
- Can this be tested without knowing implementation details? (Should be yes)
-->

# Requirement: {title}

## Description

{description}

## Acceptance Criteria

- [ ] Implementation complete
- [ ] Tests passing
- [ ] Documentation updated

## Data Models & Structures

Define the information this requirement works with (entities, fields, relationships - no code).

## Quality Attributes

Performance targets, security constraints, reliability needs.

## Dependencies

Other requirements or systems this depends on.

## Notes

Additional context, edge cases, and considerations.
