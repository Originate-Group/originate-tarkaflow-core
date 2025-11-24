"""Common MCP tool handlers shared between stdio and HTTP transports.

This module provides handler logic that can be used by both:
- src/raas_mcp/server.py (stdio transport for local development)
- raas-team/src/api/routers/mcp_http.py (HTTP transport with OAuth for production)

All handlers follow a consistent pattern:
- Accept: arguments dict, httpx.AsyncClient, and optional current_scope
- Return: tuple of (list[TextContent], Optional[dict]) where second element is updated scope
- Use formatters from formatters module for consistent output
- Log all operations for debugging

Session state management (scope) is handled by the caller (transport-specific).
"""
from typing import Optional, Any
import logging

import httpx
from mcp.types import TextContent

from . import formatters

logger = logging.getLogger("raas-mcp.handlers")


# ============================================================================
# Organization Handlers
# ============================================================================

async def handle_list_organizations(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List organizations with pagination and filtering.

    COMMON PATTERNS:
    • Browse → Details → Update: list_organizations() → get_organization() → update_organization()
    • Find by name: list_organizations(search="foo")
    • Get first page: list_organizations(page=1, page_size=50)

    RETURNS (paginated):
    • items: List of organizations with id, name, slug, created_at
    • total: Total count across all pages
    • page: Current page number
    • total_pages: Total number of pages
    """
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/organizations/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {result['total']} organizations")

    items_text = "\n\n".join([formatters.format_organization(item) for item in result['items']])
    summary = f"Found {result['total']} organizations (page {result['page']} of {result['total_pages']})\n\n{items_text}"

    return [TextContent(type="text", text=summary)], current_scope


async def handle_get_organization(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get detailed organization information.

    Returns complete organization details including settings.
    Errors: 404 (not found), 403 (not a member)
    """
    org_id = arguments["organization_id"]
    response = await client.get(f"/organizations/{org_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved organization {org_id}: {result['name']}")

    return [TextContent(type="text", text=formatters.format_organization(result))], current_scope


async def handle_create_organization(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new organization.

    Organization names should be clear and descriptive (e.g., 'Acme Corporation', 'Engineering Team').
    Slug must be unique, URL-friendly (lowercase, alphanumeric, hyphens).
    """
    response = await client.post("/organizations/", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully created organization: {result['name']} (ID: {result['id']})")

    text = (f"Created organization: {result['name']}\n"
            f"ID: {result['id']}\n"
            f"Slug: {result['slug']}\n\n"
            f"Full details:\n{formatters.format_organization(result)}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_update_organization(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update an organization.

    Only organization admins can update organization details.
    """
    org_id = arguments.pop("organization_id")
    response = await client.put(f"/organizations/{org_id}", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated organization {org_id}: {result['name']}")

    text = f"Updated organization: {result['name']}\n\n{formatters.format_organization(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_delete_organization(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Delete an organization and all its data (cascading delete).

    Only organization owners can delete an organization. Use with caution!
    """
    org_id = arguments["organization_id"]
    response = await client.delete(f"/organizations/{org_id}")
    response.raise_for_status()
    logger.info(f"Successfully deleted organization {org_id}")

    return [TextContent(type="text", text=f"Successfully deleted organization {org_id}")], current_scope


# ============================================================================
# Organization Member Handlers
# ============================================================================

async def handle_list_organization_members(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List all members of an organization with their roles."""
    org_id = arguments["organization_id"]
    response = await client.get(f"/organizations/{org_id}/members")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {len(result)} members for organization {org_id}")

    if not result:
        return [TextContent(type="text", text="No members found for this organization.")], current_scope

    members_text = "\n".join([formatters.format_organization_member(item) for item in result])
    return [TextContent(type="text", text=f"Organization Members:\n\n{members_text}")], current_scope


async def handle_add_organization_member(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Add a user to an organization with a specific role.

    Only organization admins and owners can add members.
    """
    org_id = arguments["organization_id"]
    response = await client.post(f"/organizations/{org_id}/members", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully added user {arguments['user_id']} to organization {org_id}")

    text = f"Added user {result['user_id']} to organization with role: {result['role']}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_update_organization_member(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update an organization member's role.

    Only organization admins and owners can update member roles.
    """
    org_id = arguments["organization_id"]
    user_id = arguments["user_id"]
    role = arguments["role"]
    response = await client.put(f"/organizations/{org_id}/members/{user_id}", json={"role": role})
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated user {user_id} role in organization {org_id}")

    text = f"Updated user {result['user_id']} role to: {result['role']}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_remove_organization_member(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Remove a user from an organization.

    Only organization admins and owners can remove members.
    """
    org_id = arguments["organization_id"]
    user_id = arguments["user_id"]
    response = await client.delete(f"/organizations/{org_id}/members/{user_id}")
    response.raise_for_status()
    logger.info(f"Successfully removed user {user_id} from organization {org_id}")

    return [TextContent(type="text", text=f"Removed user {user_id} from organization")], current_scope


# ============================================================================
# Project Handlers
# ============================================================================

async def handle_list_projects(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List projects with pagination (filtered by visibility and membership).

    COMMON PATTERN: list_projects(organization_id=...) → get project → list_requirements(project_id=...)
    IMPORTANT: Always use project_id when querying requirements to avoid mixing data from multiple projects.
    """
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/projects/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {result['total']} projects")

    items_text = "\n\n".join([formatters.format_project(item) for item in result['items']])
    summary = f"Found {result['total']} projects (page {result['page']} of {result['total_pages']})\n\n{items_text}"

    return [TextContent(type="text", text=summary)], current_scope


async def handle_get_project(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get detailed project information.

    Use project_id with list_requirements(project_id=...) to scope requirements correctly.
    Errors: 404 (not found), 403 (no access).
    """
    project_id = arguments["project_id"]
    response = await client.get(f"/projects/{project_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved project {project_id}: {result['name']}")

    return [TextContent(type="text", text=formatters.format_project(result))], current_scope


async def handle_create_project(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new project within an organization.

    Project names should be outcome-focused (e.g., 'Customer Self-Service Portal')
    rather than implementation-focused (e.g., 'React Frontend Rewrite').
    """
    response = await client.post("/projects/", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully created project: {result['name']} (ID: {result['id']})")

    text = (f"Created project: {result['name']} ({result['slug']})\n"
            f"ID: {result['id']}\n"
            f"Status: {result['status']}\n\n"
            f"Full details:\n{formatters.format_project(result)}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_update_project(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update a project.

    Only project admins and organization admins can update projects.
    """
    project_id = arguments.pop("project_id")
    response = await client.put(f"/projects/{project_id}", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated project {project_id}: {result['name']}")

    text = f"Updated project: {result['name']}\n\n{formatters.format_project(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_delete_project(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Delete a project and all its requirements (cascading delete).

    Only project admins and organization owners can delete projects. Use with caution!
    """
    project_id = arguments["project_id"]
    response = await client.delete(f"/projects/{project_id}")
    response.raise_for_status()
    logger.info(f"Successfully deleted project {project_id}")

    return [TextContent(type="text", text=f"Successfully deleted project {project_id}")], current_scope


# ============================================================================
# Project Member Handlers
# ============================================================================

async def handle_list_project_members(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List all members of a project with their roles."""
    project_id = arguments["project_id"]
    response = await client.get(f"/projects/{project_id}/members")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {len(result)} members for project {project_id}")

    if not result:
        return [TextContent(type="text", text="No members found for this project.")], current_scope

    members_text = "\n".join([formatters.format_project_member(item) for item in result])
    return [TextContent(type="text", text=f"Project Members:\n\n{members_text}")], current_scope


async def handle_add_project_member(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Add a user to a project with a specific role.

    Only project admins and organization admins can add members.
    """
    project_id = arguments["project_id"]
    response = await client.post(f"/projects/{project_id}/members", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully added user {arguments['user_id']} to project {project_id}")

    text = f"Added user {result['user_id']} to project with role: {result['role']}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_update_project_member(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update a project member's role.

    Only project admins and organization admins can update member roles.
    """
    project_id = arguments["project_id"]
    user_id = arguments["user_id"]
    role = arguments["role"]
    response = await client.put(f"/projects/{project_id}/members/{user_id}", json={"role": role})
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated user {user_id} role in project {project_id}")

    text = f"Updated user {result['user_id']} role to: {result['role']}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_remove_project_member(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Remove a user from a project.

    Only project admins and organization admins can remove members.
    """
    project_id = arguments["project_id"]
    user_id = arguments["user_id"]
    response = await client.delete(f"/projects/{project_id}/members/{user_id}")
    response.raise_for_status()
    logger.info(f"Successfully removed user {user_id} from project {project_id}")

    return [TextContent(type="text", text=f"Removed user {user_id} from project")], current_scope


# ============================================================================
# Project Scope Handlers
# ============================================================================

async def handle_select_project(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle select_project tool call.

    Args:
        arguments: Tool arguments containing project_id
        client: HTTP client configured with authentication
        current_scope: Current project scope (ignored for this operation)

    Returns:
        Tuple of (response content, updated project scope)
    """
    project_id = arguments["project_id"]

    # Validate project exists and user has access
    response = await client.get(f"/projects/{project_id}")
    response.raise_for_status()
    result = response.json()

    # Create new project scope
    new_scope = {
        "project_id": result["id"],
        "name": result["name"],
        "slug": result["slug"],
        "organization_id": result["organization_id"]
    }

    logger.info(f"Set project scope to: {result['name']} ({result['slug']})")

    content = [TextContent(
        type="text",
        text=f"✅ Project scope set successfully!\n\n"
             f"Active Project: {result['name']} ({result['slug']})\n"
             f"Project ID: {result['id']}\n"
             f"Organization ID: {result['organization_id']}\n\n"
             f"All requirement tools will now default to this project unless you provide an explicit project_id parameter."
    )]

    return content, new_scope


async def handle_get_project_scope(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle get_project_scope tool call.

    Args:
        arguments: Tool arguments (empty for this tool)
        client: HTTP client (not used for this operation)
        current_scope: Current project scope to query

    Returns:
        Tuple of (response content, unchanged project scope)
    """
    if current_scope is None:
        logger.info("No project scope is currently set")
        content = [TextContent(
            type="text",
            text="No project scope is currently set.\n\n"
                 "Use select_project(project_id='...') to set a default project context, or provide explicit project_id parameters to requirement tools."
        )]
    else:
        logger.info(f"Current project scope: {current_scope['name']} ({current_scope['slug']})")
        content = [TextContent(
            type="text",
            text=f"📍 Current Project Scope:\n\n"
                 f"Project: {current_scope['name']} ({current_scope['slug']})\n"
                 f"Project ID: {current_scope['project_id']}\n"
                 f"Organization ID: {current_scope['organization_id']}\n\n"
                 f"All requirement tools are using this project as their default context."
        )]

    return content, current_scope


async def handle_clear_project_scope(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle clear_project_scope tool call.

    Args:
        arguments: Tool arguments (empty for this tool)
        client: HTTP client (not used for this operation)
        current_scope: Current project scope to clear

    Returns:
        Tuple of (response content, None for cleared scope)
    """
    if current_scope is None:
        logger.info("Cleared project scope (was already unset)")
        content = [TextContent(
            type="text",
            text="✅ Project scope cleared (no scope was set).\n\n"
                 "Requirement tools will now require explicit project_id parameters or operate globally."
        )]
    else:
        previous_scope = current_scope
        logger.info(f"Cleared project scope (was: {previous_scope['name']})")
        content = [TextContent(
            type="text",
            text=f"✅ Project scope cleared!\n\n"
                 f"Previous scope: {previous_scope['name']} ({previous_scope['slug']})\n\n"
                 f"Requirement tools will now require explicit project_id parameters or operate globally."
        )]

    return content, None


async def apply_project_scope_defaults(
    tool_name: str,
    arguments: dict,
    current_scope: Optional[dict] = None
) -> dict:
    """Apply project scope as default for tools that accept project_id.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments (may be modified)
        current_scope: Current project scope

    Returns:
        Modified arguments with project_id defaulted if applicable
    """
    # Tools that should use project scope as default
    scoped_tools = {
        "list_requirements",
        "create_requirement",  # For epics only
    }

    if tool_name not in scoped_tools:
        return arguments

    if current_scope is None:
        return arguments

    # For create_requirement, only apply scope to epics (other types inherit from parent)
    if tool_name == "create_requirement":
        if arguments.get("type") == "epic" and "project_id" not in arguments:
            arguments["project_id"] = current_scope["project_id"]
            logger.info(f"Using session project scope for epic: {current_scope['name']}")

    # For list_requirements, apply scope if project_id not explicitly provided
    elif tool_name == "list_requirements":
        if "project_id" not in arguments:
            arguments["project_id"] = current_scope["project_id"]
            logger.info(f"Using session project scope for listing: {current_scope['name']}")

    return arguments


# ============================================================================
# User Handlers
# ============================================================================

async def handle_list_users(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List all users with pagination.

    Use for finding user IDs when managing organization/project members.
    """
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/users/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {result['total']} users")

    if result['total'] == 0:
        return [TextContent(type="text", text="No users found.")], current_scope

    users_text = "\n\n".join([formatters.format_user(item) for item in result['items']])
    summary = f"Found {result['total']} users (page {result['page']} of {result['total_pages']})\n\n{users_text}"

    return [TextContent(type="text", text=summary)], current_scope


async def handle_search_users(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Search for users with optional filtering.

    Useful for finding user UUIDs before adding them to projects.
    Can filter by organization membership and search by email/name.
    """
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/users/search", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully searched users: found {result['total']} results")

    if result['total'] == 0:
        return [TextContent(type="text", text="No users found matching search criteria.")], current_scope

    users_text = "\n\n".join([formatters.format_user(item) for item in result['items']])
    summary = f"Found {result['total']} users (page {result['page']} of {result['total_pages']})\n\n{users_text}"

    return [TextContent(type="text", text=summary)], current_scope


async def handle_get_user(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a user by their UUID."""
    user_id = arguments["user_id"]
    response = await client.get(f"/users/{user_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved user {user_id}: {result['email']}")

    return [TextContent(type="text", text=formatters.format_user(result))], current_scope


async def handle_get_user_by_email(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a user by their email address.

    Useful for finding a user's UUID when you only know their email.
    Email matching is case-insensitive.
    """
    email = arguments["email"]
    response = await client.get(f"/users/by-email/{email}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully found user by email {email}: {result['id']}")

    return [TextContent(type="text", text=formatters.format_user(result))], current_scope


# ============================================================================
# Requirement Handlers
# ============================================================================

async def handle_get_requirement_template(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get the markdown template for creating a new requirement (REQUIRED before create_requirement).

    WHEN TO USE:
    • ALWAYS call this FIRST before create_requirement() to get proper format
    • Templates include YAML frontmatter structure + markdown body guidance
    • Each requirement type (epic/component/feature/requirement) has different template

    COMMON PATTERNS:
    • Create workflow: get_requirement_template(type='...') → fill in values → create_requirement(content=...)
    • Reference for updates: Use to understand required frontmatter fields
    """
    req_type = arguments["type"]
    response = await client.get(f"/requirements/templates/{req_type}")
    response.raise_for_status()
    result = response.json()
    template_content = result["template"]
    logger.info(f"Successfully retrieved template for {req_type}")

    text = (f"Template for '{req_type}' requirement:\n\n"
            f"```markdown\n{template_content}\n```\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Copy the template above\n"
            f"2. Replace placeholder values in the YAML frontmatter and markdown body\n"
            f"3. Maintain the exact structure (frontmatter + markdown body)\n"
            f"4. Pass the complete filled-in content to create_requirement() or update_requirement()")

    return [TextContent(type="text", text=text)], current_scope


async def handle_create_requirement(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new requirement using properly formatted markdown template (with YAML frontmatter).

    REQUIRED WORKFLOW:
    1. Call get_requirement_template(type='...') to get the template
    2. Fill in template with actual values (maintain markdown structure)
    3. Optionally add 'depends_on: [uuid1, uuid2]' in YAML frontmatter
    4. Pass complete markdown in create_requirement(content=...)

    HIERARCHY RULES:
    • Epics: Top-level (no parent needed)
    • Components: Must have parent_id pointing to an epic
    • Features: Must have parent_id pointing to a component
    • Requirements: Must have parent_id pointing to a feature
    """
    response = await client.post("/requirements/", json=arguments)
    response.raise_for_status()
    result = response.json()
    readable_id = result.get('human_readable_id', 'PENDING')
    logger.info(f"Successfully created {result['type']}: {result['title']} ([{readable_id}])")

    text = (f"✅ Requirement created successfully!\n\n"
            f"[{readable_id}] {result['title']}\n"
            f"UUID: {result['id']}\n"
            f"Type: {result['type']}\n"
            f"Status: {result['status']}\n\n"
            f"You can reference this requirement as either:\n"
            f"- Readable ID: {readable_id}\n"
            f"- UUID: {result['id']}\n\n"
            f"Full details:\n{formatters.format_requirement(result)}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_list_requirements(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List and filter requirements with pagination (lightweight, excludes full markdown content).

    COMMON PATTERNS:
    • Browse → Details → Update: list_requirements() → get_requirement() → update_requirement()
    • Find next work: list_requirements(ready_to_implement=true, status='approved')
    • Explore hierarchy: list_requirements(parent_id='epic-uuid') → get children
    • Search by tags: list_requirements(tags=['sprint-1', 'backend'])
    """
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/requirements/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {result['total']} requirements (page {result['page']}/{result['total_pages']})")

    items_text = "\n".join([formatters.format_requirement_summary(item) for item in result['items']])
    summary = f"Found {result['total']} requirements (page {result['page']}/{result['total_pages']})\n{items_text}"

    return [TextContent(type="text", text=summary)], current_scope


async def handle_get_requirement(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get complete requirement details including full markdown content (heavy operation).

    Accepts both UUID and human-readable ID (e.g., 'RAAS-FEAT-042', case-insensitive).

    COMMON PATTERNS:
    • Read before update: get_requirement() → extract 'content' field → modify → update_requirement(content=...)
    • Check dependencies: get_requirement() → inspect 'depends_on' array
    • Browse then details: list_requirements() finds IDs → get_requirement() fetches full content
    """
    req_id = arguments["requirement_id"]
    response = await client.get(f"/requirements/{req_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved requirement {req_id}: {result['title']}")

    return [TextContent(type="text", text=formatters.format_requirement(result))], current_scope


async def handle_update_requirement(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update an existing requirement using properly formatted markdown OR update specific fields directly.

    Accepts both UUID and human-readable ID.

    COMMON PATTERNS:
    • Full content update: get_requirement() → modify content field → update_requirement(content=...)
    • Add dependencies: update_requirement(requirement_id='...', depends_on=['uuid1', 'uuid2'])
    • Clear dependencies: update_requirement(requirement_id='...', depends_on=[])
    """
    req_id = arguments.pop("requirement_id")
    response = await client.patch(f"/requirements/{req_id}", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated requirement {req_id}: {result['title']}")

    text = f"Updated requirement: {result['title']}\n\n{formatters.format_requirement(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_delete_requirement(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Delete a requirement and ALL its children recursively (cascading delete, permanent).

    Accepts both UUID and human-readable ID.

    WARNING: This operation is PERMANENT and cascades to all descendants!
    """
    req_id = arguments["requirement_id"]
    response = await client.delete(f"/requirements/{req_id}")
    response.raise_for_status()
    logger.info(f"Successfully deleted requirement {req_id}")

    return [TextContent(type="text", text=f"Successfully deleted requirement {req_id}")], current_scope


async def handle_get_requirement_children(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get all direct children of a requirement (lightweight, excludes full markdown content).

    Accepts both UUID and human-readable ID (case-insensitive).

    COMMON PATTERNS:
    • Explore hierarchy: get_requirement_children(epic_id) → shows components
    • Navigate down: Get children → pick one → get_requirement_children(child_id) → deeper
    • Preview before delete: get_requirement_children() → see what will be cascade deleted
    """
    req_id = arguments["requirement_id"]
    response = await client.get(f"/requirements/{req_id}/children")
    response.raise_for_status()
    result = response.json()

    if not result:
        logger.info(f"No children found for requirement {req_id}")
        return [TextContent(type="text", text="No children found for this requirement.")], current_scope

    logger.info(f"Successfully retrieved {len(result)} children for requirement {req_id}")
    children_text = "\n".join([formatters.format_requirement_summary(item) for item in result])

    return [TextContent(type="text", text=f"Children ({len(result)}):\n{children_text}")], current_scope


async def handle_get_requirement_history(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """View complete change history for a requirement (audit trail).

    Accepts both UUID and human-readable ID.

    COMMON PATTERNS:
    • Audit trail: get_requirement_history() → see who changed what and when
    • Debug changes: Check history to understand recent modifications
    • Compliance: Retrieve full audit log for requirement
    """
    req_id = arguments["requirement_id"]
    limit = arguments.get("limit", 50)
    response = await client.get(f"/requirements/{req_id}/history", params={"limit": limit})
    response.raise_for_status()
    result = response.json()

    if not result:
        logger.info(f"No history found for requirement {req_id}")
        return [TextContent(type="text", text="No history found for this requirement.")], current_scope

    logger.info(f"Successfully retrieved {len(result)} history entries for requirement {req_id}")
    history_text = "\n".join([formatters.format_history(item) for item in result])

    return [TextContent(type="text", text=f"Change History:\n\n{history_text}")], current_scope


async def handle_transition_status(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Transition a requirement to a new lifecycle status (convenience tool).

    Accepts both UUID and human-readable ID.

    STATUS WORKFLOW (enforced state machine):
    • Forward: draft → review → approved → in_progress → implemented → validated → deployed
    • Can move backward 1+ steps (e.g., review → draft, approved → draft)
    • CANNOT skip steps (e.g., draft → approved is blocked, must go draft → review → approved)
    • deployed is terminal (cannot transition out, create new requirement instead)
    """
    req_id = arguments["requirement_id"]
    new_status = arguments["new_status"]
    response = await client.patch(f"/requirements/{req_id}", json={"status": new_status})
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully transitioned requirement {req_id} to status: {new_status}")

    text = f"Transitioned '{result['title']}' to status: {new_status}"
    return [TextContent(type="text", text=text)], current_scope


# ============================================================================
# Guardrail Handlers
# ============================================================================

async def handle_get_guardrail_template(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get the markdown template for creating a new guardrail.

    WHEN TO USE:
    • ALWAYS call this FIRST before create_guardrail() to get proper format
    • Template includes YAML frontmatter structure + markdown body guidance
    """
    response = await client.get("/guardrails/template")
    response.raise_for_status()
    result = response.json()
    logger.info("Successfully retrieved guardrail template")

    return [TextContent(type="text", text=result["template"])], current_scope


async def handle_create_guardrail(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new organizational guardrail with structured markdown content (with YAML frontmatter).

    REQUIRED WORKFLOW:
    1. Call get_guardrail_template() to get the template
    2. Fill in template with actual values (maintain markdown structure)
    3. Pass complete markdown in create_guardrail(content=...)

    GUARDRAILS ARE:
    • Organization-scoped (not project-scoped)
    • Standards that guide requirement authoring across all projects
    • Categorized (MVP: security, architecture)
    • Have enforcement levels (advisory, recommended, mandatory)
    • Specify which requirement types they apply to
    """
    org_id = arguments["organization_id"]
    content = arguments["content"]
    response = await client.post("/guardrails/", json={
        "organization_id": org_id,
        "content": content
    })
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully created guardrail {result['human_readable_id']}: {result['title']}")

    text = (f"Created guardrail: {result['title']}\n"
            f"ID: {result['human_readable_id']}\n"
            f"Category: {result['category']}\n"
            f"Enforcement Level: {result['enforcement_level']}\n"
            f"Status: {result['status']}\n"
            f"Applies To: {', '.join(result['applies_to'])}\n\n"
            f"UUID: {result['id']}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_get_guardrail(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get complete guardrail details including full markdown content.

    Accepts both UUID and human-readable ID (e.g., 'GUARD-SEC-001', case-insensitive).
    """
    guardrail_id = arguments["guardrail_id"]
    response = await client.get(f"/guardrails/{guardrail_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved guardrail {guardrail_id}")

    text = (f"Guardrail: {result['title']} ({result['human_readable_id']})\n"
            f"Category: {result['category']}\n"
            f"Enforcement Level: {result['enforcement_level']}\n"
            f"Status: {result['status']}\n"
            f"Applies To: {', '.join(result['applies_to'])}\n"
            f"Created: {result['created_at']}\n"
            f"Updated: {result['updated_at']}\n\n"
            f"Content:\n{result['content']}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_update_guardrail(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update an existing guardrail with new markdown content.

    WORKFLOW:
    1. Call get_guardrail() to retrieve current content
    2. Modify the markdown content (update title, status, body, etc.)
    3. Pass complete updated markdown in update_guardrail(content=...)
    """
    guardrail_id = arguments["guardrail_id"]
    content = arguments["content"]
    response = await client.patch(f"/guardrails/{guardrail_id}", json={"content": content})
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated guardrail {result['human_readable_id']}: {result['title']}")

    text = (f"Updated guardrail: {result['title']}\n"
            f"ID: {result['human_readable_id']}\n"
            f"Category: {result['category']}\n"
            f"Enforcement Level: {result['enforcement_level']}\n"
            f"Status: {result['status']}\n"
            f"Applies To: {', '.join(result['applies_to'])}\n"
            f"Updated: {result['updated_at']}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_list_guardrails(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List and filter organizational guardrails with pagination and search.

    FILTERS:
    • organization_id: Filter by organization UUID
    • category: Filter by category (security, architecture)
    • enforcement_level: Filter by level (advisory, recommended, mandatory)
    • applies_to: Filter by requirement type (epic, component, feature, requirement)
    • status: Filter by status (defaults to 'active' only, use 'all' for all statuses)
    • search: Keyword search in title and content

    DEFAULT BEHAVIOR:
    • Returns only active guardrails unless status filter specified
    • Multiple filters combine with AND logic
    • Results ordered by creation date (newest first)
    """
    # Build query parameters
    params = {}
    for key in ["organization_id", "category", "enforcement_level", "applies_to", "status", "search", "page", "page_size"]:
        if key in arguments and arguments[key] is not None:
            # Handle 'all' status - convert to None to show all statuses
            if key == "status" and arguments[key] == "all":
                params[key] = None
            else:
                params[key] = arguments[key]

    response = await client.get("/guardrails/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed guardrails: {result['total']} total, page {result['page']}")

    if result['total'] == 0:
        return [TextContent(type="text", text="No guardrails found matching the filters.")], current_scope

    items_text = "\n\n".join([
        f"{item['human_readable_id']}: {item['title']}\n"
        f"  Category: {item['category']}\n"
        f"  Enforcement: {item['enforcement_level']}\n"
        f"  Status: {item['status']}\n"
        f"  Applies To: {', '.join(item['applies_to'])}\n"
        f"  Description: {item['description'] or '(none)'}"
        for item in result['items']
    ])

    summary = (
        f"Found {result['total']} guardrails (page {result['page']} of {result['total_pages']})\n\n"
        f"{items_text}"
    )

    return [TextContent(type="text", text=summary)], current_scope
