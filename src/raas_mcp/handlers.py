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
# Agent Scope Handlers (CR-009: Replaces Persona System)
# ============================================================================

# Valid agent emails for workflow authorization (CR-009)
# Agent accounts use @tarka.internal domain
VALID_AGENT_EMAILS = {
    "code@tarka.internal",        # Claude Code (development tasks)
    "csa@tarka.internal",         # Client Success Agent
    "ba@tarka.internal",          # Business Analyst
    "ea@tarka.internal",          # Enterprise Architect (all transitions)
    "developer@tarka.internal",   # Developer role
    "tester@tarka.internal",      # Tester role
    "release_manager@tarka.internal",  # Release Manager role
}

# Map agent emails to their role for authorization
# This replaces the old persona->transition matrix with RBAC
AGENT_ROLE_MAP = {
    "code@tarka.internal": "developer",
    "csa@tarka.internal": "product_owner",
    "ba@tarka.internal": "product_owner",
    "ea@tarka.internal": "enterprise_architect",
    "developer@tarka.internal": "developer",
    "tester@tarka.internal": "tester",
    "release_manager@tarka.internal": "release_manager",
}


async def handle_select_agent(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None,
    client_id: Optional[str] = None,
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle select_agent tool call (CR-009, CR-012, CR-005).

    CR-012 adds authorization checking: directors must be explicitly authorized
    to use agents, or be organization owners (implicit authorization).

    CR-005/TARKA-FEAT-105 adds client constraints: agent-director mappings can
    restrict which MCP clients can use the agent via allowed_user_agents patterns.

    Args:
        arguments: Tool arguments containing agent_email and optional organization_id
        client: HTTP client for API calls
        current_scope: Current project scope (used to get organization_id if not provided)
        client_id: MCP client identifier (e.g., "claude-code/0.1.0") for constraint checking

    Returns:
        Tuple of (response content, agent scope marker)
    """
    agent_email = arguments["agent_email"].lower()

    # Validate agent email format
    if agent_email not in VALID_AGENT_EMAILS:
        valid_list = ", ".join(sorted(VALID_AGENT_EMAILS))
        return [TextContent(
            type="text",
            text=f"Invalid agent: {agent_email}\n\nValid agents: {valid_list}"
        )], current_scope

    # Get organization_id from arguments or current scope
    organization_id = arguments.get("organization_id")
    if not organization_id and current_scope and "organization_id" in current_scope:
        organization_id = current_scope["organization_id"]

    # CR-012: Check authorization if we have an organization context
    # CR-005: Include client_id for client constraint checking
    auth_type = None
    if organization_id:
        try:
            params = {
                "agent_email": agent_email,
                "organization_id": str(organization_id),
            }
            # CR-005: Add user_agent for client constraint checking
            if client_id:
                params["user_agent"] = client_id

            response = await client.get("/agents/check-authorization", params=params)

            if response.status_code == 403:
                error_data = response.json().get("detail", {})
                error_code = error_data.get("error", "agent_not_authorized")
                error_msg = error_data.get("message", "Not authorized to use this agent")

                # CR-005: Handle client constraint rejection differently
                if error_code == "client_not_allowed":
                    allowed = error_data.get("allowed_user_agents", [])
                    allowed_str = ", ".join(allowed) if allowed else "none"
                    return [TextContent(
                        type="text",
                        text=f"Client not allowed: {error_msg}\n\n"
                             f"Agent: {agent_email}\n"
                             f"Your client: {client_id or 'unknown'}\n"
                             f"Allowed clients: {allowed_str}\n\n"
                             f"This agent is restricted to specific MCP clients.\n"
                             f"Use list_my_agents() to see which agents you can use from this client."
                    )], {"_agent": None, "_persona": None}  # Clear agent on denial

                # BUG-001 Fix 3: Clear stale agent state on authorization denial
                # Don't preserve previous agent - explicit denial means no agent
                return [TextContent(
                    type="text",
                    text=f"Authorization denied: {error_msg}\n\n"
                         f"You are not authorized to act as '{agent_email}' in this organization.\n"
                         f"Contact an organization owner to create an agent-director mapping.\n\n"
                         f"Use list_my_agents() to see which agents you can use."
                )], {"_agent": None, "_persona": None}  # Clear agent on denial
            elif response.status_code == 404:
                return [TextContent(
                    type="text",
                    text=f"Agent not found: {agent_email}\n\n"
                         f"Use list_my_agents() to see available agents."
                )], current_scope
            elif response.status_code == 200:
                result = response.json()
                auth_type = result.get("authorization_type")
            else:
                # BUG-001 Fix 1: Fail closed on unexpected status codes
                # Security principle: authorization must fail closed, not open
                logger.error(f"Authorization check failed with unexpected status {response.status_code}")
                return [TextContent(
                    type="text",
                    text=f"Authorization check failed (status {response.status_code}).\n\n"
                         f"Cannot proceed without confirming authorization.\n"
                         f"Please try again or contact an administrator."
                )], {"_agent": None, "_persona": None}  # Explicitly clear agent state
        except Exception as e:
            # BUG-001 Fix 1: Fail closed on exception
            # Security principle: authorization must fail closed, not open
            logger.error(f"Authorization check failed with exception: {e}")
            return [TextContent(
                type="text",
                text=f"Authorization check failed: {e}\n\n"
                     f"Cannot proceed without confirming authorization.\n"
                     f"Please try again or contact an administrator."
            )], {"_agent": None, "_persona": None}  # Explicitly clear agent state

    role = AGENT_ROLE_MAP.get(agent_email, "unknown")
    logger.info(f"Set agent to: {agent_email} (role: {role}, auth_type: {auth_type})")

    # Build response message
    auth_info = ""
    if auth_type == "owner":
        auth_info = "\nAuthorization: implicit (you are an organization owner)"
    elif auth_type == "explicit":
        auth_info = "\nAuthorization: explicit (agent-director mapping exists)"
    elif not organization_id:
        auth_info = "\n\nNote: No organization context set. Use select_project() to set context " \
                   "for proper authorization enforcement."

    content = [TextContent(
        type="text",
        text=f"Agent set to: {agent_email}\n"
             f"Role: {role}{auth_info}\n\n"
             f"All status transitions will now use this agent for authorization.\n"
             f"Audit trail will show: director=<your user>, actor={agent_email}"
    )]

    # Return special marker dict to signal agent scope change
    # We store both the email and the mapped role for backward compatibility
    return content, {"_agent": agent_email, "_persona": role}


async def handle_get_agent(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle get_agent tool call (CR-009).

    Note: This handler doesn't have direct access to _session_agent,
    so the server must pass it differently. For now, we return a message
    that the agent should be checked via server state.
    """
    # The actual agent value is managed by the server
    # This handler is called for informational purposes
    content = [TextContent(
        type="text",
        text="Use select_agent() to set an agent, or check the server logs for current session agent."
    )]
    return content, current_scope


async def handle_clear_agent(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle clear_agent tool call (CR-009).

    Args:
        arguments: Tool arguments (empty for this tool)
        client: HTTP client (not used for this operation)
        current_scope: Current project scope (passed through unchanged)

    Returns:
        Tuple of (response content, agent scope marker with None)
    """
    logger.info("Cleared agent")

    content = [TextContent(
        type="text",
        text="Agent cleared.\n\n"
             "WARNING: All status transitions will now fail with 403 Forbidden.\n"
             "You must call select_agent() again before using transition_status() "
             "or update_requirement()."
    )]

    # Return special marker to clear both agent and persona (for backward compat)
    return content, {"_agent": None, "_persona": None}


async def handle_list_my_agents(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Handle list_my_agents tool call (CR-012).

    Returns agents the current user can direct in the organization.

    Args:
        arguments: Tool arguments containing organization_id (optional if project scope set)
        client: HTTP client for API calls
        current_scope: Current project scope (used to get organization_id if not provided)

    Returns:
        Tuple of (response content, scope unchanged)
    """
    # Get organization_id from arguments or current scope
    organization_id = arguments.get("organization_id")
    if not organization_id and current_scope and "organization_id" in current_scope:
        organization_id = current_scope["organization_id"]

    if not organization_id:
        return [TextContent(
            type="text",
            text="Organization ID required.\n\n"
                 "Either provide organization_id parameter or use select_project() first "
                 "to set the organization context."
        )], current_scope

    try:
        response = await client.get(
            "/agents/my-agents",
            params={"organization_id": str(organization_id)}
        )
        response.raise_for_status()
        data = response.json()

        # Format the agent list
        agents = data.get("agents", [])
        authorized_agents = [a for a in agents if a.get("is_authorized")]
        unauthorized_agents = [a for a in agents if not a.get("is_authorized")]

        lines = ["# Agents You Can Direct\n"]

        if authorized_agents:
            lines.append("## Authorized Agents\n")
            for agent in authorized_agents:
                auth_type = agent.get("authorization_type", "unknown")
                name = agent.get("full_name") or "No name"
                lines.append(f"• **{agent['email']}** ({name})")
                lines.append(f"  - Authorization: {auth_type}")
                # CR-005: Show client constraints if any
                allowed = agent.get("allowed_user_agents")
                if allowed:
                    allowed_str = ", ".join(allowed)
                    lines.append(f"  - Allowed clients: {allowed_str}")
                else:
                    lines.append(f"  - Allowed clients: all (unrestricted)")
            lines.append("")

        if unauthorized_agents:
            lines.append("## Unavailable Agents (not authorized)\n")
            for agent in unauthorized_agents:
                name = agent.get("full_name") or "No name"
                lines.append(f"• {agent['email']} ({name})")
            lines.append("")
            lines.append("To use these agents, contact an organization owner to create an agent-director mapping.")

        lines.append(f"\nDirector: {data.get('director_email', 'unknown')}")
        lines.append(f"Organization: {organization_id}")

        return [TextContent(type="text", text="\n".join(lines))], current_scope

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            return [TextContent(
                type="text",
                text="Access denied: You are not a member of this organization."
            )], current_scope
        raise
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        return [TextContent(
            type="text",
            text=f"Failed to list agents: {str(e)}"
        )], current_scope


async def apply_agent_defaults(
    tool_name: str,
    arguments: dict,
    current_agent: Optional[str] = None
) -> Tuple[dict, Optional[List[TextContent]]]:
    """Apply session agent for tools that require agent authorization (CR-009).

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments (may be modified)
        current_agent: Current session agent email

    Returns:
        Tuple of (modified arguments, error content or None)
        If error content is not None, the caller should return it instead of proceeding.
    """
    # Tools that REQUIRE agent for status transitions
    agent_required_tools = {
        "transition_status",  # Always requires agent
    }

    # Tools that require agent only if status is being changed
    agent_conditional_tools = {
        "update_requirement",  # Requires agent only if status field is present
    }

    # Check if this is a tool that requires agent
    requires_agent = False

    if tool_name in agent_required_tools:
        requires_agent = True
    elif tool_name in agent_conditional_tools:
        # update_requirement requires agent if:
        # 1. "status" field is explicitly provided, OR
        # 2. "content" field is provided (could contain status in frontmatter)
        # We can't reliably parse frontmatter here, so we require agent
        # for any update that might affect status.
        if "status" in arguments or "content" in arguments:
            requires_agent = True
        # If only updating depends_on or other non-status fields, no agent needed

    if not requires_agent:
        return arguments, None

    # Agent is required but not set
    if current_agent is None:
        error_content = [TextContent(
            type="text",
            text="ERROR: No agent set for status transition.\n\n"
                 "You MUST call select_agent() before using this tool.\n\n"
                 "Example: select_agent(agent_email='developer@tarka.internal')\n\n"
                 "Available agents:\n"
                 "• developer@tarka.internal - for draft→review, in_progress→implemented\n"
                 "• tester@tarka.internal - for implemented→validated\n"
                 "• release_manager@tarka.internal - for validated→deployed\n"
                 "• ea@tarka.internal - Enterprise Architect (all transitions)\n"
                 "• code@tarka.internal - Claude Code (development tasks)\n"
                 "• ba@tarka.internal - Business Analyst\n"
                 "• csa@tarka.internal - Client Success Agent"
        )]
        return arguments, error_content

    # Map agent to persona for backward compatibility with existing authorization
    role = AGENT_ROLE_MAP.get(current_agent, "developer")
    arguments["persona"] = role
    logger.info(f"Using session agent: {current_agent} (role: {role})")

    return arguments, None


# Backward compatibility aliases (CR-009 transition period)
# TODO: Remove after full migration
handle_select_persona = handle_select_agent
handle_get_persona = handle_get_agent
handle_clear_persona = handle_clear_agent
apply_persona_defaults = apply_agent_defaults


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
    # BUG-003: Send X-Agent-Email header for director/actor audit trail
    headers = {}
    if current_scope and current_scope.get("_agent"):
        headers["X-Agent-Email"] = current_scope["_agent"]
    response = await client.post("/requirements/", json=arguments, headers=headers)
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
    # BUG-003: Send X-Agent-Email header for director/actor audit trail
    if current_scope and current_scope.get("_agent"):
        headers["X-Agent-Email"] = current_scope["_agent"]
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
    # BUG-003: Send X-Agent-Email header for director/actor audit trail
    if current_scope and current_scope.get("_agent"):
        headers["X-Agent-Email"] = current_scope["_agent"]
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
# Task Queue Handlers (RAAS-EPIC-027, RAAS-COMP-065)
# ============================================================================


def format_task(task: dict, full_details: bool = False) -> str:
    """Format a task for display.

    Args:
        task: Task data dictionary
        full_details: If True, include full description. If False, truncate to 200 chars.
    """
    lines = [
        f"**{task['human_readable_id'] or task['id']}**: {task['title']}",
        f"Type: {task['task_type']} | Status: {task['status']} | Priority: {task['priority']}",
    ]

    if task.get('description'):
        if full_details:
            lines.append(f"Description: {task['description']}")
        else:
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

    text = f"Task Details:\n\n{format_task(result, full_details=True)}"
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


async def handle_resolve_clarification_task(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Resolve a clarification task with an answer (CR-003)."""
    task_id = arguments["task_id"]
    resolution_content = arguments["resolution_content"]

    response = await client.post(
        f"/tasks/{task_id}/resolve",
        json={"resolution_content": resolution_content}
    )
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully resolved clarification task {result['human_readable_id']}")

    text = (
        f"Resolved clarification task: {result['human_readable_id']}\n"
        f"Title: {result['title']}\n"
        f"Status: {result['status']}\n"
        f"Resolved at: {result['resolved_at']}\n"
        f"Resolution: {result['resolution_content'][:200]}{'...' if len(result.get('resolution_content', '')) > 200 else ''}"
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
# NOTE: CR-004 removed clarification point handlers (use tasks with task_type='clarification')
# NOTE: CR-004 removed create_elicitation_session, add_session_message (internal to workflow)
# =============================================================================


# NOTE: handle_create_elicitation_session removed in CR-004 - sessions are internal to workflow
# NOTE: handle_create_clarification_point removed in CR-004 - use create_task(task_type='clarification')
# NOTE: handle_list_clarification_points removed in CR-004 - use list_tasks(task_type='clarification')
# NOTE: handle_get_clarification_point removed in CR-004 - use get_task()
# NOTE: handle_resolve_clarification_point removed in CR-004 - use resolve_clarification_task()
# NOTE: handle_get_my_clarifications removed in CR-004 - use get_my_tasks()


async def handle_get_elicitation_session(
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


# NOTE: handle_add_session_message removed in CR-004 - sessions are internal to workflow


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


def _format_analysis_result(result: dict, indent: int = 0) -> list[str]:
    """Format a single gap analysis result, optionally with indentation."""
    prefix = "  " * indent
    text_parts = []

    # Header with score
    title = result['requirement_title']
    score = result['completeness_score']
    if indent == 0:
        text_parts.append(f"**Gap Analysis: {title}**")
        text_parts.append(f"Completeness Score: {score:.0%}")
    else:
        text_parts.append(f"{prefix}**{title}** ({score:.0%})")

    # Findings
    findings = result.get('findings', [])
    if not findings:
        text_parts.append(f"{prefix}No issues found")
    else:
        # Group by severity
        by_severity = {'critical': [], 'high': [], 'medium': [], 'low': []}
        for f in findings:
            by_severity[f['severity']].append(f)

        for severity in ['critical', 'high', 'medium', 'low']:
            if by_severity[severity]:
                text_parts.append(f"{prefix}**{severity.upper()} ({len(by_severity[severity])})**")
                for f in by_severity[severity]:
                    text_parts.append(f"{prefix}  • [{f['issue_type']}] {f['description']}")
                    if f.get('suggestion'):
                        text_parts.append(f"{prefix}    Suggestion: {f['suggestion']}")

    # Recursively format children
    child_analyses = result.get('child_analyses')
    if child_analyses:
        text_parts.append("")
        text_parts.append(f"{prefix}**Children ({len(child_analyses)}):**")
        for child in child_analyses:
            text_parts.append("")
            text_parts.extend(_format_analysis_result(child, indent + 1))

    return text_parts


async def handle_analyze_requirement(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Analyze a requirement for completeness and gaps."""
    response = await client.post("/elicitation/analyze/requirement", json=arguments)
    response.raise_for_status()
    result = response.json()

    text_parts = _format_analysis_result(result)

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


# ============================================================================
# Work Item Handlers (CR-010: RAAS-COMP-075)
# ============================================================================


async def handle_list_work_items(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List Work Items with filtering and pagination."""
    params = {k: v for k, v in arguments.items() if v is not None}
    response = await client.get("/work-items/", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {result['total']} work items")

    if result['total'] == 0:
        return [TextContent(type="text", text="No work items found matching criteria.")], current_scope

    items_text = "\n".join([formatters.format_work_item_summary(item) for item in result['items']])
    summary = f"Found {result['total']} work items (page {result['page']} of {result['total_pages']})\n\n{items_text}"

    return [TextContent(type="text", text=summary)], current_scope


async def handle_get_work_item(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a Work Item by UUID or human-readable ID."""
    work_item_id = arguments["work_item_id"]
    response = await client.get(f"/work-items/{work_item_id}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved work item {work_item_id}: {result['title']}")

    return [TextContent(type="text", text=formatters.format_work_item(result))], current_scope


async def handle_create_work_item(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Create a new Work Item."""
    response = await client.post("/work-items/", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully created work item: {result['human_readable_id']}")

    text = (f"Created work item: {result['human_readable_id']}\n"
            f"Type: {result['work_item_type']}\n"
            f"Status: {result['status']}\n\n"
            f"Full details:\n{formatters.format_work_item(result)}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_update_work_item(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Update a Work Item."""
    work_item_id = arguments.pop("work_item_id")
    response = await client.patch(f"/work-items/{work_item_id}", json=arguments)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully updated work item: {result['human_readable_id']}")

    return [TextContent(type="text", text=f"Updated work item:\n{formatters.format_work_item(result)}")], current_scope


async def handle_transition_work_item(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Transition a Work Item to a new status."""
    work_item_id = arguments["work_item_id"]
    new_status = arguments["new_status"]

    response = await client.post(f"/work-items/{work_item_id}/transition", json={"new_status": new_status})
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully transitioned work item {result['human_readable_id']} to {new_status}")

    text = (f"Transitioned {result['human_readable_id']} to **{new_status}**\n\n"
            f"{formatters.format_work_item(result)}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_get_work_item_history(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get change history for a Work Item."""
    work_item_id = arguments["work_item_id"]
    params = {}
    if arguments.get("limit"):
        params["limit"] = arguments["limit"]

    response = await client.get(f"/work-items/{work_item_id}/history", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved {len(result)} history entries for work item {work_item_id}")

    if not result:
        return [TextContent(type="text", text=f"No history found for work item {work_item_id}")], current_scope

    history_text = "\n".join([formatters.format_work_item_history(entry) for entry in result])
    text = f"**Work Item History ({work_item_id})**\n\n{history_text}"

    return [TextContent(type="text", text=text)], current_scope


# ============================================================================
# Requirement Versioning Handlers (CR-002: RAAS-FEAT-097)
# ============================================================================

async def handle_list_requirement_versions(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """List all versions of a requirement with pagination."""
    requirement_id = arguments["requirement_id"]
    params = {k: v for k, v in arguments.items() if v is not None and k != "requirement_id"}

    response = await client.get(f"/work-items/requirements/{requirement_id}/versions", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully listed {result['total']} versions for requirement {requirement_id}")

    if not result['items']:
        return [TextContent(type="text", text=f"No versions found for requirement {requirement_id}")], current_scope

    versions_text = "\n\n".join([formatters.format_requirement_version(v) for v in result['items']])
    # CR-006: Changed from current_version_number to deployed_version_number
    deployed_info = f"\nDeployed version: v{result['deployed_version_number']}" if result.get('deployed_version_number') else ""
    text = f"**Versions for {requirement_id}** ({result['total']} total){deployed_info}\n\n{versions_text}"

    return [TextContent(type="text", text=text)], current_scope


async def handle_get_requirement_version(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get a specific version of a requirement by version number."""
    requirement_id = arguments["requirement_id"]
    version_number = arguments["version_number"]

    response = await client.get(f"/work-items/requirements/{requirement_id}/versions/{version_number}")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully retrieved version {version_number} for requirement {requirement_id}")

    # Include full content for this version
    text = f"{formatters.format_requirement_version(result)}\n\n**Content:**\n{result.get('content', '(no content)')}"

    return [TextContent(type="text", text=text)], current_scope


async def handle_diff_requirement_versions(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get diff between two versions of a requirement."""
    requirement_id = arguments["requirement_id"]
    from_version = arguments["from_version"]
    to_version = arguments["to_version"]

    params = {"from_version": from_version, "to_version": to_version}
    response = await client.get(f"/work-items/requirements/{requirement_id}/versions/diff", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully generated diff v{from_version}→v{to_version} for requirement {requirement_id}")

    return [TextContent(type="text", text=formatters.format_version_diff(result))], current_scope


async def handle_mark_requirement_deployed(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Mark a requirement's deployed_version_id to track production deployment."""
    requirement_id = arguments["requirement_id"]
    params = {}
    if arguments.get("version_id"):
        params["version_id"] = arguments["version_id"]

    response = await client.post(f"/work-items/requirements/{requirement_id}/mark-deployed", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully marked requirement {requirement_id} as deployed")

    text = (f"Marked **{result.get('human_readable_id', requirement_id)}** as deployed\n"
            f"Deployed version: v{result.get('deployed_version_number', '?')}")

    return [TextContent(type="text", text=text)], current_scope


async def handle_batch_mark_requirements_deployed(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Batch mark multiple requirements as deployed."""
    requirement_ids = arguments["requirement_ids"]

    params = {"requirement_ids": requirement_ids}
    response = await client.post("/work-items/requirements/batch-mark-deployed", params=params)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Successfully marked {result.get('updated_count', 0)} requirements as deployed")

    text = (f"Batch deployment update complete\n"
            f"Updated: {result.get('updated_count', 0)} requirements\n"
            f"Failed: {result.get('failed_count', 0)} requirements")

    if result.get('errors'):
        text += f"\n\nErrors:\n" + "\n".join([f"- {e}" for e in result['errors']])

    return [TextContent(type="text", text=text)], current_scope


# =============================================================================
# CR-002 (RAAS-FEAT-104): Work Item Diffs and Conflict Detection
# =============================================================================


async def handle_get_work_item_diffs(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Get diffs for all affected requirements in a Work Item."""
    work_item_id = arguments["work_item_id"]

    response = await client.get(f"/work-items/{work_item_id}/diffs")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Retrieved diffs for Work Item {work_item_id}")

    # Format response
    text_lines = [
        f"## Work Item Diffs: {result.get('human_readable_id', work_item_id)}",
        f"Type: {result.get('work_item_type', 'unknown')}",
        f"Total affected: {result.get('total_affected', 0)}",
        f"With changes: {result.get('total_with_changes', 0)}",
        "",
    ]

    for req in result.get('affected_requirements', []):
        hrid = req.get('human_readable_id', str(req.get('requirement_id', 'unknown')))
        title = req.get('title', 'Untitled')
        has_changes = req.get('has_changes', False)
        changes_summary = req.get('changes_summary', '')

        status_marker = "**CHANGED**" if has_changes else "no changes"
        text_lines.append(f"### [{hrid}] {title}")
        text_lines.append(f"Status: {status_marker}")
        # CR-006: Changed from current_version_number to deployed_version_number
        text_lines.append(f"Deployed version: {req.get('deployed_version_number', 'N/A')}")
        text_lines.append(f"Latest version: {req.get('latest_version_number', 'N/A')}")
        if changes_summary:
            text_lines.append(f"Summary: {changes_summary}")
        text_lines.append("")

    return [TextContent(type="text", text="\n".join(text_lines))], current_scope


async def handle_check_work_item_conflicts(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Check for conflicts in a Work Item before approval/merge."""
    work_item_id = arguments["work_item_id"]

    response = await client.get(f"/work-items/{work_item_id}/check-conflicts")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Checked conflicts for Work Item {work_item_id}")

    # Format response
    has_conflicts = result.get('has_conflicts', False)
    conflict_count = result.get('conflict_count', 0)

    if has_conflicts:
        header = f"## CONFLICTS DETECTED: {result.get('human_readable_id', work_item_id)}"
        status_msg = f"**{conflict_count} requirement(s) have conflicts**"
    else:
        header = f"## No Conflicts: {result.get('human_readable_id', work_item_id)}"
        status_msg = "All affected requirements are up-to-date"

    text_lines = [header, status_msg, ""]

    for req in result.get('affected_requirements', []):
        hrid = req.get('human_readable_id', str(req.get('requirement_id', 'unknown')))
        title = req.get('title', 'Untitled')
        has_conflict = req.get('has_conflict', False)
        conflict_reason = req.get('conflict_reason', '')

        if has_conflict:
            text_lines.append(f"### CONFLICT: [{hrid}] {title}")
            text_lines.append(f"Reason: {conflict_reason}")
        else:
            text_lines.append(f"### OK: [{hrid}] {title}")
            if conflict_reason:
                text_lines.append(f"Note: {conflict_reason}")
        text_lines.append("")

    return [TextContent(type="text", text="\n".join(text_lines))], current_scope


async def handle_check_work_item_drift(
    arguments: dict,
    client: httpx.AsyncClient,
    current_scope: Optional[dict] = None
) -> tuple[list[TextContent], Optional[dict]]:
    """Check for version drift in a Work Item (RAAS-FEAT-099)."""
    work_item_id = arguments["work_item_id"]

    response = await client.get(f"/work-items/{work_item_id}/drift")
    response.raise_for_status()
    result = response.json()
    logger.info(f"Checked drift for Work Item {work_item_id}")

    # Format response
    has_drift = result.get('has_drift', False)
    drift_warnings = result.get('drift_warnings', [])

    hrid = result.get('work_item_human_readable_id', work_item_id)

    if has_drift:
        header = f"## DRIFT DETECTED: {hrid}"
        status_msg = f"**{len(drift_warnings)} requirement(s) have newer versions**"
    else:
        header = f"## No Drift: {hrid}"
        status_msg = "All targeted requirements are at their current versions"

    text_lines = [header, status_msg, ""]

    for warning in drift_warnings:
        req_hrid = warning.get('requirement_human_readable_id', str(warning.get('requirement_id', 'unknown')))
        target_v = warning.get('target_version', 1)
        # CR-006: Renamed from current_version to latest_version
        latest_v = warning.get('latest_version', 1)
        versions_behind = warning.get('versions_behind', 0)

        text_lines.append(f"### DRIFT: {req_hrid}")
        text_lines.append(f"- Targeting: v{target_v}")
        text_lines.append(f"- Latest: v{latest_v}")
        text_lines.append(f"- Versions behind: {versions_behind}")
        text_lines.append("")

    if not drift_warnings and not has_drift:
        text_lines.append("*No version drift detected. Work item targets are up-to-date.*")

    return [TextContent(type="text", text="\n".join(text_lines))], current_scope
