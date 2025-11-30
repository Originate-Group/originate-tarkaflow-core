"""Shared formatting functions for MCP responses.

This module provides consistent formatting for both stdio and HTTP MCP endpoints.
"""


def format_organization(org: dict) -> str:
    """Format an organization for display."""
    settings_info = f"\nSettings: {org['settings']}" if org.get('settings') else ""

    return f"""**{org['name']}**
ID: {org['id']}
Slug: {org['slug']}{settings_info}
Created: {org['created_at']}
Updated: {org['updated_at']}"""


def format_project(proj: dict) -> str:
    """Format a project for display."""
    desc_info = f"\nDescription: {proj['description']}" if proj.get('description') else ""
    tags_info = f"\nTags: {', '.join(proj['tags'])}" if proj.get('tags') else ""
    value_info = f"\nValue Statement: {proj['value_statement']}" if proj.get('value_statement') else ""
    type_info = f"\nProject Type: {proj['project_type']}" if proj.get('project_type') else ""

    return f"""**{proj['name']}** ({proj['slug']})
ID: {proj['id']}
Organization: {proj['organization_id']}
Status: {proj['status']}
Visibility: {proj['visibility']}{desc_info}{value_info}{type_info}{tags_info}
Created: {proj['created_at']}
Updated: {proj['updated_at']}"""


def format_organization_member(member: dict) -> str:
    """Format an organization member for display."""
    return f"- User {member['user_id']}: {member['role']} (joined: {member['joined_at']})"


def format_project_member(member: dict) -> str:
    """Format a project member for display."""
    return f"- User {member['user_id']}: {member['role']} (joined: {member['joined_at']})"


def format_user(user: dict) -> str:
    """Format a user for display."""
    name_info = f" ({user['full_name']})" if user.get('full_name') else ""
    return f"""**{user['email']}**{name_info}
ID: {user['id']}
Active: {user['is_active']}
Created: {user['created_at']}"""


def format_requirement(req: dict) -> str:
    """Format a requirement for display with full content and human-readable ID."""
    # Get human-readable ID (or fallback to NO-ID if missing)
    readable_id = req.get('human_readable_id', 'NO-ID')

    # Add emoji prefix based on type
    type_emoji = {
        'epic': '📚',
        'component': '🧩',
        'feature': '✨',
        'requirement': '📝'
    }.get(req['type'], '📄')

    parent_info = f"\nParent ID: {req['parent_id']}" if req['parent_id'] else ""
    tags_info = f"\nTags: {', '.join(req['tags'])}" if req['tags'] else ""

    # Format dependencies if present
    depends_on = req.get('depends_on', [])
    deps_info = ""
    if depends_on:
        dep_count = len(depends_on)
        # Show first 3 dependencies, then "and N more" if there are more
        if dep_count <= 3:
            deps_info = f"\nDepends on: {', '.join([str(d) for d in depends_on])}"
        else:
            first_three = ', '.join([str(d) for d in depends_on[:3]])
            deps_info = f"\nDepends on: {first_three} (and {dep_count - 3} more)"

    # Include computed metadata fields if available
    metadata_info = ""
    if 'content_length' in req:
        metadata_info += f"\nContent length: {req['content_length']} chars"
    if 'child_count' in req:
        metadata_info += f"\nChildren: {req['child_count']}"

    # Use full content if available, otherwise fall back to description
    # This ensures Desktop gets complete markdown for read → update workflows
    body = req.get('content') or req.get('description') or '(No content)'

    return f"""[{readable_id}] {type_emoji} **{req['title']}** ({req['type']})
UUID: {req['id']}{parent_info}
Status: {req['status']}{tags_info}{deps_info}{metadata_info}
Created: {req['created_at']}
Updated: {req['updated_at']}

{body}"""


def format_requirement_summary(req: dict) -> str:
    """Format a requirement as a compact one-liner for list views (token-efficient)."""
    readable_id = req.get('human_readable_id', 'NO-ID')
    status = req.get('status', 'unknown')
    title = req.get('title', '(untitled)')

    # BUG-019: Include version info to avoid N+1 queries
    version_number = req.get('version_number')
    total_versions = req.get('total_versions', 0)
    version_suffix = f" v{version_number}/{total_versions}" if version_number else ""

    # Show dependency count if present
    depends_on = req.get('depends_on', [])
    deps_suffix = f" (deps: {len(depends_on)})" if depends_on else ""

    return f"[{readable_id}] {status}: {title}{version_suffix}{deps_suffix}"


def format_history(entry: dict) -> str:
    """Format a history entry for display."""
    timestamp = entry['changed_at']
    change_type = entry['change_type']

    if entry['field_name']:
        return f"- [{timestamp}] {change_type}: {entry['field_name']} changed from '{entry['old_value']}' to '{entry['new_value']}'"
    else:
        return f"- [{timestamp}] {change_type}: {entry['new_value']}"


