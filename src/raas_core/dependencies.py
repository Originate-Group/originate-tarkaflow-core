"""Dependency validation and query logic for requirement dependencies."""
import logging
from typing import Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_

from . import models

logger = logging.getLogger("raas-api.dependencies")


class CircularDependencyError(ValueError):
    """Raised when a circular dependency is detected."""
    pass


class PriorityInversionWarning(Warning):
    """Warning for priority inversions in dependencies."""
    pass


def extract_priority_from_tags(tags: list[str]) -> Optional[int]:
    """
    Extract priority from tags list (e.g., ['p1', 'backend'] -> 1).

    Args:
        tags: List of tags

    Returns:
        Priority as integer (1-3) or None if no priority tag found
    """
    for tag in tags:
        tag_lower = tag.lower()
        if tag_lower in ['p1', 'priority1']:
            return 1
        elif tag_lower in ['p2', 'priority2']:
            return 2
        elif tag_lower in ['p3', 'priority3']:
            return 3
    return None


def detect_circular_dependency(
    db: Session,
    requirement_id: UUID,
    new_dependencies: list[UUID],
    visited: Optional[Set[UUID]] = None
) -> Optional[list[UUID]]:
    """
    Detect if adding dependencies would create a circular dependency.

    Uses depth-first search to detect cycles in the dependency graph.

    Args:
        db: Database session
        requirement_id: The requirement we're adding dependencies to
        new_dependencies: List of dependency IDs to add
        visited: Set of already visited requirement IDs (for recursion)

    Returns:
        List representing the cycle path if found, None otherwise
    """
    if visited is None:
        visited = set()

    # Check if requirement_id is in new_dependencies (self-dependency)
    if requirement_id in new_dependencies:
        return [requirement_id, requirement_id]

    visited.add(requirement_id)

    # For each new dependency, check if it eventually depends on requirement_id
    for dep_id in new_dependencies:
        if dep_id in visited:
            # Found a cycle
            return [requirement_id, dep_id]

        # Get transitive dependencies of dep_id (start fresh, don't pass visited)
        transitive_deps = get_transitive_dependencies(db, dep_id, set())

        if requirement_id in transitive_deps:
            # Found a cycle
            return [requirement_id, dep_id, requirement_id]

    return None


def get_transitive_dependencies(
    db: Session,
    requirement_id: UUID,
    visited: Optional[Set[UUID]] = None,
    depth: int = 0,
    max_depth: int = 50
) -> Set[UUID]:
    """
    Get all transitive dependencies of a requirement (recursive).

    Args:
        db: Database session
        requirement_id: Starting requirement ID
        visited: Set of already visited IDs (prevents infinite loops)
        depth: Current recursion depth
        max_depth: Maximum recursion depth (default: 50)

    Returns:
        Set of all requirement IDs that this requirement depends on (directly or indirectly)
        NOTE: Does NOT include the starting requirement_id itself
    """
    if visited is None:
        visited = set()

    if depth >= max_depth:
        logger.warning(f"Maximum dependency depth ({max_depth}) reached for requirement {requirement_id}")
        return visited

    if requirement_id in visited:
        return visited

    visited.add(requirement_id)

    # Get direct dependencies from the junction table
    dependencies = (
        db.query(models.requirement_dependencies.c.depends_on_id)
        .filter(models.requirement_dependencies.c.requirement_id == requirement_id)
        .all()
    )

    # Recursively get transitive dependencies
    for (dep_id,) in dependencies:
        if dep_id not in visited:
            get_transitive_dependencies(db, dep_id, visited, depth + 1, max_depth)

    return visited


def check_priority_inversions(
    db: Session,
    requirement_id: UUID,
    dependency_ids: list[UUID]
) -> list[dict]:
    """
    Check for priority inversions where higher priority items depend on lower priority items.

    Args:
        db: Database session
        requirement_id: The requirement being updated
        dependency_ids: List of dependency IDs

    Returns:
        List of warnings (dicts with requirement_id, dep_id, req_priority, dep_priority)
    """
    warnings = []

    # Get the requirement's priority from tags
    requirement = db.query(models.Requirement).filter(models.Requirement.id == requirement_id).first()
    if not requirement:
        return warnings

    req_priority = extract_priority_from_tags(requirement.tags)
    if req_priority is None:
        # No priority tag, skip check
        return warnings

    # Check each dependency
    for dep_id in dependency_ids:
        dep = db.query(models.Requirement).filter(models.Requirement.id == dep_id).first()
        if not dep:
            continue

        dep_priority = extract_priority_from_tags(dep.tags)
        if dep_priority is None:
            # Dependency has no priority, skip
            continue

        # Priority inversion: lower number = higher priority
        # So P1 (1) depending on P3 (3) is an inversion
        if req_priority < dep_priority:
            warnings.append({
                'requirement_id': requirement_id,
                'requirement_priority': req_priority,
                'dependency_id': dep_id,
                'dependency_priority': dep_priority,
                'message': f"Priority inversion: P{req_priority} requirement depends on P{dep_priority} requirement"
            })

    return warnings


