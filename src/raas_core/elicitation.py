"""
CRUD operations for AI-Driven Requirements Elicitation & Verification.
RAAS-EPIC-026

Components:
- RAAS-COMP-062: Question Framework Repository
- RAAS-COMP-063: Elicitation Session Management
- RAAS-COMP-064: Gap Analyzer

NOTE: CR-004 removed RAAS-COMP-060 (Clarification Points Management).
Clarifications are now managed as tasks with task_type='clarification'.
"""
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from .models import (
    QuestionFramework,
    ElicitationSession, ElicitationSessionStatus,
    Requirement,
)
from .schemas import (
    QuestionFrameworkCreate, QuestionFrameworkUpdate,
    ElicitationSessionCreate, ElicitationSessionUpdate, ElicitationSessionAddMessage,
    GapFinding,
)


# NOTE: CR-004 removed all clarification point functions. Use task tools instead:
# - create_clarification_point -> create_task(task_type='clarification')
# - list_clarification_points -> list_tasks(task_type='clarification')
# - get_clarification_point -> get_task()
# - resolve_clarification_point -> resolve_clarification_task()
# - get_my_clarifications -> get_my_tasks()
# - get_clarifications_for_artifact -> list_tasks(artifact_id=..., task_type='clarification')


# =============================================================================
# RAAS-COMP-062: Question Framework Repository
# =============================================================================


def create_question_framework(
    db: Session,
    data: QuestionFrameworkCreate,
    created_by: Optional[UUID] = None,
) -> QuestionFramework:
    """Create a new question framework."""
    framework = QuestionFramework(
        organization_id=data.organization_id,
        project_id=data.project_id,
        name=data.name,
        description=data.description,
        framework_type=data.framework_type,
        content=data.content,
        created_by=created_by,
    )
    db.add(framework)
    db.commit()
    db.refresh(framework)
    return framework


def get_question_framework(
    db: Session,
    framework_id: UUID,
) -> Optional[QuestionFramework]:
    """Get a question framework by ID."""
    return db.query(QuestionFramework).filter(QuestionFramework.id == framework_id).first()


def get_effective_framework(
    db: Session,
    organization_id: UUID,
    framework_type: str,
    project_id: Optional[UUID] = None,
) -> Optional[QuestionFramework]:
    """
    Get the effective framework for a given type, with project override.
    Project-level frameworks take precedence over org-level defaults.
    """
    # First try project-specific framework
    if project_id:
        framework = db.query(QuestionFramework).filter(
            and_(
                QuestionFramework.organization_id == organization_id,
                QuestionFramework.project_id == project_id,
                QuestionFramework.framework_type == framework_type,
                QuestionFramework.is_active == True,
            )
        ).first()
        if framework:
            return framework

    # Fall back to org-level default
    return db.query(QuestionFramework).filter(
        and_(
            QuestionFramework.organization_id == organization_id,
            QuestionFramework.project_id.is_(None),
            QuestionFramework.framework_type == framework_type,
            QuestionFramework.is_active == True,
        )
    ).first()


