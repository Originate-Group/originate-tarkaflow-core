---
type: feature
title: "{title}"
parent_id: {parent_id}
status: {status}
tags: {tags}
---

# Feature: {title}

<!--
A Feature is the ATOMIC UNIT OF WORK handed to a developer (human or AI).
It must be self-contained and implementable without additional context.

Child Requirements are OPTIONAL decomposition - use them to break down
complex features, but a well-written Feature can be implemented directly.

READY FOR IMPLEMENTATION when:
- User Story clearly states WHO, WHAT, WHY
- Acceptance Criteria are observable and testable
- Scope Boundaries are explicit
-->

## User Story

**As a** [type of user]
**I want** [goal/desire]
**So that** [benefit/value]

<!--
Focus on WHO benefits and WHAT they can do.
Do NOT describe HOW the system implements it.

GOOD: "As a product manager, I want to organize requirements hierarchically
      so that I can manage complex projects with clear relationships"

BAD: "As a user, I want the system to use recursive CTEs to query the
     parent_id foreign key so that hierarchical data is retrieved efficiently"
-->

## Overview

{description}

<!--
2-3 sentences: What this feature enables and why it matters.
Describe the CAPABILITY from the user's perspective.
-->

## Acceptance Criteria

<!--
What must be TRUE for this feature to be complete?
Write from the USER's perspective - what they can observe/verify.

GOOD: "User sees all child requirements when viewing a parent"
GOOD: "System prevents creating orphaned requirements"

BAD: "API returns 400 if parent_id is invalid UUID"
BAD: "Database constraint enforces referential integrity"
-->

- [ ] [User-observable outcome 1]
- [ ] [User-observable outcome 2]
- [ ] [Business rule that must be enforced]

## Success Criteria

<!--
How do we know this delivers value? Business outcomes only.
-->

- [ ] [User can accomplish their goal]
- [ ] [Measurable business outcome]

## Scope Boundaries

**In Scope**: [What this feature delivers]

**Out of Scope**: [Explicitly excluded - may be future work]