def validate_dependencies(
    db: Session,
    requirement_id: UUID,
    dependency_ids: list[UUID],
    project_id: UUID
) -> tuple[bool, Optional[str], list[dict]]:
    """
    Validate a list of dependencies for a requirement.

    Checks:
    1. All dependency IDs exist and are in the same project
    2. No self-dependencies
    3. No circular dependencies
    4. Priority inversions (warning only)

    Args:
        db: Database session
        requirement_id: The requirement being updated
        dependency_ids: List of dependency IDs to validate
        project_id: Project ID (dependencies must be in same project)

    Returns:
        Tuple of (is_valid, error_message, warnings)
        - is_valid: True if dependencies are valid, False otherwise
        - error_message: Error message if invalid, None otherwise
        - warnings: List of warning dicts (for priority inversions)
    """
    warnings = []

    # Check for self-dependencies
    if requirement_id in dependency_ids:
        return False, "Requirement cannot depend on itself", []

    # Validate all dependency IDs exist and are in same project
    for dep_id in dependency_ids:
        dep = db.query(models.Requirement).filter(models.Requirement.id == dep_id).first()
        if not dep:
            return False, f"Dependency {dep_id} not found", []
        if dep.project_id != project_id:
            return False, f"Dependency {dep_id} is in a different project", []

    # Check for circular dependencies
    cycle = detect_circular_dependency(db, requirement_id, dependency_ids)
    if cycle:
        cycle_str = " -> ".join(str(id) for id in cycle)
        return False, f"Circular dependency detected: {cycle_str}", []

    # Check for priority inversions (warning only, doesn't block)
    warnings = check_priority_inversions(db, requirement_id, dependency_ids)

    return True, None, warnings


def get_requirements_ready_to_implement(
    db: Session,
    project_id: UUID,
    organization_ids: list[UUID]
) -> list[models.Requirement]:
    """
    Get requirements that are ready to implement (all dependencies are code-complete).

    CR-004 Phase 4: "Code-complete" means deployed_version_id is set, indicating
    a version has been deployed to production. Requirements are specifications;
    implementation status is tracked on Work Items.

    Args:
        db: Database session
        project_id: Project ID to filter by
        organization_ids: Organization IDs for access control

    Returns:
        List of approved requirements with no unmet dependencies
    """
    from sqlalchemy import case

    # CR-009: Status lives on RequirementVersion. Join with resolved version to filter.
    # Subquery to get resolved version ID (deployed > latest approved > latest)
    resolved_version_subq = (
        db.query(models.RequirementVersion.id)
        .filter(models.RequirementVersion.requirement_id == models.Requirement.id)
        .order_by(
            case(
                (models.RequirementVersion.id == models.Requirement.deployed_version_id, 0),
                else_=1
            ),
            case(
                (models.RequirementVersion.status == models.LifecycleStatus.APPROVED, 0),
                else_=1
            ),
            models.RequirementVersion.version_number.desc()
        )
        .limit(1)
        .correlate(models.Requirement)
        .scalar_subquery()
    )

    # Get approved requirements (ready for implementation)
    query = (
        db.query(models.Requirement)
        .join(
            models.RequirementVersion,
            models.RequirementVersion.id == resolved_version_subq
        )
        .filter(
            models.Requirement.project_id == project_id,
            models.Requirement.organization_id.in_(organization_ids),
            models.RequirementVersion.status == models.LifecycleStatus.APPROVED,
            # Exclude requirements that already have a deployed version
            models.Requirement.deployed_version_id.is_(None)
        )
    )

    ready_requirements = []

    for req in query.all():
        # Get direct dependencies
        deps = (
            db.query(models.Requirement)
            .join(
                models.requirement_dependencies,
                models.Requirement.id == models.requirement_dependencies.c.depends_on_id
            )
            .filter(models.requirement_dependencies.c.requirement_id == req.id)
            .all()
        )

        # Check if all dependencies are code-complete (have deployed_version_id set)
        if not deps or all(dep.deployed_version_id is not None for dep in deps):
            ready_requirements.append(req)

    return ready_requirements


def get_requirements_blocked_by(
    db: Session,
    requirement_id: UUID
) -> list[models.Requirement]:
    """
    Get requirements that are blocked by (depend on) the specified requirement.

    Args:
        db: Database session
        requirement_id: Requirement ID to check

    Returns:
        List of requirements that depend on this requirement
    """
    return (
        db.query(models.Requirement)
        .join(
            models.requirement_dependencies,
            models.Requirement.id == models.requirement_dependencies.c.requirement_id
        )
        .filter(models.requirement_dependencies.c.depends_on_id == requirement_id)
        .all()
    )


def can_mark_as_deployed(
    db: Session,
    requirement_id: UUID
) -> tuple[bool, Optional[str]]:
    """
    Check if a requirement can be marked as deployed (deployed_version_id can be set).

    CR-004 Phase 4: Requirements no longer have a DEPLOYED status. Instead,
    deployment is tracked via deployed_version_id. A requirement can only be
    marked as deployed if all its dependencies already have deployed_version_id set.

    Args:
        db: Database session
        requirement_id: Requirement ID to check

    Returns:
        Tuple of (can_deploy, error_message)
        - can_deploy: True if all dependencies are deployed (have deployed_version_id)
        - error_message: Error message if cannot deploy, None otherwise
    """
    # Get direct dependencies
    deps = (
        db.query(models.Requirement)
        .join(
            models.requirement_dependencies,
            models.Requirement.id == models.requirement_dependencies.c.depends_on_id
        )
        .filter(models.requirement_dependencies.c.requirement_id == requirement_id)
        .all()
    )

    # Check if any dependencies don't have deployed_version_id set
    unmet_deps = [dep for dep in deps if dep.deployed_version_id is None]

    if unmet_deps:
        dep_list = ", ".join(
            f"{dep.human_readable_id or str(dep.id)} (not deployed)"
            for dep in unmet_deps
        )
        return False, f"Cannot mark as deployed: the following dependencies are not deployed: {dep_list}"

    return True, None


# Legacy alias for backwards compatibility
def can_transition_to_deployed(
    db: Session,
    requirement_id: UUID
) -> tuple[bool, Optional[str]]:
    """
    DEPRECATED: Use can_mark_as_deployed instead.

    CR-004 Phase 4 removed DEPLOYED from requirement statuses.
    This function now delegates to can_mark_as_deployed.
    """
    return can_mark_as_deployed(db, requirement_id)
