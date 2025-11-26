"""RaaS MCP Server - Expose requirements management to AI assistants."""
import os
import sys
import asyncio
import logging
import traceback
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
from pydantic import AnyUrl

# Import shared formatters, tools, and handlers
from . import formatters
from . import tools
from . import handlers


# Configure logging to stderr (captured by Docker)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
    force=True
)
logger = logging.getLogger("raas-mcp")

# API Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000/api/v1")
RAAS_PAT = os.getenv("RAAS_PAT")  # Personal Access Token for authentication

logger.info(f"MCP Server starting with API_BASE_URL: {API_BASE_URL}")
if RAAS_PAT:
    logger.info("MCP Server configured with Personal Access Token authentication")
else:
    logger.info("MCP Server running without authentication (local development mode)")


# MCP Server instance
app = Server("raas-mcp")

# Session state for project and persona scope
# This is per-MCP-connection since each connection runs in its own process (stdio mode)
_session_project_scope: Optional[dict] = None  # Stores {project_id, name, slug, organization_id}
_session_persona: Optional[str] = None  # Stores persona name (e.g., "developer", "tester")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools for requirements management."""
    return tools.get_tools()


# Formatting functions moved to src/mcp/formatters.py
# Tool definitions moved to src/mcp/tools.py


# ============================================================================
# Tool Handlers
# ============================================================================


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent | EmbeddedResource]:
    """Handle MCP tool calls by delegating to shared handlers."""
    global _session_project_scope, _session_persona

    logger.info(f"Tool call: {name} with arguments: {arguments}")

    # Apply project scope defaults to arguments if applicable
    arguments = await handlers.apply_project_scope_defaults(name, arguments, _session_project_scope)

    # Apply persona defaults and check for required persona
    arguments, persona_error = await handlers.apply_persona_defaults(name, arguments, _session_persona)
    if persona_error is not None:
        # Return the error content directly - persona is required but not set
        return persona_error

    # Prepare headers with PAT authentication if available
    headers = {}
    if RAAS_PAT:
        headers["X-API-Key"] = RAAS_PAT

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=headers) as client:
        try:
            # Map tool names to handler functions
            handler_map = {
                # Organization handlers
                "list_organizations": handlers.handle_list_organizations,
                "get_organization": handlers.handle_get_organization,
                "create_organization": handlers.handle_create_organization,
                "update_organization": handlers.handle_update_organization,
                # NOTE: delete_organization removed - use API directly
                # Organization member handlers
                "list_organization_members": handlers.handle_list_organization_members,
                "add_organization_member": handlers.handle_add_organization_member,
                "update_organization_member": handlers.handle_update_organization_member,
                # NOTE: delete_organization_member removed - use API directly
                # Project handlers
                "list_projects": handlers.handle_list_projects,
                "get_project": handlers.handle_get_project,
                "create_project": handlers.handle_create_project,
                "update_project": handlers.handle_update_project,
                # NOTE: delete_project removed - use API directly
                # Project member handlers
                "list_project_members": handlers.handle_list_project_members,
                "add_project_member": handlers.handle_add_project_member,
                "update_project_member": handlers.handle_update_project_member,
                # NOTE: delete_project_member removed - use API directly
                # Project scope handlers
                "select_project": handlers.handle_select_project,
                "get_project_scope": handlers.handle_get_project_scope,
                "clear_project_scope": handlers.handle_clear_project_scope,
                # Persona scope handlers
                "select_persona": handlers.handle_select_persona,
                "get_persona": handlers.handle_get_persona,
                "clear_persona": handlers.handle_clear_persona,
                # User handlers
                "list_users": handlers.handle_list_users,
                "search_users": handlers.handle_search_users,
                "get_user": handlers.handle_get_user,
                "get_user_by_email": handlers.handle_get_user_by_email,
                # Requirement handlers
                "get_requirement_template": handlers.handle_get_requirement_template,
                "create_requirement": handlers.handle_create_requirement,
                "list_requirements": handlers.handle_list_requirements,
                "get_requirement": handlers.handle_get_requirement,
                "update_requirement": handlers.handle_update_requirement,
                # NOTE: delete_requirement removed - use API directly or transition to 'deprecated'
                "get_requirement_children": handlers.handle_get_requirement_children,
                "get_requirement_history": handlers.handle_get_requirement_history,
                "transition_status": handlers.handle_transition_status,
                # Guardrail handlers
                "get_guardrail_template": handlers.handle_get_guardrail_template,
                "create_guardrail": handlers.handle_create_guardrail,
                "get_guardrail": handlers.handle_get_guardrail,
                "update_guardrail": handlers.handle_update_guardrail,
                "list_guardrails": handlers.handle_list_guardrails,
                # Change request handlers (RAAS-COMP-068)
                "create_change_request": handlers.handle_create_change_request,
                "get_change_request": handlers.handle_get_change_request,
                "list_change_requests": handlers.handle_list_change_requests,
                "transition_change_request": handlers.handle_transition_change_request,
                "complete_change_request": handlers.handle_complete_change_request,
                # Task handlers (RAAS-COMP-065)
                "create_task": handlers.handle_create_task,
                "list_tasks": handlers.handle_list_tasks,
                "get_task": handlers.handle_get_task,
                "update_task": handlers.handle_update_task,
                "assign_task": handlers.handle_assign_task,
                "complete_task": handlers.handle_complete_task,
                "get_my_tasks": handlers.handle_get_my_tasks,
            }

            # Look up and execute handler
            handler = handler_map.get(name)
            if not handler:
                logger.warning(f"Unknown tool requested: {name}")
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # Special case for get_persona - return actual persona value
            if name == "get_persona":
                if _session_persona:
                    return [TextContent(
                        type="text",
                        text=f"Current persona: {_session_persona}\n\n"
                             f"This persona will be used for status transitions unless overridden."
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text="No persona is currently set.\n\n"
                             "Use select_persona(persona='developer') to set a default persona for status transitions."
                    )]

            # Execute handler and get result
            # Handlers return (content, scope_update) where scope_update can be:
            # - dict with project_id: project scope change
            # - dict with _persona key: persona scope change
            # - None: no change
            # - Same as current: no change
            content, scope_update = await handler(arguments, client, _session_project_scope)

            # Update session scope if handler modified it
            if scope_update is not None and scope_update is not _session_project_scope:
                # Check if this is a persona scope update
                if isinstance(scope_update, dict) and "_persona" in scope_update:
                    _session_persona = scope_update.get("_persona")
                    logger.info(f"Updated session persona to: {_session_persona}")
                else:
                    # Project scope update
                    _session_project_scope = scope_update

            return content

        except httpx.HTTPStatusError as e:
            # Log detailed HTTP error information
            logger.error(f"HTTP error during {name} call:")
            logger.error(f"  Status: {e.response.status_code}")
            logger.error(f"  URL: {e.request.url}")
            logger.error(f"  Request body: {e.request.content}")
            try:
                response_body = e.response.json()
                logger.error(f"  Response body: {response_body}")
                error_detail = response_body.get("detail", str(e))
            except Exception:
                response_text = e.response.text
                logger.error(f"  Response text: {response_text}")
                error_detail = response_text or str(e)
            logger.error(f"  Traceback: {traceback.format_exc()}")
            return [TextContent(type="text", text=f"Error: {error_detail}")]

        except httpx.RequestError as e:
            # Network/connection errors
            logger.error(f"Request error during {name} call:")
            logger.error(f"  Error type: {type(e).__name__}")
            logger.error(f"  Error message: {str(e)}")
            logger.error(f"  URL: {e.request.url if hasattr(e, 'request') else 'N/A'}")
            logger.error(f"  Traceback: {traceback.format_exc()}")
            return [TextContent(type="text", text=f"Error: Connection failed - {str(e)}")]

        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(f"Unexpected error during {name} call:")
            logger.error(f"  Error type: {type(e).__name__}")
            logger.error(f"  Error message: {str(e)}")
            logger.error(f"  Arguments: {arguments}")
            logger.error(f"  Traceback:\n{traceback.format_exc()}")
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {str(e)}")]


# Formatting functions moved to src/mcp/formatters.py for sharing between stdio and HTTP endpoints


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