def format_work_item(wi: dict) -> str:
    """Format a work item for display with full details."""
    # Get human-readable ID
    readable_id = wi.get('human_readable_id', 'NO-ID')

    # Add emoji prefix based on type (CR-007: removed IR/task, added DEBT)
    type_emoji = {
        'cr': '📝',      # Change Request
        'bug': '🐛',     # Bug
        'debt': '🔧',    # Technical Debt
        'release': '📦', # Release
    }.get(wi.get('work_item_type', ''), '📋')

    # Basic info
    title = wi.get('title', '(untitled)')
    wi_type = wi.get('work_item_type', 'unknown')
    status = wi.get('status', 'unknown')
    priority = wi.get('priority', 'medium')

    # Optional fields
    desc_info = f"\n\n{wi['description']}" if wi.get('description') else ""
    assignee = wi.get('assignee_email') or wi.get('assignee_name')
    assignee_info = f"\nAssigned to: {assignee}" if assignee else ""
    tags_info = f"\nTags: {', '.join(wi['tags'])}" if wi.get('tags') else ""

    # Affects info
    affects_count = wi.get('affects_count', 0)
    affected_ids = wi.get('affected_requirement_ids', [])
    affects_info = ""
    if affects_count > 0:
        if len(affected_ids) <= 3:
            affects_info = f"\nAffects: {', '.join([str(a) for a in affected_ids])}"
        else:
            first_three = ', '.join([str(a) for a in affected_ids[:3]])
            affects_info = f"\nAffects: {first_three} (and {affects_count - 3} more)"

    # Implementation refs
    impl_refs = wi.get('implementation_refs') or {}
    refs_info = ""
    if impl_refs:
        refs_parts = []
        if impl_refs.get('github_issue_url'):
            refs_parts.append(f"Issue: {impl_refs['github_issue_url']}")
        if impl_refs.get('pr_urls'):
            refs_parts.append(f"PRs: {len(impl_refs['pr_urls'])}")
        if impl_refs.get('commit_shas'):
            refs_parts.append(f"Commits: {len(impl_refs['commit_shas'])}")
        if refs_parts:
            refs_info = f"\nGitHub: {', '.join(refs_parts)}"

    # Timestamps
    created = wi.get('created_at', 'unknown')
    updated = wi.get('updated_at', 'unknown')
    completed = wi.get('completed_at')
    cancelled = wi.get('cancelled_at')

    completion_info = ""
    if completed:
        completion_info = f"\nCompleted: {completed}"
    elif cancelled:
        completion_info = f"\nCancelled: {cancelled}"

    return f"""[{readable_id}] {type_emoji} **{title}** ({wi_type})
UUID: {wi['id']}
Status: {status} | Priority: {priority}{assignee_info}{tags_info}{affects_info}{refs_info}
Created: {created}
Updated: {updated}{completion_info}{desc_info}"""


def format_work_item_summary(wi: dict) -> str:
    """Format a work item as a compact one-liner for list views."""
    readable_id = wi.get('human_readable_id', 'NO-ID')
    status = wi.get('status', 'unknown')
    priority = wi.get('priority', 'medium')
    title = wi.get('title', '(untitled)')
    wi_type = wi.get('work_item_type', 'unknown')
    affects_count = wi.get('affects_count', 0)

    affects_suffix = f" (affects: {affects_count})" if affects_count > 0 else ""

    return f"[{readable_id}] {wi_type}/{status}/{priority}: {title}{affects_suffix}"


def format_work_item_history(entry: dict) -> str:
    """Format a work item history entry for display."""
    timestamp = entry.get('changed_at', 'unknown')
    change_type = entry.get('change_type', 'unknown')
    changed_by = entry.get('changed_by_email', 'unknown')

    if entry.get('field_name'):
        return f"- [{timestamp}] {change_type} by {changed_by}: {entry['field_name']} '{entry.get('old_value')}' -> '{entry.get('new_value')}'"
    else:
        return f"- [{timestamp}] {change_type} by {changed_by}"


def format_requirement_version(version: dict) -> str:
    """Format a requirement version for display (CR-002: RAAS-FEAT-097)."""
    version_num = version.get('version_number', '?')
    title = version.get('title', '(untitled)')
    content_hash = version.get('content_hash', '')[:12] + '...' if version.get('content_hash') else 'N/A'
    created_at = version.get('created_at', 'unknown')

    # Source work item if present
    source_wi = version.get('source_work_item_id')
    source_info = f"\nSource Work Item: {source_wi}" if source_wi else ""

    # Change reason if present
    reason = version.get('change_reason')
    reason_info = f"\nChange Reason: {reason}" if reason else ""

    return f"""**Version {version_num}**: {title}
Hash: {content_hash}
Created: {created_at}{source_info}{reason_info}"""


def format_requirement_version_summary(version: dict) -> str:
    """Format a requirement version as a compact one-liner."""
    version_num = version.get('version_number', '?')
    title = version.get('title', '(untitled)')
    created_at = version.get('created_at', 'unknown')[:10]  # Just date

    return f"v{version_num}: {title} ({created_at})"


def format_version_diff(diff: dict) -> str:
    """Format a version diff for display (CR-002: RAAS-FEAT-097)."""
    req_id = diff.get('requirement_id', 'unknown')
    from_v = diff.get('from_version', '?')
    to_v = diff.get('to_version', '?')
    from_title = diff.get('from_title', '(untitled)')
    to_title = diff.get('to_title', '(untitled)')

    title_change = ""
    if from_title != to_title:
        title_change = f"\n**Title changed**: '{from_title}' → '{to_title}'"

    return f"""**Diff: v{from_v} → v{to_v}**
Requirement: {req_id}{title_change}

--- FROM (v{from_v}) ---
{diff.get('from_content', '(no content)')}

--- TO (v{to_v}) ---
{diff.get('to_content', '(no content)')}"""