def list_question_frameworks(
    db: Session,
    organization_id: UUID,
    project_id: Optional[UUID] = None,
    framework_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[List[QuestionFramework], int]:
    """List question frameworks with filtering."""
    query = db.query(QuestionFramework).filter(
        QuestionFramework.organization_id == organization_id
    )

    if project_id is not None:
        # Include org-level defaults and project-specific
        query = query.filter(
            or_(
                QuestionFramework.project_id.is_(None),
                QuestionFramework.project_id == project_id,
            )
        )

    if framework_type:
        query = query.filter(QuestionFramework.framework_type == framework_type)

    if is_active is not None:
        query = query.filter(QuestionFramework.is_active == is_active)

    query = query.order_by(
        QuestionFramework.framework_type,
        QuestionFramework.project_id.nulls_first(),
        QuestionFramework.version.desc(),
    )

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def update_question_framework(
    db: Session,
    framework_id: UUID,
    data: QuestionFrameworkUpdate,
) -> Optional[QuestionFramework]:
    """Update a question framework (creates new version if content changes)."""
    framework = get_question_framework(db, framework_id)
    if not framework:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # If content is being updated, increment version
    if "content" in update_data and update_data["content"] != framework.content:
        framework.version += 1

    for field, value in update_data.items():
        setattr(framework, field, value)

    framework.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(framework)
    return framework


# =============================================================================
# RAAS-COMP-063: Elicitation Session Management
# =============================================================================


def create_elicitation_session(
    db: Session,
    data: ElicitationSessionCreate,
    created_by: Optional[UUID] = None,
) -> ElicitationSession:
    """Create a new elicitation session."""
    session = ElicitationSession(
        organization_id=data.organization_id,
        project_id=data.project_id,
        target_artifact_type=data.target_artifact_type,
        target_artifact_id=data.target_artifact_id,
        assignee_id=data.assignee_id,
        clarification_task_id=data.clarification_task_id,
        expires_at=data.expires_at,
        created_by=created_by,
        conversation_history=[],
        identified_gaps=[],
        progress={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_elicitation_session(
    db: Session,
    session_id: str,
) -> Optional[ElicitationSession]:
    """Get an elicitation session by UUID or human-readable ID (e.g., ELIC-001)."""
    # Try UUID first
    try:
        uuid_id = UUID(session_id)
        return db.query(ElicitationSession).filter(ElicitationSession.id == uuid_id).first()
    except (ValueError, AttributeError):
        pass

    # Try human-readable ID (case-insensitive)
    return db.query(ElicitationSession).filter(
        ElicitationSession.human_readable_id == session_id.upper()
    ).first()


# Aliases for backwards compatibility
get_elicitation_session_by_human_id = get_elicitation_session
get_elicitation_session_by_any_id = get_elicitation_session


def list_elicitation_sessions(
    db: Session,
    organization_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    assignee_id: Optional[UUID] = None,
    status: Optional[str] = None,
    target_artifact_type: Optional[str] = None,
    clarification_task_id: Optional[UUID] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[List[ElicitationSession], int]:
    """List elicitation sessions with filtering."""
    query = db.query(ElicitationSession)

    if organization_id:
        query = query.filter(ElicitationSession.organization_id == organization_id)
    if project_id:
        query = query.filter(ElicitationSession.project_id == project_id)
    if assignee_id:
        query = query.filter(ElicitationSession.assignee_id == assignee_id)
    if status:
        status_value = status.lower() if isinstance(status, str) else status
        query = query.filter(ElicitationSession.status == ElicitationSessionStatus(status_value))
    if target_artifact_type:
        query = query.filter(ElicitationSession.target_artifact_type == target_artifact_type)
    if clarification_task_id:
        query = query.filter(ElicitationSession.clarification_task_id == clarification_task_id)

    query = query.order_by(
        ElicitationSession.last_activity_at.desc()
    )

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def get_active_session_for_clarification_task(
    db: Session,
    clarification_task_id: UUID,
) -> Optional[ElicitationSession]:
    """Get active elicitation session for a clarification task."""
    return db.query(ElicitationSession).filter(
        and_(
            ElicitationSession.clarification_task_id == clarification_task_id,
            ElicitationSession.status.in_([
                ElicitationSessionStatus.ACTIVE,
                ElicitationSessionStatus.PAUSED,
            ])
        )
    ).first()


def update_elicitation_session(
    db: Session,
    session_id: str,
    data: ElicitationSessionUpdate,
) -> Optional[ElicitationSession]:
    """Update an elicitation session. Accepts UUID or human-readable ID (e.g., ELIC-001)."""
    session = get_elicitation_session(db, session_id)
    if not session:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status" and value:
            status_value = value.lower() if isinstance(value, str) else value
            value = ElicitationSessionStatus(status_value)
            # Handle status transitions
            if value == ElicitationSessionStatus.COMPLETED:
                session.completed_at = datetime.now(timezone.utc)
        setattr(session, field, value)

    session.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


def add_message_to_session(
    db: Session,
    session_id: str,
    data: ElicitationSessionAddMessage,
) -> Optional[ElicitationSession]:
    """Add a message to the conversation history. Accepts UUID or human-readable ID (e.g., ELIC-001)."""
    session = get_elicitation_session(db, session_id)
    if not session:
        return None

    message = {
        "role": data.role,
        "content": data.content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if data.metadata:
        message["metadata"] = data.metadata

    # Append to conversation history
    history = list(session.conversation_history) if session.conversation_history else []
    history.append(message)
    session.conversation_history = history
    session.last_activity_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(session)
    return session


def update_session_draft(
    db: Session,
    session_id: UUID,
    partial_draft: dict,
) -> Optional[ElicitationSession]:
    """Update the partial draft in a session."""
    session = get_elicitation_session(db, session_id)
    if not session:
        return None

    session.partial_draft = partial_draft
    session.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


def add_gap_to_session(
    db: Session,
    session_id: UUID,
    gap: dict,
) -> Optional[ElicitationSession]:
    """Add an identified gap to the session."""
    session = get_elicitation_session(db, session_id)
    if not session:
        return None

    gaps = list(session.identified_gaps) if session.identified_gaps else []
    gap["identified_at"] = datetime.now(timezone.utc).isoformat()
    gaps.append(gap)
    session.identified_gaps = gaps
    session.last_activity_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(session)
    return session


def update_session_progress(
    db: Session,
    session_id: UUID,
    progress: dict,
) -> Optional[ElicitationSession]:
    """Update the progress markers in a session."""
    session = get_elicitation_session(db, session_id)
    if not session:
        return None

    # Merge with existing progress
    current_progress = dict(session.progress) if session.progress else {}
    current_progress.update(progress)
    session.progress = current_progress
    session.last_activity_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(session)
    return session


def complete_elicitation_session(
    db: Session,
    session_id: str,
    final_artifact_id: Optional[UUID] = None,
) -> Optional[ElicitationSession]:
    """Mark an elicitation session as completed. Accepts UUID or human-readable ID (e.g., ELIC-001)."""
    session = get_elicitation_session(db, session_id)
    if not session:
        return None

    session.status = ElicitationSessionStatus.COMPLETED
    session.completed_at = datetime.now(timezone.utc)
    session.last_activity_at = datetime.now(timezone.utc)

    if final_artifact_id:
        session.target_artifact_id = final_artifact_id

    db.commit()
    db.refresh(session)
    return session


def expire_stale_sessions(
    db: Session,
) -> int:
    """Mark expired sessions as expired. Returns count of expired sessions."""
    now = datetime.now(timezone.utc)
    result = db.query(ElicitationSession).filter(
        and_(
            ElicitationSession.expires_at.isnot(None),
            ElicitationSession.expires_at < now,
            ElicitationSession.status.in_([
                ElicitationSessionStatus.ACTIVE,
                ElicitationSessionStatus.PAUSED,
            ])
        )
    ).update(
        {
            ElicitationSession.status: ElicitationSessionStatus.EXPIRED,
            ElicitationSession.last_activity_at: now,
        },
        synchronize_session=False,
    )
    db.commit()
    return result


# =============================================================================
# RAAS-COMP-064: Gap Analyzer (Analysis Functions)
# =============================================================================


# Default vagueness patterns for detecting ambiguous language
DEFAULT_VAGUENESS_PATTERNS = [
    {"pattern": r"\bfast\b", "issue": "Undefined speed - specify metrics (ms, requests/sec)"},
    {"pattern": r"\bslow\b", "issue": "Undefined speed - specify acceptable latency"},
    {"pattern": r"\beasy\b", "issue": "Subjective term - define concrete usability criteria"},
    {"pattern": r"\bsimple\b", "issue": "Subjective term - define what simplicity means"},
    {"pattern": r"\bflexible\b", "issue": "Undefined flexibility - specify what must be configurable"},
    {"pattern": r"\bscalable\b", "issue": "Undefined scalability - specify load targets"},
    {"pattern": r"\befficient\b", "issue": "Undefined efficiency - specify resource constraints"},
    {"pattern": r"\buser-friendly\b", "issue": "Subjective term - define UX requirements"},
    {"pattern": r"\bretc\.?\b", "issue": "Incomplete list - enumerate all items"},
    {"pattern": r"\band so on\b", "issue": "Incomplete list - enumerate all items"},
    {"pattern": r"\bsome\b", "issue": "Imprecise quantity - specify exact count or range"},
    {"pattern": r"\bmany\b", "issue": "Imprecise quantity - specify exact count or range"},
    {"pattern": r"\bfew\b", "issue": "Imprecise quantity - specify exact count or range"},
    {"pattern": r"\bvarious\b", "issue": "Imprecise - enumerate the specific items"},
    {"pattern": r"\bappropriate\b", "issue": "Subjective term - define what is appropriate"},
    {"pattern": r"\breasonable\b", "issue": "Subjective term - define acceptable thresholds"},
    {"pattern": r"\bas needed\b", "issue": "Undefined trigger - specify when/what conditions"},
    {"pattern": r"\bif possible\b", "issue": "Ambiguous requirement - make mandatory or remove"},
    {"pattern": r"\bshould\b", "issue": "Weak requirement - use 'must' for mandatory, remove for optional"},
    {"pattern": r"\bmight\b", "issue": "Uncertain requirement - clarify if required"},
    {"pattern": r"\bcould\b", "issue": "Uncertain requirement - clarify if required"},
    {"pattern": r"\bTBD\b", "issue": "Placeholder - needs resolution"},
    {"pattern": r"\bTODO\b", "issue": "Placeholder - needs resolution"},
]

# Default completeness criteria for different requirement types
DEFAULT_COMPLETENESS_CRITERIA = {
    "epic": {
        "required_sections": ["Vision", "Success Criteria", "Scope Boundaries"],
        "recommended_sections": ["Business Dependencies", "Data and Privacy"],
    },
    "component": {
        "required_sections": ["Purpose", "Capabilities", "Integrations"],
        "recommended_sections": ["Success Criteria", "Scope Boundaries", "Data and Privacy"],
    },
    "feature": {
        "required_sections": ["Purpose", "Acceptance Criteria"],
        "recommended_sections": ["Dependencies", "Technical Notes"],
    },
    "requirement": {
        "required_sections": ["Purpose", "Acceptance Criteria"],
        "recommended_sections": ["Dependencies"],
    },
    "guardrail": {
        "required_sections": ["Purpose", "Compliance Criteria", "Reference Patterns"],
        "recommended_sections": ["Scope"],
    },
}


def analyze_requirement_completeness(
    db: Session,
    requirement_id: UUID,
    framework: Optional[QuestionFramework] = None,
) -> tuple[float, List[GapFinding]]:
    """
    Analyze a requirement for completeness and vague language.
    Returns (completeness_score, findings).
    """
    import re

    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if not requirement:
        return 0.0, []

    findings = []
    content = requirement.content or ""
    req_type = requirement.type

    # Get completeness criteria
    if framework and framework.content.get("completeness_criteria"):
        criteria = framework.content["completeness_criteria"]
    else:
        criteria = DEFAULT_COMPLETENESS_CRITERIA.get(req_type, {})

    required_sections = criteria.get("required_sections", [])
    recommended_sections = criteria.get("recommended_sections", [])

    # Check for required sections
    sections_found = 0
    for section in required_sections:
        # Look for markdown headers with section name
        pattern = rf"^#+\s*{re.escape(section)}"
        if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
            findings.append(GapFinding(
                section=section,
                issue_type="missing_section",
                severity="high",
                description=f"Required section '{section}' is missing",
                suggestion=f"Add a '{section}' section to this {req_type}",
            ))
        else:
            sections_found += 1

    # Check for recommended sections
    for section in recommended_sections:
        pattern = rf"^#+\s*{re.escape(section)}"
        if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
            findings.append(GapFinding(
                section=section,
                issue_type="missing_section",
                severity="low",
                description=f"Recommended section '{section}' is missing",
                suggestion=f"Consider adding a '{section}' section",
            ))

    # Get vagueness patterns
    if framework and framework.content.get("vagueness_patterns"):
        vagueness_patterns = framework.content["vagueness_patterns"]
    else:
        vagueness_patterns = DEFAULT_VAGUENESS_PATTERNS

    # Check for vague language
    for pattern_def in vagueness_patterns:
        pattern = pattern_def.get("pattern", "")
        issue = pattern_def.get("issue", "Vague language detected")

        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        for match in matches:
            # Find which section this is in
            section = "Content"
            lines_before = content[:match.start()].split("\n")
            for line in reversed(lines_before):
                if line.startswith("#"):
                    section = line.lstrip("#").strip()
                    break

            findings.append(GapFinding(
                section=section,
                issue_type="vague_language",
                severity="medium",
                description=issue,
                evidence=match.group(),
                suggestion=f"Replace '{match.group()}' with specific, measurable criteria",
            ))

    # Calculate completeness score
    total_required = len(required_sections)
    if total_required > 0:
        base_score = sections_found / total_required
    else:
        base_score = 1.0

    # Penalize for vague language
    vague_count = len([f for f in findings if f.issue_type == "vague_language"])
    vague_penalty = min(0.3, vague_count * 0.05)  # Max 30% penalty

    completeness_score = max(0.0, base_score - vague_penalty)

    return completeness_score, findings


def find_contradictions_in_hierarchy(
    db: Session,
    parent_id: UUID,
) -> List[dict]:
    """
    Find potential contradictions between requirements in a hierarchy.
    This is a basic implementation that looks for conflicting keywords.
    """
    # Get all requirements under the parent
    requirements = db.query(Requirement).filter(
        Requirement.parent_id == parent_id
    ).all()

    contradictions = []

    # Simple keyword-based contradiction detection
    # Real implementation would use more sophisticated NLP
    contradiction_pairs = [
        ("must", "must not"),
        ("required", "optional"),
        ("always", "never"),
        ("synchronous", "asynchronous"),
        ("real-time", "batch"),
        ("public", "private"),
        ("internal", "external"),
    ]

    for i, req_a in enumerate(requirements):
        content_a = (req_a.content or "").lower()
        for req_b in requirements[i + 1:]:
            content_b = (req_b.content or "").lower()

            for term_a, term_b in contradiction_pairs:
                if term_a in content_a and term_b in content_b:
                    contradictions.append({
                        "requirement_a_id": req_a.id,
                        "requirement_a_title": req_a.title,
                        "requirement_b_id": req_b.id,
                        "requirement_b_title": req_b.title,
                        "contradiction_type": "potential_conflict",
                        "description": f"'{term_a}' in one requirement vs '{term_b}' in another",
                        "evidence_a": term_a,
                        "evidence_b": term_b,
                        "severity": "medium",
                    })
                elif term_b in content_a and term_a in content_b:
                    contradictions.append({
                        "requirement_a_id": req_a.id,
                        "requirement_a_title": req_a.title,
                        "requirement_b_id": req_b.id,
                        "requirement_b_title": req_b.title,
                        "contradiction_type": "potential_conflict",
                        "description": f"'{term_b}' in one requirement vs '{term_a}' in another",
                        "evidence_a": term_b,
                        "evidence_b": term_a,
                        "severity": "medium",
                    })

    return contradictions
