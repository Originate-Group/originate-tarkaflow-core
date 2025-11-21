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


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools for requirements management."""
    return [
        # ============================================================================
        # Organization Tools
        # ============================================================================
        Tool(
            name="list_organizations",
            description="List all organizations with pagination. "
                       "Returns organizations that the current user is a member of.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default: 50, max: 100)"
                    }
                }
            }
        ),
        Tool(
            name="get_organization",
            description="Get an organization by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "UUID of the organization to retrieve"
                    }
                },
                "required": ["organization_id"]
            }
        ),
        Tool(
            name="create_organization",
            description="Create a new organization.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Organization name"
                    },
                    "slug": {
                        "type": "string",
                        "description": "URL-friendly slug (lowercase, alphanumeric, hyphens)"
                    },
                    "settings": {
                        "type": "object",
                        "description": "Optional JSON settings"
                    }
                },
                "required": ["name", "slug"]
            }
        ),
        Tool(
            name="update_organization",
            description="Update an organization. Only organization admins can update organization details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "UUID of the organization to update"
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional new name"
                    },
                    "settings": {
                        "type": "object",
                        "description": "Optional new settings (replaces existing)"
                    }
                },
                "required": ["organization_id"]
            }
        ),
        Tool(
            name="delete_organization",
            description="Delete an organization and all its data (cascading delete). "
                       "Only organization owners can delete an organization. Use with caution!",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "UUID of the organization to delete"
                    }
                },
                "required": ["organization_id"]
            }
        ),
        # ============================================================================
        # Project Tools
        # ============================================================================
        Tool(
            name="list_projects",
            description="List projects with pagination and filtering. "
                       "Returns projects based on visibility and membership.",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Filter by organization UUID"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived", "planning", "on_hold"],
                        "description": "Filter by project status"
                    },
                    "visibility": {
                        "type": "string",
                        "enum": ["public", "private"],
                        "description": "Filter by project visibility"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search in name and description"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default: 50, max: 100)"
                    }
                }
            }
        ),
        Tool(
            name="get_project",
            description="Get a project by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project to retrieve"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="create_project",
            description="Create a new project within an organization. "
                       "Project names should be outcome-focused (e.g., 'Customer Self-Service Portal') "
                       "rather than implementation-focused (e.g., 'React Frontend Rewrite').",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Parent organization UUID"
                    },
                    "name": {
                        "type": "string",
                        "description": "Project name (outcome-focused)"
                    },
                    "slug": {
                        "type": "string",
                        "description": "3-4 uppercase alphanumeric characters (e.g., 'RAAS', 'WEB', 'API')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description"
                    },
                    "visibility": {
                        "type": "string",
                        "enum": ["public", "private"],
                        "description": "Project visibility (default: public)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived", "planning", "on_hold"],
                        "description": "Project status (default: active)"
                    },
                    "value_statement": {
                        "type": "string",
                        "description": "Optional value statement"
                    },
                    "project_type": {
                        "type": "string",
                        "description": "Optional project type"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of tags"
                    }
                },
                "required": ["organization_id", "name", "slug"]
            }
        ),
        Tool(
            name="update_project",
            description="Update a project. Only project admins and organization admins can update projects.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project to update"
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional new name"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional new description"
                    },
                    "visibility": {
                        "type": "string",
                        "enum": ["public", "private"],
                        "description": "Optional new visibility"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived", "planning", "on_hold"],
                        "description": "Optional new status"
                    },
                    "value_statement": {
                        "type": "string",
                        "description": "Optional new value statement"
                    },
                    "project_type": {
                        "type": "string",
                        "description": "Optional new project type"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional new tags list"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="delete_project",
            description="Delete a project and all its requirements (cascading delete). "
                       "Only project admins and organization owners can delete projects. Use with caution!",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project to delete"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="list_project_members",
            description="List all members of a project with their roles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="add_project_member",
            description="Add a user to a project with a specific role. "
                       "Only project admins and organization admins can add members.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "UUID of the user to add"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["admin", "editor", "viewer"],
                        "description": "Project role (default: editor)"
                    }
                },
                "required": ["project_id", "user_id"]
            }
        ),
        Tool(
            name="update_project_member",
            description="Update a project member's role. "
                       "Only project admins and organization admins can update member roles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "UUID of the user"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["admin", "editor", "viewer"],
                        "description": "New project role"
                    }
                },
                "required": ["project_id", "user_id", "role"]
            }
        ),
        Tool(
            name="remove_project_member",
            description="Remove a user from a project. "
                       "Only project admins and organization admins can remove members.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "UUID of the user to remove"
                    }
                },
                "required": ["project_id", "user_id"]
            }
        ),
        # ============================================================================
        # User Tools
        # ============================================================================
        Tool(
            name="search_users",
            description="Search for users with optional filtering. "
                       "Useful for finding user UUIDs before adding them to projects. "
                       "Can filter by organization membership and search by email/name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default: 50, max: 100)"
                    },
                    "organization_id": {
                        "type": "string",
                        "description": "Filter by organization UUID (only users who are members)"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search term (matches email and full name, case-insensitive)"
                    }
                }
            }
        ),
        Tool(
            name="get_user",
            description="Get a user by their UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "UUID of the user to retrieve"
                    }
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="get_user_by_email",
            description="Get a user by their email address. "
                       "Useful for finding a user's UUID when you only know their email. "
                       "Email matching is case-insensitive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Email address of the user to find"
                    }
                },
                "required": ["email"]
            }
        ),
        # ============================================================================
        # Requirement Tools
        # ============================================================================
        Tool(
            name="get_requirement_template",
            description="Get the markdown template for a specific requirement type. "
                       "REQUIRED: You MUST call this tool BEFORE creating or updating any requirement to get the proper template format. "
                       "All requirements must be provided as properly formatted markdown with YAML frontmatter. "
                       "Templates include detailed guidance on writing outcome-focused requirements that describe WHAT and WHY, not HOW.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["epic", "component", "feature", "requirement"],
                        "description": "The requirement type to get the template for"
                    }
                },
                "required": ["type"]
            }
        ),
        Tool(
            name="create_requirement",
            description="Create a new requirement using a properly formatted markdown template. "
                       "REQUIRED WORKFLOW: "
                       "1. First call get_requirement_template() to get the template for the requirement type. "
                       "2. Fill in the template with the actual values, maintaining all markdown structure. "
                       "3. Pass the complete markdown content in the 'content' field. "
                       "The server will validate the content structure and reject improperly formatted requirements. "
                       "Epics are top-level and don't need a parent. All other types must specify a parent_id in the frontmatter. "
                       "CRITICAL: Requirements must focus on OUTCOMES (what/why), not IMPLEMENTATION (how). "
                       "Describe capabilities and behaviors, not code. Include data model structure, not code definitions. "
                       "State acceptance criteria, not implementation steps. See template for detailed writing guidelines and examples.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["epic", "component", "feature", "requirement"],
                        "description": "The type of requirement to create"
                    },
                    "content": {
                        "type": "string",
                        "description": "REQUIRED: The complete markdown content with YAML frontmatter. "
                                     "Must be obtained by calling get_requirement_template() first and filling in the template."
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project UUID (REQUIRED for epics, inherited from parent for other types). "
                                     "Get project ID from list_projects() or create_project()."
                    },
                    "title": {
                        "type": "string",
                        "description": "DEPRECATED: Use content field instead. This is extracted from markdown frontmatter."
                    },
                    "description": {
                        "type": "string",
                        "description": "READ-ONLY: Auto-extracted from content. Do not provide - will be ignored. "
                                     "The system automatically extracts description from markdown content (max 500 chars)."
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "DEPRECATED: Use content field instead. This is specified in markdown frontmatter."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "review", "approved", "in_progress", "implemented", "validated", "deployed"],
                        "description": "DEPRECATED: Use content field instead. This is specified in markdown frontmatter."
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "DEPRECATED: Use content field instead. This is specified in markdown frontmatter."
                    }
                },
                "required": ["type", "content"]
            }
        ),
        Tool(
            name="list_requirements",
            description="List and filter requirements with pagination (returns lightweight data without content field). "
                       "Use get_requirement() to fetch full content for specific requirements. "
                       "Returns: id, type, title, description (500 char max), status, tags, timestamps, "
                       "content_length, child_count. Use this to find requirements by type, status, parent, tags, or search text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["epic", "component", "feature", "requirement"],
                        "description": "Filter by requirement type"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "review", "approved", "in_progress", "implemented", "validated", "deployed"],
                        "description": "Filter by lifecycle status"
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Filter by parent requirement UUID"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search in title and description"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags (AND logic - requirement must have ALL specified tags). Example: ['sprint-1', 'repo:agency-os-core']"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default: 50, max: 100)"
                    }
                }
            }
        ),
        Tool(
            name="get_requirement",
            description="Get detailed information about a specific requirement by its UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID of the requirement to retrieve"
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="update_requirement",
            description="Update an existing requirement using properly formatted markdown. "
                       "REQUIRED WORKFLOW: "
                       "1. First call get_requirement() to get the current requirement. "
                       "2. Extract the 'content' field which contains the current markdown. "
                       "3. Modify the markdown content (update frontmatter or body as needed). "
                       "4. Pass the complete updated markdown in the 'content' field. "
                       "The server will validate the content structure and reject improperly formatted updates. "
                       "For simple status changes, use transition_status() instead. "
                       "REMINDER: Keep requirements outcome-focused (what/why), not prescriptive (how).",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID of the requirement to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "REQUIRED: The complete updated markdown content with YAML frontmatter."
                    },
                    "title": {
                        "type": "string",
                        "description": "DEPRECATED: Use content field instead. This is extracted from markdown frontmatter."
                    },
                    "description": {
                        "type": "string",
                        "description": "READ-ONLY: Auto-extracted from content. Do not provide - will be ignored. "
                                     "The system automatically extracts description from markdown content (max 500 chars)."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "review", "approved", "in_progress", "implemented", "validated", "deployed"],
                        "description": "DEPRECATED: Use content field or transition_status() instead."
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "DEPRECATED: Use content field instead. This is specified in markdown frontmatter."
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="delete_requirement",
            description="Delete a requirement and all its children (cascading delete). Use with caution!",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID of the requirement to delete"
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="get_requirement_children",
            description="Get all direct children of a requirement (returns lightweight data without content field). "
                       "Use get_requirement() to fetch full content for specific children. "
                       "Useful for exploring the hierarchy.",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID of the parent requirement"
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="get_requirement_history",
            description="View the change history for a requirement, including who changed what and when.",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID of the requirement"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of history entries (default: 50, max: 100)"
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="transition_status",
            description="Transition a requirement to a new lifecycle status. This is a convenience wrapper around update_requirement.",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID of the requirement"
                    },
                    "new_status": {
                        "type": "string",
                        "enum": ["draft", "review", "approved", "in_progress", "implemented", "validated", "deployed"],
                        "description": "Target status"
                    }
                },
                "required": ["requirement_id", "new_status"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent | EmbeddedResource]:
    """Handle MCP tool calls."""
    logger.info(f"Tool call: {name} with arguments: {arguments}")

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

                items_text = "\n\n".join([_format_organization(item) for item in result['items']])
                summary = f"Found {result['total']} organizations (page {result['page']} of {result['total_pages']})\n\n{items_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_organization":
                org_id = arguments["organization_id"]
                response = await client.get(f"/organizations/{org_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved organization {org_id}: {result['name']}")
                return [TextContent(type="text", text=_format_organization(result))]

            elif name == "create_organization":
                response = await client.post("/organizations/", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully created organization: {result['name']} (ID: {result['id']})")
                return [TextContent(
                    type="text",
                    text=f"Created organization: {result['name']}\nID: {result['id']}\nSlug: {result['slug']}\n\nFull details:\n{_format_organization(result)}"
                )]

            elif name == "update_organization":
                org_id = arguments.pop("organization_id")
                response = await client.put(f"/organizations/{org_id}", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated organization {org_id}: {result['name']}")
                return [TextContent(
                    type="text",
                    text=f"Updated organization: {result['name']}\n\n{_format_organization(result)}"
                )]

            elif name == "delete_organization":
                org_id = arguments["organization_id"]
                response = await client.delete(f"/organizations/{org_id}")
                response.raise_for_status()
                logger.info(f"Successfully deleted organization {org_id}")
                return [TextContent(type="text", text=f"Successfully deleted organization {org_id}")]

            # ============================================================================
            # Project Handlers
            # ============================================================================
            elif name == "list_projects":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/projects/", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {result['total']} projects")

                items_text = "\n\n".join([_format_project(item) for item in result['items']])
                summary = f"Found {result['total']} projects (page {result['page']} of {result['total_pages']})\n\n{items_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_project":
                project_id = arguments["project_id"]
                response = await client.get(f"/projects/{project_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved project {project_id}: {result['name']}")
                return [TextContent(type="text", text=_format_project(result))]

            elif name == "create_project":
                response = await client.post("/projects/", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully created project: {result['name']} (ID: {result['id']})")
                return [TextContent(
                    type="text",
                    text=f"Created project: {result['name']} ({result['slug']})\nID: {result['id']}\nStatus: {result['status']}\n\nFull details:\n{_format_project(result)}"
                )]

            elif name == "update_project":
                project_id = arguments.pop("project_id")
                response = await client.put(f"/projects/{project_id}", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated project {project_id}: {result['name']}")
                return [TextContent(
                    type="text",
                    text=f"Updated project: {result['name']}\n\n{_format_project(result)}"
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

                members_text = "\n".join([_format_project_member(item) for item in result])
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
            # User Handlers
            # ============================================================================
            elif name == "search_users":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/users/search", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully searched users: found {result['total']} results")

                if result['total'] == 0:
                    return [TextContent(type="text", text="No users found matching search criteria.")]

                users_text = "\n\n".join([_format_user(item) for item in result['items']])
                summary = f"Found {result['total']} users (page {result['page']} of {result['total_pages']})\n\n{users_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_user":
                user_id = arguments["user_id"]
                response = await client.get(f"/users/{user_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved user {user_id}: {result['email']}")
                return [TextContent(type="text", text=_format_user(result))]

            elif name == "get_user_by_email":
                email = arguments["email"]
                response = await client.get(f"/users/by-email/{email}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully found user by email {email}: {result['id']}")
                return [TextContent(type="text", text=_format_user(result))]

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
                logger.info(f"Successfully created {result['type']}: {result['title']} (ID: {result['id']})")
                return [TextContent(
                    type="text",
                    text=f"Created {result['type']}: {result['title']}\nID: {result['id']}\nStatus: {result['status']}\n\nFull details:\n{_format_requirement(result)}"
                )]

            elif name == "list_requirements":
                params = {k: v for k, v in arguments.items() if v is not None}
                response = await client.get("/requirements/", params=params)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully listed {result['total']} requirements (page {result['page']}/{result['total_pages']})")

                items_text = "\n\n".join([_format_requirement(item) for item in result['items']])
                summary = f"Found {result['total']} requirements (showing page {result['page']} of {result['total_pages']})\n\n{items_text}"
                return [TextContent(type="text", text=summary)]

            elif name == "get_requirement":
                req_id = arguments["requirement_id"]
                response = await client.get(f"/requirements/{req_id}")
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully retrieved requirement {req_id}: {result['title']}")
                return [TextContent(type="text", text=_format_requirement(result))]

            elif name == "update_requirement":
                req_id = arguments.pop("requirement_id")
                response = await client.patch(f"/requirements/{req_id}", json=arguments)
                response.raise_for_status()
                result = response.json()
                logger.info(f"Successfully updated requirement {req_id}: {result['title']}")
                return [TextContent(
                    type="text",
                    text=f"Updated requirement: {result['title']}\n\n{_format_requirement(result)}"
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
                children_text = "\n\n".join([_format_requirement(item) for item in result])
                return [TextContent(type="text", text=f"Children:\n\n{children_text}")]

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
                history_text = "\n".join([_format_history(item) for item in result])
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


def _format_organization(org: dict) -> str:
    """Format an organization for display."""
    settings_info = f"\nSettings: {org['settings']}" if org.get('settings') else ""

    return f"""**{org['name']}**
