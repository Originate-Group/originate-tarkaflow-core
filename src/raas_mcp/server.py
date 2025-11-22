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

# Session state for project scope
# This is per-MCP-connection since each connection runs in its own process (stdio mode)
_session_project_scope: Optional[dict] = None  # Stores {project_id, name, slug, organization_id}


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
    """Handle MCP tool calls."""
    global _session_project_scope

    logger.info(f"Tool call: {name} with arguments: {arguments}")

    # Apply project scope defaults to arguments if applicable
    arguments = await handlers.apply_project_scope_defaults(name, arguments, _session_project_scope)

    # Prepare headers with PAT authentication if available
    headers = {}
    if RAAS_PAT:
        headers["X-API-Key"] = RAAS_PAT

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=headers) as client:
        try:
            # ============================================================================
            # Organization Handlers
            # ============================================================================
            if name == "list_organizations":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/organizations/", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {result['total']} organizations")

                items_text = "\n\n".join([formatters.format_organization(item) for item in result['items']])
                summary = f"Found {result['total']} organizations (page {result['page']} of {result['total_pages']})\n\n{items_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_organization":
                org_id = arguments["organization_id"]
                response = await client.get(f"/organizations/{org_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved organization {org_id}: {result['name']}")
                return [TextContent(type="text", text=formatters.format_organization(result))]

            elif name == "create_organization":
                response = await client.post("/organizations/", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully created organization: {result['name']} (ID: {result['id']})")
                return [TextContent(
                    type="text",
                    text=f"Created organization: {result['name']}\nID: {result['id']}\nSlug: {result['slug']}\n\nFull details:\n{formatters.format_organization(result)}"
                )]

            elif name == "update_organization":
                org_id = arguments.pop("organization_id")
                response = await client.put(f"/organizations/{org_id}", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated organization {org_id}: {result['name']}")
                return [TextContent(
                    type="text",
                    text=f"Updated organization: {result['name']}\n\n{formatters.format_organization(result)}"
                )]

            elif name == "delete_organization":
                org_id = arguments["organization_id"]
                response = await client.delete(f"/organizations/{org_id}")
                response.raise_for_status()
                logger.info(f"Successfully deleted organization {org_id}")
                return [TextContent(type="text", text=f"Successfully deleted organization {org_id}")]

            # ============================================================================
            # Organization Member Handlers
            # ============================================================================
            elif name == "list_organization_members":
                org_id = arguments["organization_id"]
                response = await client.get(f"/organizations/{org_id}/members")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {len(result)} members for organization {org_id}")

                if not result:
                    return [TextContent(type="text", text="No members found for this organization.")]

                members_text = "\n".join([formatters.format_organization_member(item) for item in result])
                return [TextContent(type="text", text=f"Organization Members:\n\n{members_text}")]

            elif name == "add_organization_member":
                org_id = arguments["organization_id"]
                response = await client.post(f"/organizations/{org_id}/members", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully added user {arguments['user_id']} to organization {org_id}")
                return [TextContent(
                    type="text",
                    text=f"Added user {result['user_id']} to organization with role: {result['role']}"
                )]

            elif name == "update_organization_member":
                org_id = arguments["organization_id"]
                user_id = arguments["user_id"]
                role = arguments["role"]
                response = await client.put(f"/organizations/{org_id}/members/{user_id}", json={"role": role})
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated user {user_id} role in organization {org_id}")
                return [TextContent(
                    type="text",
                    text=f"Updated user {result['user_id']} role to: {result['role']}"
                )]

            elif name == "remove_organization_member":
                org_id = arguments["organization_id"]
                user_id = arguments["user_id"]
                response = await client.delete(f"/organizations/{org_id}/members/{user_id}")
                response.raise_for_status()
                logger.info(f"Successfully removed user {user_id} from organization {org_id}")
                return [TextContent(type="text", text=f"Removed user {user_id} from organization")]

            # ============================================================================
            # Project Handlers
            # ============================================================================
            elif name == "list_projects":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/projects/", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {result['total']} projects")

                items_text = "\n\n".join([formatters.format_project(item) for item in result['items']])
                summary = f"Found {result['total']} projects (page {result['page']} of {result['total_pages']})\n\n{items_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_project":
                project_id = arguments["project_id"]
                response = await client.get(f"/projects/{project_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved project {project_id}: {result['name']}")
                return [TextContent(type="text", text=formatters.format_project(result))]

            elif name == "create_project":
                response = await client.post("/projects/", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully created project: {result['name']} (ID: {result['id']})")
                return [TextContent(
                    type="text",
                    text=f"Created project: {result['name']} ({result['slug']})\nID: {result['id']}\nStatus: {result['status']}\n\nFull details:\n{formatters.format_project(result)}"
                )]

            elif name == "update_project":
                project_id = arguments.pop("project_id")
                response = await client.put(f"/projects/{project_id}", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated project {project_id}: {result['name']}")
                return [TextContent(
                    type="text",
                    text=f"Updated project: {result['name']}\n\n{formatters.format_project(result)}"
                )]

            elif name == "delete_project":
                project_id = arguments["project_id"]
                response = await client.delete(f"/projects/{project_id}")
                response.raise_for_status()
                logger.info(f"Successfully deleted project {project_id}")
                return [TextContent(type="text", text=f"Successfully deleted project {project_id}")]

            elif name == "list_project_members":
                project_id = arguments["project_id"]
                response = await client.get(f"/projects/{project_id}/members")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {len(result)} members for project {project_id}")

                if not result:
                    return [TextContent(type="text", text="No members found for this project.")]

                members_text = "\n".join([formatters.format_project_member(item) for item in result])
                return [TextContent(type="text", text=f"Project Members:\n\n{members_text}")]

            elif name == "add_project_member":
                project_id = arguments["project_id"]
                response = await client.post(f"/projects/{project_id}/members", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully added user {arguments['user_id']} to project {project_id}")
                return [TextContent(
                    type="text",
                    text=f"Added user {result['user_id']} to project with role: {result['role']}"
                )]

            elif name == "update_project_member":
                project_id = arguments["project_id"]
                user_id = arguments["user_id"]
                role = arguments["role"]
                response = await client.put(f"/projects/{project_id}/members/{user_id}", json={"role": role})
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated user {user_id} role in project {project_id}")
                return [TextContent(
                    type="text",
                    text=f"Updated user {result['user_id']} role to: {result['role']}"
                )]

            elif name == "remove_project_member":
                project_id = arguments["project_id"]
                user_id = arguments["user_id"]
                response = await client.delete(f"/projects/{project_id}/members/{user_id}")
                response.raise_for_status()
                logger.info(f"Successfully removed user {user_id} from project {project_id}")
                return [TextContent(type="text", text=f"Removed user {user_id} from project")]

            # ============================================================================
            # Project Scope Handlers
            # ============================================================================
            elif name == "select_project":
                content, new_scope = await handlers.handle_select_project(arguments, client, _session_project_scope)
                _session_project_scope = new_scope
                return content

            elif name == "get_project_scope":
                content, _ = await handlers.handle_get_project_scope(arguments, client, _session_project_scope)
                return content

            elif name == "clear_project_scope":
                content, new_scope = await handlers.handle_clear_project_scope(arguments, client, _session_project_scope)
                _session_project_scope = new_scope
                return content

            # ============================================================================
            # User Handlers
            # ============================================================================
            elif name == "list_users":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/users/", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {result['total']} users")

                if result['total'] == 0:
                    return [TextContent(type="text", text="No users found.")]

                users_text = "\n\n".join([formatters.format_user(item) for item in result['items']])
                summary = f"Found {result['total']} users (page {result['page']} of {result['total_pages']})\n\n{users_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "search_users":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/users/search", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully searched users: found {result['total']} results")

                if result['total'] == 0:
                    return [TextContent(type="text", text="No users found matching search criteria.")]

                users_text = "\n\n".join([formatters.format_user(item) for item in result['items']])
                summary = f"Found {result['total']} users (page {result['page']} of {result['total_pages']})\n\n{users_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_user":
                user_id = arguments["user_id"]
                response = await client.get(f"/users/{user_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved user {user_id}: {result['email']}")
                return [TextContent(type="text", text=formatters.format_user(result))]

            elif name == "get_user_by_email":
                email = arguments["email"]
                response = await client.get(f"/users/by-email/{email}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully found user by email {email}: {result['id']}")
                return [TextContent(type="text", text=formatters.format_user(result))]

            # ============================================================================
            # Requirement Handlers
            # ============================================================================
            elif name == "get_requirement_template":
                req_type = arguments["type"]
                response = await client.get(f"/requirements/templates/{req_type}")
                response.raise_for_status()
                result = response.json()
                template_content = result["template"]
                logger.info(f"Successfully retrieved template for {req_type}")
                return [TextContent(
                    type="text",
                    text=f"Template for '{req_type}' requirement:\n\n```markdown\n{template_content}\n```\n\n"
                         f"INSTRUCTIONS:\n"
                         f"1. Copy the template above\n"
                         f"2. Replace placeholder values in the YAML frontmatter and markdown body\n"
                         f"3. Maintain the exact structure (frontmatter + markdown body)\n"
                         f"4. Pass the complete filled-in content to create_requirement() or update_requirement()"
                )]

            elif name == "create_requirement":
                response = await client.post("/requirements/", json=arguments)
                response.raise_for_status()
                result = response.json()
                readable_id = result.get('human_readable_id', 'PENDING')
                logger.info(f"Successfully created {result['type']}: {result['title']} ([{readable_id}])")
                return [TextContent(
                    type="text",
                    text=f"✅ Requirement created successfully!\n\n[{readable_id}] {result['title']}\nUUID: {result['id']}\nType: {result['type']}\nStatus: {result['status']}\n\nYou can reference this requirement as either:\n- Readable ID: {readable_id}\n- UUID: {result['id']}\n\nFull details:\n{formatters.format_requirement(result)}"
                )]

            elif name == "list_requirements":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/requirements/", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {result['total']} requirements (page {result['page']}/{result['total_pages']})")

                items_text = "\n".join([formatters.format_requirement_summary(item) for item in result['items']])
                summary = f"Found {result['total']} requirements (page {result['page']}/{result['total_pages']})\n{items_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_requirement":
                req_id = arguments["requirement_id"]
                response = await client.get(f"/requirements/{req_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved requirement {req_id}: {result['title']}")
                return [TextContent(type="text", text=formatters.format_requirement(result))]

            elif name == "update_requirement":
                req_id = arguments.pop("requirement_id")
                response = await client.patch(f"/requirements/{req_id}", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated requirement {req_id}: {result['title']}")
                return [TextContent(
                    type="text",
                    text=f"Updated requirement: {result['title']}\n\n{formatters.format_requirement(result)}"
                )]

            elif name == "delete_requirement":
                req_id = arguments["requirement_id"]
                response = await client.delete(f"/requirements/{req_id}")
                response.raise_for_status()
                logger.info(f"Successfully deleted requirement {req_id}")
                return [TextContent(type="text", text=f"Successfully deleted requirement {req_id}")]

            elif name == "get_requirement_children":
                req_id = arguments["requirement_id"]
                response = await client.get(f"/requirements/{req_id}/children")
                response.raise_for_status()
                result = response.json()

                if not result:
                    logger.info(f"No children found for requirement {req_id}")
                    return [TextContent(type="text", text="No children found for this requirement.")]

                logger.info(f"Successfully retrieved {len(result)} children for requirement {req_id}")
                children_text = "\n".join([formatters.format_requirement_summary(item) for item in result])
                return [TextContent(type="text", text=f"Children ({len(result)}):\n{children_text}")]

            elif name == "get_requirement_history":
                req_id = arguments["requirement_id"]
                limit = arguments.get("limit", 50)
                response = await client.get(f"/requirements/{req_id}/history", params={"limit": limit})
                response.raise_for_status()
                result = response.json()

                if not result:
                    logger.info(f"No history found for requirement {req_id}")
                    return [TextContent(type="text", text="No history found for this requirement.")]

                logger.info(f"Successfully retrieved {len(result)} history entries for requirement {req_id}")
                history_text = "\n".join([formatters.format_history(item) for item in result])
                return [TextContent(type="text", text=f"Change History:\n\n{history_text}")]

            elif name == "transition_status":
                req_id = arguments["requirement_id"]
                new_status = arguments["new_status"]
                response = await client.patch(f"/requirements/{req_id}", json={"status": new_status})
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully transitioned requirement {req_id} to status: {new_status}")
                return [TextContent(
                    type="text",
                    text=f"Transitioned '{result['title']}' to status: {new_status}"
                )]

            else:
                logger.warning(f"Unknown tool requested: {name}")
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

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
