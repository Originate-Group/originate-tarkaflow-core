"""Common MCP tool handlers shared between stdio and HTTP transports.

This module provides handler logic that can be used by both:
- src/mcp/server.py (stdio transport for local development)
- src/api/routers/mcp_http.py (HTTP transport with OAuth for production)

Session state management is handled by the caller (transport-specific).
"""
from typing import Optional, Any
import logging

import httpx
from mcp.types import TextContent

from . import formatters

logger = logging.getLogger("raas-mcp.handlers")


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