ID: {org['id']}
Slug: {org['slug']}{settings_info}
Created: {org['created_at']}
Updated: {org['updated_at']}"""


def _format_project(proj: dict) -> str:
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


def _format_project_member(member: dict) -> str:
    """Format a project member for display."""
    return f"- User {member['user_id']}: {member['role']} (joined: {member['joined_at']})"


def _format_user(user: dict) -> str:
    """Format a user for display."""
    name_info = f" ({user['full_name']})" if user.get('full_name') else ""
    return f"""**{user['email']}**{name_info}
ID: {user['id']}
Active: {user['is_active']}
Created: {user['created_at']}"""


def _format_requirement(req: dict) -> str:
    """Format a requirement for display with full content."""
    parent_info = f"\nParent ID: {req['parent_id']}" if req['parent_id'] else ""
    tags_info = f"\nTags: {', '.join(req['tags'])}" if req['tags'] else ""

    # Include computed metadata fields if available
    metadata_info = ""
    if 'content_length' in req:
        metadata_info += f"\nContent length: {req['content_length']} chars"
    if 'child_count' in req:
        metadata_info += f"\nChildren: {req['child_count']}"

    # Use full content if available, otherwise fall back to description
    # This ensures Desktop gets complete markdown for read → update workflows
    body = req.get('content') or req.get('description') or '(No content)'

    return f"""**{req['title']}** ({req['type']})
ID: {req['id']}{parent_info}
Status: {req['status']}{tags_info}{metadata_info}
Created: {req['created_at']}
Updated: {req['updated_at']}

{body}"""


def _format_history(entry: dict) -> str:
    """Format a history entry for display."""
    timestamp = entry['changed_at']
    change_type = entry['change_type']

    if entry['field_name']:
        return f"- [{timestamp}] {change_type}: {entry['field_name']} changed from '{entry['old_value']}' to '{entry['new_value']}'"
    else:
        return f"- [{timestamp}] {change_type}: {entry['new_value']}"


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
