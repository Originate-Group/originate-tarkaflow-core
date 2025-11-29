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

# Session state for project and agent scope (CR-009: agent replaces persona)
# This is per-MCP-connection since each connection runs in its own process (stdio mode)
_session_project_scope: Optional[dict] = None  # Stores {project_id, name, slug, organization_id}
_session_agent: Optional[str] = None  # Stores agent email (e.g., "developer@tarka.internal")
_session_persona: Optional[str] = None  # Stores mapped role for backward compat
# CR-005/TARKA-FEAT-105: Client identification for agent selection constraints
# Format: "client-name/version" (e.g., "claude-desktop/1.2.3", "claude-code/0.1.0")
_session_client_id: Optional[str] = os.getenv("RAAS_CLIENT_ID")  # Can be set via env or MCP init


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
    global _session_project_scope, _session_agent, _session_persona

    logger.info(f"Tool call: {name} with arguments: {arguments}")

    # Apply project scope defaults to arguments if applicable
    arguments = await handlers.apply_project_scope_defaults(name, arguments, _session_project_scope)

    # Apply agent defaults and check for required agent (CR-009)
    arguments, agent_error = await handlers.apply_agent_defaults(name, arguments, _session_agent)
    if agent_error is not None:
        # Return the error content directly - agent is required but not set
        return agent_error

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
                # Agent scope handlers (CR-009: replaces persona, CR-012: adds authorization)
                "select_agent": handlers.handle_select_agent,
                "get_agent": handlers.handle_get_agent,
                "clear_agent": handlers.handle_clear_agent,
                "list_my_agents": handlers.handle_list_my_agents,
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
                # Task handlers (RAAS-COMP-065)
                "create_task": handlers.handle_create_task,
                "list_tasks": handlers.handle_list_tasks,
                "get_task": handlers.handle_get_task,
                "update_task": handlers.handle_update_task,
                "assign_task": handlers.handle_assign_task,
                "complete_task": handlers.handle_complete_task,
                "resolve_clarification_task": handlers.handle_resolve_clarification_task,
                "get_my_tasks": handlers.handle_get_my_tasks,
                # Elicitation handlers (RAAS-EPIC-026)
                # NOTE: CR-004 removed clarification point handlers (use task tools)
                # NOTE: CR-004 removed create_elicitation_session, add_session_message (internal)
                "get_elicitation_session": handlers.handle_get_elicitation_session,
                "complete_elicitation_session": handlers.handle_complete_elicitation_session,
                "analyze_requirement": handlers.handle_analyze_requirement,
                "analyze_project": handlers.handle_analyze_project,
                "analyze_contradictions": handlers.handle_analyze_contradictions,
                # Work Item handlers (CR-010: RAAS-COMP-075)
                "list_work_items": handlers.handle_list_work_items,
                "get_work_item": handlers.handle_get_work_item,
                "create_work_item": handlers.handle_create_work_item,
                "update_work_item": handlers.handle_update_work_item,
                "transition_work_item": handlers.handle_transition_work_item,
                "get_work_item_history": handlers.handle_get_work_item_history,
                # Requirement Versioning handlers (CR-002: RAAS-FEAT-097)
                "list_requirement_versions": handlers.handle_list_requirement_versions,
                "get_requirement_version": handlers.handle_get_requirement_version,
                "diff_requirement_versions": handlers.handle_diff_requirement_versions,
                "mark_requirement_deployed": handlers.handle_mark_requirement_deployed,
                "batch_mark_requirements_deployed": handlers.handle_batch_mark_requirements_deployed,
                # CR-002 (RAAS-FEAT-104): Work Item Diffs and Conflict Detection
                "get_work_item_diffs": handlers.handle_get_work_item_diffs,
                "check_work_item_conflicts": handlers.handle_check_work_item_conflicts,
                # RAAS-FEAT-099: Version Drift Detection
                "check_work_item_drift": handlers.handle_check_work_item_drift,
            }

            # Look up and execute handler
            handler = handler_map.get(name)
            if not handler:
                logger.warning(f"Unknown tool requested: {name}")
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # Special case for get_agent - return actual agent value (CR-009)
            if name == "get_agent":
                if _session_agent:
                    role = handlers.AGENT_ROLE_MAP.get(_session_agent, "unknown")
                    return [TextContent(
                        type="text",
                        text=f"Current agent: {_session_agent}\n"
                             f"Role: {role}\n\n"
                             f"This agent will be used for status transitions unless overridden."
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text="No agent is currently set.\n\n"
                             "Use select_agent(agent_email='developer@tarka.internal') to set a default agent for status transitions."
                    )]

            # Execute handler and get result
            # Handlers return (content, scope_update) where scope_update can be:
            # - dict with project_id: project scope change
            # - dict with _agent key: agent scope change (CR-009)
            # - None: no change
            # - Same as current: no change
            # CR-005: Pass client_id to select_agent for constraint checking
            if name == "select_agent":
                content, scope_update = await handler(arguments, client, _session_project_scope, _session_client_id)
            else:
                content, scope_update = await handler(arguments, client, _session_project_scope)

            # Update session scope if handler modified it
            if scope_update is not None and scope_update is not _session_project_scope:
                # Check if this is an agent scope update (CR-009)
                if isinstance(scope_update, dict) and "_agent" in scope_update:
                    _session_agent = scope_update.get("_agent")
                    _session_persona = scope_update.get("_persona")  # For backward compat
                    logger.info(f"Updated session agent to: {_session_agent} (role: {_session_persona})")
                elif isinstance(scope_update, dict) and "_persona" in scope_update:
                    # Legacy persona update (backward compat)
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
