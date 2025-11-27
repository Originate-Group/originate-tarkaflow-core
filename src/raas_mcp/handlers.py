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
from typing import Optional, Any, Tuple, List
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


# NOTE: handle_delete_organization removed from MCP - destructive operations require direct API access
# See RAAS-FEAT-079: MCP Destructive Operation Removal


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


# NOTE: handle_delete_organization_member removed from MCP - destructive operations require direct API access
# See RAAS-FEAT-079: MCP Destructive Operation Removal


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


# NOTE: handle_delete_project removed from MCP - destructive operations require direct API access
# See RAAS-FEAT-079: MCP Destructive Operation Removal


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


# NOTE: handle_delete_project_member removed from MCP - destructive operations require direct API access
# See RAAS-FEAT-079: MCP Destructive Operation Removal


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
# Persona Scope Handlers
# ============================================================================

# Valid personas for workflow authorization
VALID_PERSONAS = {
    "enterprise_architect",
    "product_owner",
    "scrum_master",
    "developer",
    "tester",
    "release_manager",
}


async def handle_select_persona(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle select_persona tool call.

    Args:
        arguments: Tool arguments containing persona
        client: HTTP client (not used for this operation)
        current_scope: Current project scope (passed through unchanged)

    Returns:
        Tuple of (response content, persona scope marker)
    """
    persona = arguments["persona"].lower()

    # Validate persona
    if persona not in VALID_PERSONAS:
        valid_list = ", ".join(sorted(VALID_PERSONAS))
        return [TextContent(
            type="text",
            text=f"Invalid persona: {persona}\n\nValid personas: {valid_list}"
        )], current_scope

    logger.info(f"Set persona to: {persona}")

    content = [TextContent(
        type="text",
        text=f"Persona set to: {persona}\n\n"
             f"All status transitions will now use this persona for authorization.\n"
             f"The persona is logged in the audit trail for compliance."
    )]

    # Return special marker dict to signal persona scope change
    return content, {"_persona": persona}


async def handle_get_persona(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle get_persona tool call.

    Note: This handler doesn't have direct access to _session_persona,
    so the server must pass it differently. For now, we return a message
    that the persona should be checked via server state.
    """
    # The actual persona value is managed by the server
    # This handler is called for informational purposes
    content = [TextContent(
        type="text",
        text="Use select_persona() to set a persona, or check the server logs for current session persona."
    )]
    return content, current_scope


async def handle_clear_persona(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle clear_persona tool call.

    Args:
        arguments: Tool arguments (empty for this tool)
        client: HTTP client (not used for this operation)
        current_scope: Current project scope (passed through unchanged)

    Returns:
        Tuple of (response content, persona scope marker with None)
    """
    logger.info("Cleared persona")

    content = [TextContent(
        type="text",
        text="Persona cleared.\n\n"
             "WARNING: All status transitions will now fail with 403 Forbidden.\n"
             "You must call select_persona() again before using transition_status() "
             "or update_requirement()."
    )]

    # Return special marker to clear persona
    return content, {"_persona": None}


async def apply_persona_defaults(
    tool_name: str,
    arguments: dict,
    current_persona: Optional[str] = None
) -> Tuple[dict, Optional[List[TextContent]]]:
    """Apply session persona for tools that require persona authorization.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments (may be modified)
        current_persona: Current session persona

    Returns:
        Tuple of (modified arguments, error content or None)
        If error content is not None, the caller should return it instead of proceeding.
    """
    # Tools that REQUIRE persona for status transitions
    persona_required_tools = {
        "transition_status",  # Always requires persona
    }

    # Tools that require persona only if status is being changed
    persona_conditional_tools = {
        "update_requirement",  # Requires persona only if status field is present
    }

    # Check if this is a tool that requires persona
    requires_persona = False

    if tool_name in persona_required_tools:
        requires_persona = True
    elif tool_name in persona_conditional_tools:
        # update_requirement requires persona if:
        # 1. "status" field is explicitly provided, OR
        # 2. "content" field is provided (could contain status in frontmatter)
        # We can't reliably parse frontmatter here, so we require persona
        # for any update that might affect status.
        if "status" in arguments or "content" in arguments:
            requires_persona = True
        # If only updating depends_on or other non-status fields, no persona needed

    if not requires_persona:
        return arguments, None

    # Persona is required but not set
    if current_persona is None:
        error_content = [TextContent(
            type="text",
            text="ERROR: No persona set for status transition.\n\n"
                 "You MUST call select_persona() before using this tool.\n\n"
                 "Example: select_persona(persona='developer')\n\n"
                 "Available personas:\n"
                 "• developer - for draft→review, in_progress→implemented\n"
                 "• product_owner - for review→approved\n"
                 "• tester - for implemented→validated\n"
                 "• release_manager - for validated→deployed\n"
                 "• enterprise_architect - governance override (all transitions)\n"
                 "• scrum_master - sprint coordination"
        )]
        return arguments, error_content

    # Apply persona to arguments
    arguments["persona"] = current_persona
    logger.info(f"Using session persona: {current_persona}")

    return arguments, None


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
    # Extract persona for header (not part of JSON body)
    persona = arguments.pop("persona", None)
    headers = {"X-Persona": persona} if persona else {}
    response = await client.patch(f"/requirements/{req_id}", json=arguments, headers=headers)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated requirement {req_id}: {result['title']}")

    text = f"Updated requirement: {result['title']}\n\n{formatters.format_requirement(result)}"
    return [TextContent(type="text", text=text)], current_scope


# NOTE: handle_delete_requirement removed from MCP - destructive operations require direct API access
# For soft retirement, use transition_status to move requirement to 'deprecated' status
# See RAAS-FEAT-079: MCP Destructive Operation Removal


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

    PERSONA AUTHORIZATION:
    • Different transitions require different personas
    • Declare your persona to authorize the transition
    """
    req_id = arguments["requirement_id"]
    new_status = arguments["new_status"]
    persona = arguments.get("persona")
    headers = {"X-Persona": persona} if persona else {}
    response = await client.patch(f"/requirements/{req_id}", json={"status": new_status}, headers=headers)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully transitioned requirement {req_id} to status: {new_status}")

    text = f"Transitioned '{result['title']}' to status: {new_status}"
    if persona:
        text += f" (persona: {persona})"
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
    • Categorized (security, architecture, business)
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
    • category: Filter by category (security, architecture, business)
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


# ============================================================================
# Change Request Handlers (RAAS-COMP-068)
# ============================================================================

async def handle_create_change_request(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new change request with justification and affected requirements.

    Change Requests (CR) gate updates to requirements that have passed review status.
    """
    data = {
        "organization_id": arguments["organization_id"],
        "justification": arguments["justification"],
        "affects": arguments["affects"],
    }
    response = await client.post("/change-requests/", json=data)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully created change request {result['human_readable_id']}")

    text = (
        f"Created change request: {result['human_readable_id']}\n"
        f"Status: {result['status']}\n"
        f"Justification: {result['justification']}\n"
        f"Affects: {result['affects_count']} requirements\n"
        f"Created: {result['created_at']}\n\n"
        f"Next steps:\n"
        f"1. Submit for review: transition_change_request(cr_id='{result['human_readable_id']}', new_status='review')\n"
        f"2. After approval, use this CR ID when updating requirements"
    )

    return [TextContent(type="text", text=text)], current_scope


async def handle_get_change_request(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a change request by UUID or human-readable ID."""
    cr_id = arguments["cr_id"]
    response = await client.get(f"/change-requests/{cr_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved change request {result['human_readable_id']}")

    affects_list = ", ".join(str(a) for a in result['affects'][:5])
    if len(result['affects']) > 5:
        affects_list += f"... and {len(result['affects']) - 5} more"

    text = (
        f"Change Request: {result['human_readable_id']}\n"
        f"Status: {result['status']}\n"
        f"Justification: {result['justification']}\n"
        f"Requestor: {result['requestor_email'] or 'Unknown'}\n"
        f"Created: {result['created_at']}\n"
        f"Updated: {result['updated_at']}\n\n"
        f"Scope:\n"
        f"  Affects: {result['affects_count']} requirements ({affects_list})\n"
        f"  Modified: {result['modifications_count']} requirements\n"
    )

    if result['approved_at']:
        text += f"\nApproved: {result['approved_at']} by {result['approved_by_email'] or 'Unknown'}"

    if result['completed_at']:
        text += f"\nCompleted: {result['completed_at']}"

    return [TextContent(type="text", text=text)], current_scope


async def handle_list_change_requests(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List and filter change requests with pagination."""
    params = {}
    for key in ["organization_id", "status", "page", "page_size"]:
        if key in arguments and arguments[key] is not None:
            value = arguments[key]
            # Normalize enum values to lowercase
            if key == "status" and isinstance(value, str):
                value = value.lower()
            params[key] = value

    response = await client.get("/change-requests/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed change requests: {result['total']} total, page {result['page']}")

    if result['total'] == 0:
        return [TextContent(type="text", text="No change requests found matching the filters.")], current_scope

    items_text = "\n\n".join([
        f"{item['human_readable_id']}: {item['status']}\n"
        f"  Justification: {item['justification'][:80]}{'...' if len(item['justification']) > 80 else ''}\n"
        f"  Requestor: {item['requestor_email'] or 'Unknown'}\n"
        f"  Affects: {item['affects_count']} | Modified: {item['modifications_count']}\n"
        f"  Created: {item['created_at']}"
        for item in result['items']
    ])

    summary = (
        f"Found {result['total']} change requests (page {result['page']} of {result['total_pages']})\n\n"
        f"{items_text}"
    )

    return [TextContent(type="text", text=summary)], current_scope


async def handle_transition_change_request(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Transition a change request to a new status."""
    cr_id = arguments["cr_id"]
    new_status = arguments["new_status"]
    # Normalize enum value to lowercase
    if isinstance(new_status, str):
        new_status = new_status.lower()

    response = await client.post(
        f"/change-requests/{cr_id}/transition",
        json={"new_status": new_status}
    )
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully transitioned change request {result['human_readable_id']} to {new_status}")

    text = (
        f"Transitioned change request: {result['human_readable_id']}\n"
        f"New status: {result['status']}\n"
    )

    if result['status'] == 'approved':
        text += (
            f"Approved at: {result['approved_at']}\n"
            f"Approved by: {result['approved_by_email'] or 'Unknown'}\n\n"
            f"This CR can now be used to update requirements in its scope."
        )
    elif result['status'] == 'completed':
        text += f"Completed at: {result['completed_at']}\n"
    elif result['status'] == 'review':
        text += "Submitted for review. Awaiting approval."
    elif result['status'] == 'draft':
        text += "Returned to draft for revision."

    return [TextContent(type="text", text=text)], current_scope


async def handle_complete_change_request(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Mark an approved change request as completed."""
    cr_id = arguments["cr_id"]

    response = await client.post(f"/change-requests/{cr_id}/complete")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully completed change request {result['human_readable_id']}")

    text = (
        f"Completed change request: {result['human_readable_id']}\n"
        f"Status: {result['status']}\n"
        f"Completed at: {result['completed_at']}\n"
        f"Modified: {result['modifications_count']} requirements\n\n"
        f"This CR is now closed and cannot be used for further updates."
    )

    return [TextContent(type="text", text=text)], current_scope


# ============================================================================
# Task Queue Handlers (RAAS-EPIC-027, RAAS-COMP-065)
# ============================================================================


def format_task(task: dict) -> str:
    """Format a task for display."""
    lines = [
        f"**{task['human_readable_id'] or task['id']}**: {task['title']}",
        f"Type: {task['task_type']} | Status: {task['status']} | Priority: {task['priority']}",
    ]

    if task.get('description'):
        lines.append(f"Description: {task['description'][:200]}...")

    if task.get('due_date'):
        lines.append(f"Due: {task['due_date']}")

    if task.get('source_type'):
        lines.append(f"Source: {task['source_type']} ({task.get('source_id', 'N/A')})")

    lines.append(f"Assignees: {task.get('assignee_count', 0)}")
    lines.append(f"Created: {task['created_at']}")

    if task.get('is_overdue'):
        lines.append("**OVERDUE**")

    return "\n".join(lines)


async def handle_create_task(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new task in the task queue."""
    # Normalize enum values to lowercase
    for key in ['status', 'task_type', 'priority']:
        if key in arguments and isinstance(arguments[key], str):
            arguments[key] = arguments[key].lower()
    response = await client.post("/tasks/", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully created task {result['human_readable_id']}")

    text = f"Created task: {result['human_readable_id']}\n\n{format_task(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_list_tasks(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List tasks with filtering and pagination."""
    params = {}
    # Enum fields that need lowercase normalization
    enum_fields = {'status', 'task_type', 'priority'}
    for key in ['organization_id', 'project_id', 'assignee_id', 'status', 'task_type',
                'priority', 'overdue_only', 'include_completed', 'page', 'page_size']:
        if key in arguments and arguments[key] is not None:
            value = arguments[key]
            # Normalize enum values to lowercase
            if key in enum_fields and isinstance(value, str):
                value = value.lower()
            params[key] = value

    response = await client.get("/tasks/", params=params)
    response.raise_for_status()
    result = response.json()

    items = result.get('items', [])
    total = result.get('total', 0)
    page = result.get('page', 1)
    total_pages = result.get('total_pages', 0)

    if not items:
        return [TextContent(type="text", text="No tasks found matching the criteria.")], current_scope

    text_parts = [f"Found {total} tasks (page {page}/{total_pages}):\n"]
    for task in items:
        overdue = " **OVERDUE**" if task.get('is_overdue') else ""
        text_parts.append(
            f"• {task['human_readable_id'] or task['id']}: {task['title']} "
            f"[{task['task_type']}] ({task['status']}) - {task['priority']}{overdue}"
        )

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


async def handle_get_task(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a specific task by ID."""
    task_id = arguments["task_id"]
    response = await client.get(f"/tasks/{task_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Retrieved task {result['human_readable_id']}")

    text = f"Task Details:\n\n{format_task(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_update_task(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update a task's fields."""
    task_id = arguments.pop("task_id")
    # Normalize enum values to lowercase
    for key in ['status', 'task_type', 'priority']:
        if key in arguments and isinstance(arguments[key], str):
            arguments[key] = arguments[key].lower()
    response = await client.patch(f"/tasks/{task_id}", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated task {result['human_readable_id']}")

    text = f"Updated task: {result['human_readable_id']}\n\n{format_task(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_assign_task(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Assign users to a task."""
    task_id = arguments.pop("task_id")
    response = await client.post(f"/tasks/{task_id}/assign", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully assigned task {result['human_readable_id']}")

    text = (
        f"Assigned task: {result['human_readable_id']}\n"
        f"Title: {result['title']}\n"
        f"Assignees: {result['assignee_count']}"
    )
    return [TextContent(type="text", text=text)], current_scope


async def handle_complete_task(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Mark a task as completed."""
    task_id = arguments["task_id"]
    response = await client.post(f"/tasks/{task_id}/complete")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully completed task {result['human_readable_id']}")

    text = (
        f"Completed task: {result['human_readable_id']}\n"
        f"Title: {result['title']}\n"
        f"Status: {result['status']}\n"
        f"Completed at: {result['completed_at']}"
    )
    return [TextContent(type="text", text=text)], current_scope


async def handle_get_my_tasks(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get all tasks assigned to the current user."""
    params = {}
    if arguments.get('include_completed'):
        params['include_completed'] = 'true'

    response = await client.get("/tasks/my", params=params)
    response.raise_for_status()
    tasks = response.json()

    if not tasks:
        return [TextContent(type="text", text="You have no tasks assigned to you.")], current_scope

    text_parts = [f"Your Tasks ({len(tasks)} total):\n"]

    # Group by priority
    by_priority = {'critical': [], 'high': [], 'medium': [], 'low': []}
    for task in tasks:
        priority = task['priority']
        by_priority[priority].append(task)

    for priority in ['critical', 'high', 'medium', 'low']:
        if by_priority[priority]:
            text_parts.append(f"\n**{priority.upper()}**")
            for task in by_priority[priority]:
                overdue = " **OVERDUE**" if task.get('is_overdue') else ""
                due = f" (due: {task['due_date'][:10]})" if task.get('due_date') else ""
                text_parts.append(
                    f"  • {task['human_readable_id']}: {task['title']} [{task['task_type']}]{due}{overdue}"
                )

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


# =============================================================================
# RAAS-EPIC-026: Elicitation Handlers
# =============================================================================


def format_clarification(c: dict) -> str:
    """Format a clarification point for display."""
    lines = [
        f"**{c['human_readable_id']}**: {c['title']}",
        f"  Status: {c['status']} | Priority: {c['priority']}",
        f"  Artifact: {c['artifact_type']} ({c['artifact_id'][:8]}...)",
    ]
    if c.get('assignee_id'):
        lines.append(f"  Assigned to: {c['assignee_id'][:8]}...")
    if c.get('due_date'):
        lines.append(f"  Due: {c['due_date'][:10]}")
    if c.get('description'):
        lines.append(f"  Description: {c['description'][:100]}...")
    return "\n".join(lines)


async def handle_create_clarification_point(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new clarification point."""
    response = await client.post("/elicitation/clarifications", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Created clarification point {result['human_readable_id']}")

    text = f"Created clarification point: {result['human_readable_id']}\n\n{format_clarification(result)}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_list_clarification_points(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List clarification points with filtering."""
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/elicitation/clarifications", params=params)
    response.raise_for_status()
    result = response.json()

    items = result.get('items', [])
    total = result.get('total', 0)

    if not items:
        return [TextContent(type="text", text="No clarification points found matching filters.")], current_scope

    text_parts = [f"Clarification Points ({total} total):\n"]
    for c in items:
        text_parts.append(format_clarification(c))
        text_parts.append("")

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


async def handle_get_my_clarifications(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get clarification points assigned to current user ('What needs my input?')."""
    params = {}
    if arguments.get('include_resolved'):
        params['include_resolved'] = 'true'

    response = await client.get("/elicitation/clarifications/mine", params=params)
    response.raise_for_status()
    result = response.json()

    items = result.get('items', [])
    if not items:
        return [TextContent(type="text", text="No clarification points need your input.")], current_scope

    text_parts = ["**What Needs Your Input?**\n"]

    # Group by priority
    by_priority = {'blocking': [], 'high': [], 'medium': [], 'low': []}
    for c in items:
        by_priority[c['priority']].append(c)

    for priority in ['blocking', 'high', 'medium', 'low']:
        if by_priority[priority]:
            text_parts.append(f"\n**{priority.upper()}**")
            for c in by_priority[priority]:
                due = f" (due: {c['due_date'][:10]})" if c.get('due_date') else ""
                text_parts.append(f"  • {c['human_readable_id']}: {c['title']}{due}")

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


async def handle_get_clarification_point(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a clarification point by ID."""
    clarification_id = arguments["clarification_id"]
    response = await client.get(f"/elicitation/clarifications/{clarification_id}")
    response.raise_for_status()
    result = response.json()

    text = f"Clarification Point Details:\n\n{format_clarification(result)}"
    if result.get('context'):
        text += f"\n\nContext: {result['context']}"
    if result.get('resolution_content'):
        text += f"\n\nResolution: {result['resolution_content']}"

    return [TextContent(type="text", text=text)], current_scope


async def handle_resolve_clarification_point(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Resolve a clarification point with an answer."""
    clarification_id = arguments.pop("clarification_id")
    response = await client.post(
        f"/elicitation/clarifications/{clarification_id}/resolve",
        json=arguments
    )
    response.raise_for_status()
    result = response.json()
    logger.info(f"Resolved clarification point {result['human_readable_id']}")

    text = f"Resolved: {result['human_readable_id']}\n\nResolution: {result['resolution_content']}"
    return [TextContent(type="text", text=text)], current_scope


async def handle_create_elicitation_session(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new elicitation session."""
    response = await client.post("/elicitation/sessions", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Created elicitation session {result['human_readable_id']}")

    text = (
        f"Created elicitation session: {result['human_readable_id']}\n"
        f"Target: {result['target_artifact_type']}\n"
        f"Status: {result['status']}"
    )
    return [TextContent(type="text", text=text)], current_scope


async def handle_get_elicitation_session(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get elicitation session with full conversation history."""
    session_id = arguments["session_id"]
    response = await client.get(f"/elicitation/sessions/{session_id}")
    response.raise_for_status()
    result = response.json()

    text_parts = [
        f"**Session: {result['human_readable_id']}**",
        f"Target: {result['target_artifact_type']}",
        f"Status: {result['status']}",
        f"Messages: {len(result.get('conversation_history', []))}",
        f"Gaps Identified: {len(result.get('identified_gaps', []))}",
        "",
        "**Conversation History:**"
    ]

    for msg in result.get('conversation_history', []):
        role = msg.get('role', 'unknown').upper()
        content = msg.get('content', '')[:200]
        text_parts.append(f"\n[{role}]: {content}...")

    if result.get('identified_gaps'):
        text_parts.append("\n**Identified Gaps:**")
        for gap in result['identified_gaps']:
            text_parts.append(f"  • {gap.get('description', 'Unknown gap')}")

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


async def handle_add_session_message(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Add a message to elicitation session conversation."""
    session_id = arguments.pop("session_id")
    response = await client.post(
        f"/elicitation/sessions/{session_id}/messages",
        json=arguments
    )
    response.raise_for_status()
    result = response.json()

    text = (
        f"Message added to session {result['human_readable_id']}\n"
        f"Total messages: {len(result.get('conversation_history', []))}"
    )
    return [TextContent(type="text", text=text)], current_scope


async def handle_complete_elicitation_session(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Mark an elicitation session as completed."""
    session_id = arguments["session_id"]
    final_artifact_id = arguments.get("final_artifact_id")

    params = {}
    if final_artifact_id:
        params["final_artifact_id"] = final_artifact_id

    response = await client.post(
        f"/elicitation/sessions/{session_id}/complete",
        params=params
    )
    response.raise_for_status()
    result = response.json()
    logger.info(f"Completed elicitation session {result['human_readable_id']}")

    text = (
        f"Completed elicitation session: {result['human_readable_id']}\n"
        f"Status: {result['status']}\n"
        f"Completed at: {result.get('completed_at', 'N/A')}"
    )
    if final_artifact_id:
        text += f"\nLinked to artifact: {final_artifact_id}"

    return [TextContent(type="text", text=text)], current_scope


async def handle_analyze_requirement(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Analyze a requirement for completeness and gaps."""
    response = await client.post("/elicitation/analyze/requirement", json=arguments)
    response.raise_for_status()
    result = response.json()

    text_parts = [
        f"**Gap Analysis: {result['requirement_title']}**",
        f"Completeness Score: {result['completeness_score']:.0%}",
        ""
    ]

    findings = result.get('findings', [])
    if not findings:
        text_parts.append("No issues found - requirement is well-defined!")
    else:
        # Group by severity
        by_severity = {'critical': [], 'high': [], 'medium': [], 'low': []}
        for f in findings:
            by_severity[f['severity']].append(f)

        for severity in ['critical', 'high', 'medium', 'low']:
            if by_severity[severity]:
                text_parts.append(f"\n**{severity.upper()} ({len(by_severity[severity])})**")
                for f in by_severity[severity]:
                    text_parts.append(f"  • [{f['issue_type']}] {f['description']}")
                    if f.get('suggestion'):
                        text_parts.append(f"    Suggestion: {f['suggestion']}")

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


async def handle_analyze_project(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Batch analyze all requirements in a project."""
    response = await client.post("/elicitation/analyze/project", json=arguments)
    response.raise_for_status()
    result = response.json()

    text_parts = [
        f"**Project Gap Analysis**",
        f"Requirements Analyzed: {result['requirements_analyzed']}/{result['total_requirements']}",
        f"Overall Completeness: {result['overall_completeness_score']:.0%}",
        "",
        "**Findings by Severity:**"
    ]

    for severity, count in result['findings_by_severity'].items():
        if count > 0:
            text_parts.append(f"  • {severity}: {count}")

    if result.get('requirements_with_issues'):
        text_parts.append("\n**Top Requirements with Issues:**")
        for req in result['requirements_with_issues'][:10]:
            text_parts.append(
                f"  • {req['human_readable_id']}: {req['title']} "
                f"(score: {req['score']:.0%}, critical: {req['critical_count']})"
            )

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope


async def handle_analyze_contradictions(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Detect contradictions between requirements."""
    params = {
        'scope_id': arguments['scope_id'],
        'scope_type': arguments.get('scope_type', 'epic')
    }
    response = await client.post("/elicitation/analyze/contradictions", params=params)
    response.raise_for_status()
    result = response.json()

    contradictions = result.get('contradictions', [])
    if not contradictions:
        return [TextContent(
            type="text",
            text=f"No contradictions detected in {result['scope_type']} scope."
        )], current_scope

    text_parts = [
        f"**Contradiction Analysis ({result['scope_type']})**",
        f"Found {len(contradictions)} potential contradiction(s):",
        ""
    ]

    for c in contradictions:
        text_parts.append(
            f"• **{c['requirement_a_title']}** vs **{c['requirement_b_title']}**"
        )
        text_parts.append(f"  Type: {c['contradiction_type']} | Severity: {c['severity']}")
        text_parts.append(f"  {c['description']}")
        text_parts.append("")

    return [TextContent(type="text", text="\n".join(text_parts))], current_scope
