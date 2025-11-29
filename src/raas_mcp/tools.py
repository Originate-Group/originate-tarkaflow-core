"""Shared MCP tool definitions for RaaS.

This module provides the definitive list of MCP tools used by both stdio and HTTP transports.
This prevents code drift and ensures both endpoints expose identical functionality.
"""

from mcp.types import Tool


def get_tools() -> list[Tool]:
    """Get the list of all MCP tools for RaaS requirements management."""
    return [
        # ============================================================================
        # Organization Tools
        # ============================================================================
        Tool(
            name="list_organizations",
            description="List all organizations with pagination (returns only organizations you're a member of). "
                       "Use get_organization() for detailed information about a specific organization. "
                       "Common pattern: list_organizations() → pick one → list_projects(organization_id=...) → work with projects.",
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
            description="Get detailed organization information. "
                       "Errors: 404 (not found), 403 (not a member).",
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
        # NOTE: delete_organization removed from MCP - use API directly for destructive operations
        # ============================================================================
        # Organization Member Tools
        # ============================================================================
        Tool(
            name="list_organization_members",
            description="List all members of an organization with their roles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "UUID of the organization"
                    }
                },
                "required": ["organization_id"]
            }
        ),
        Tool(
            name="add_organization_member",
            description="Add a user to an organization with a specific role. "
                       "Only organization admins and owners can add members.",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "UUID of the organization"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "UUID of the user to add"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["owner", "admin", "member", "viewer"],
                        "description": "Organization role (default: member)"
                    }
                },
                "required": ["organization_id", "user_id"]
            }
        ),
        Tool(
            name="update_organization_member",
            description="Update an organization member's role. "
                       "Only organization admins and owners can update member roles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "UUID of the organization"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "UUID of the user"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["owner", "admin", "member", "viewer"],
                        "description": "New organization role"
                    }
                },
                "required": ["organization_id", "user_id", "role"]
            }
        ),
        # NOTE: delete_organization_member removed from MCP - use API directly for destructive operations
        # ============================================================================
        # Project Tools
        # ============================================================================
        Tool(
            name="list_projects",
            description="List projects with pagination (filtered by visibility and membership). "
                       "Common pattern: list_projects(organization_id=...) → get project → list_requirements(project_id=...). "
                       "IMPORTANT: Always use project_id when querying requirements to avoid mixing data from multiple projects.",
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
            description="Get detailed project information. "
                       "Use project_id with list_requirements(project_id=...) to scope requirements correctly. "
                       "Errors: 404 (not found), 403 (no access).",
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
        # NOTE: delete_project removed from MCP - use API directly for destructive operations
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
        # NOTE: delete_project_member removed from MCP - use API directly for destructive operations
        # ============================================================================
        # User Tools
        # ============================================================================
        Tool(
            name="list_users",
            description="List all users with pagination. "
                       "Use for finding user IDs when managing organization/project members.",
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
        # Project Scope Tools
        # ============================================================================
        Tool(
            name="select_project",
            description="Set a default project scope for the current session to avoid repeating project_id in every requirement tool call. "
                       "\n\nWHY USE THIS:"
                       "\n• Eliminates repetitive project_id parameter in list_requirements, create_requirement, etc."
                       "\n• Prevents accidental cross-project operations"
                       "\n• More natural workflow: set context once, work within it"
                       "\n• Reduces cognitive load when working on single project"
                       "\n\nREQUIRED WORKFLOW:"
                       "\n1. Get project UUID from list_projects() or it's already known"
                       "\n2. Call select_project(project_id='...')"
                       "\n3. Optionally verify with get_project_scope() to confirm active scope"
                       "\n4. Use requirement tools (list_requirements, create_requirement, etc.) without project_id parameter"
                       "\n5. When done, optionally call clear_project_scope() to return to unscoped operation"
                       "\n\nCOMMON PATTERNS:"
                       "\n• Start of session: select_project(project_id='...') → work with requirements without project_id"
                       "\n• Switch projects: select_project(project_id='different-uuid') → new scope active immediately"
                       "\n• Verify scope: get_project_scope() → confirm which project is active"
                       "\n• Return to unscoped: clear_project_scope() → back to requiring explicit project_id"
                       "\n• Temporary override: list_requirements(project_id='other-uuid') → uses 'other-uuid' for this call only"
                       "\n\nSCOPE BEHAVIOR:"
                       "\n• All requirement tools will default to this project_id when not explicitly provided"
                       "\n• Explicit project_id in tool calls overrides the scope for that call only (doesn't change session scope)"
                       "\n• Scope persists for the entire MCP session until cleared or changed"
                       "\n• Validation: Project must exist and you must have access to it (verified before setting scope)"
                       "\n• Setting a new project_id replaces the previous scope immediately"
                       "\n\nRETURNS:"
                       "\n• Success confirmation message"
                       "\n• Project name and slug (human-readable identifiers)"
                       "\n• Project UUID and organization UUID (for verification)"
                       "\n• Confirmation that requirement tools will use this scope"
                       "\n\nRELATED TOOLS:"
                       "\n• get_project_scope() to query current scope"
                       "\n• clear_project_scope() to remove scope"
                       "\n• list_projects() to find project UUIDs"
                       "\n• All requirement tools (list_requirements, create_requirement, etc.) respect this scope as their default"
                       "\n\nERRORS:"
                       "\n• 404: Project not found or you don't have access to it"
                       "\n• 403: Not a member of the project's organization"
                       "\n• 400: Invalid project_id format (not a valid UUID)",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project to set as default scope"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="get_project_scope",
            description="Query the current project scope for this session. "
                       "\n\nWHEN TO USE:"
                       "\n• After calling select_project() to verify scope was set correctly"
                       "\n• Before performing batch operations to confirm you're in the right project"
                       "\n• When debugging unexpected behavior (to see which project is active)"
                       "\n• At start of session to check if a scope is already set"
                       "\n• After receiving requirement results to understand which project was queried"
                       "\n\nRETURNS:"
                       "\n• If scope is set: project details (project_id, name, slug, organization_id)"
                       "\n• If no scope is set: message indicating unscoped operation mode"
                       "\n• Does NOT make API calls (reads from session state only, instant response)"
                       "\n\nCOMMON PATTERNS:"
                       "\n• Verify after setting: select_project() → get_project_scope() → confirm project name"
                       "\n• Confirm before batch operations: get_project_scope() → verify correct project → proceed with updates"
                       "\n• Debugging workflow: get_project_scope() → check which project requirement tools will default to"
                       "\n• Safety check: get_project_scope() before create_requirement() to avoid wrong project"
                       "\n\nRELATED TOOLS:"
                       "\n• select_project() to set or change scope"
                       "\n• clear_project_scope() to remove scope"
                       "\n• list_requirements() which uses this scope as default"
                       "\n\nERRORS:"
                       "\n• None - this operation is stateless and cannot fail"
                       "\n• Always returns either current scope details or confirmation that no scope is set",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="clear_project_scope",
            description="Clear the project scope for this session, returning to unscoped operation. "
                       "\n\nWHEN TO USE:"
                       "\n• After completing focused work on a single project"
                       "\n• Before querying requirements across multiple projects"
                       "\n• When you want to explicitly provide project_id for each operation"
                       "\n• Before switching to a different project (optional, select_project() replaces scope automatically)"
                       "\n• At end of task to return to neutral state"
                       "\n\nEFFECT:"
                       "\n• Removes active project scope from session state"
                       "\n• All requirement tools will require explicit project_id parameter again (or operate globally if applicable)"
                       "\n• Does NOT affect already-created requirements or make any API changes"
                       "\n• Operation is idempotent (safe to call multiple times, even when no scope is set)"
                       "\n\nRETURNS:"
                       "\n• If scope was set: confirmation message with the previous project name and slug"
                       "\n• If no scope was set: confirmation that operation completed successfully (idempotent)"
                       "\n• Confirmation that requirement tools now require explicit project_id"
                       "\n\nCOMMON PATTERNS:"
                       "\n• After focused work: clear_project_scope() → ready for cross-project queries"
                       "\n• Clean switch pattern: clear_project_scope() → select_project(different_id) (optional, direct switch works too)"
                       "\n• Verify cleared: clear_project_scope() → get_project_scope() → confirms no scope"
                       "\n• End of session cleanup: clear_project_scope() → return to neutral state"
                       "\n\nRELATED TOOLS:"
                       "\n• select_project() to set a new scope (can replace scope without clearing first)"
                       "\n• get_project_scope() to verify scope was cleared"
                       "\n• list_requirements() will require project_id parameter after clearing"
                       "\n\nERRORS:"
                       "\n• None - this operation is idempotent and cannot fail"
                       "\n• Safe to call even when no scope is set (returns success confirmation)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        # ============================================================================
        # Agent Scope Tools (CR-009: Replaces Persona System)
        # ============================================================================
        Tool(
            name="select_agent",
            description="Set the acting agent for this session (REQUIRED before any status transitions). "
                       "\n\nIMPORTANT: You MUST call select_agent() before using transition_status() or "
                       "changing status via update_requirement(). Without an agent set, all transitions are unauthorized."
                       "\n\nWHY THIS IS REQUIRED:"
                       "\n• Enables audit trail showing 'director' (human) and 'actor' (agent)"
                       "\n• Ensures explicit agent declaration before transitions"
                       "\n• Agent roles (via RBAC) determine allowed transitions"
                       "\n\nAGENT ACCOUNTS (use @tarka.internal domain):"
                       "\n• developer@tarka.internal - draft→review (submit for review)"
                       "\n• ea@tarka.internal - Enterprise Architect (all transitions)"
                       "\n• code@tarka.internal - Claude Code (development tasks)"
                       "\n• ba@tarka.internal - Business Analyst"
                       "\n• csa@tarka.internal - Client Success Agent"
                       "\n\nCLIENT CONSTRAINTS (CR-005):"
                       "\n• Agent-director mappings can restrict which MCP clients can use specific agents"
                       "\n• E.g., ea@tarka.internal may be restricted to claude-desktop/* only"
                       "\n• code@tarka.internal may be restricted to claude-code/* only"
                       "\n• Use list_my_agents() to see which agents you can use from your current client"
                       "\n\nNOTE: CR-004 Phase 4 simplified requirement lifecycle to 4 states:"
                       "\n• draft → review → approved → deprecated"
                       "\n• Implementation status (in_progress, implemented, validated, deployed) is now tracked on Work Items"
                       "\n\nCOMMON PATTERNS:"
                       "\n• Start of session: select_agent(agent_email='developer@tarka.internal') → work normally"
                       "\n• Switch roles: select_agent(agent_email='tester@tarka.internal') → now authorized for validation"
                       "\n• Check current: get_agent() → verify before critical transitions"
                       "\n\nRETURNS: Confirmation of agent set"
                       "\n\nRELATED TOOLS:"
                       "\n• get_agent() to check current agent"
                       "\n• clear_agent() to remove agent (transitions will fail until re-selected)"
                       "\n• list_my_agents() to see which agents you can use from this client"
                       "\n• transition_status() and update_requirement() require this to be set first",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_email": {
                        "type": "string",
                        "description": "The agent account email (e.g., 'developer@tarka.internal')"
                    }
                },
                "required": ["agent_email"]
            }
        ),
        Tool(
            name="get_agent",
            description="Query the current agent setting for this session. "
                       "\n\nWHEN TO USE:"
                       "\n• Verify agent is set before making transitions"
                       "\n• Check which agent will be used for audit logging"
                       "\n\nRETURNS:"
                       "\n• Current agent email if set"
                       "\n• Message indicating no agent set otherwise",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="clear_agent",
            description="Clear the agent setting for this session. "
                       "\n\nWARNING: After clearing agent, ALL status transitions will fail until you call "
                       "select_agent() again. Use this only when you want to explicitly block transitions."
                       "\n\nWHEN TO USE:"
                       "\n• End of session cleanup"
                       "\n• When you want to ensure no accidental transitions"
                       "\n• Before handing off to another agent/user"
                       "\n\nEFFECT:"
                       "\n• Removes agent from session"
                       "\n• transition_status() will return 403 Forbidden"
                       "\n• update_requirement() status changes will return 403 Forbidden"
                       "\n\nRETURNS: Confirmation that agent was cleared",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="list_my_agents",
            description="List agents you are authorized to direct in an organization (CR-012). "
                       "\n\nReturns all agent accounts with authorization status indicating which ones "
                       "you can use with select_agent()."
                       "\n\nAUTHORIZATION TYPES:"
                       "\n• 'owner': You are an organization owner (implicit authorization for all agents)"
                       "\n• 'explicit': An agent-director mapping exists for you"
                       "\n• None: Not authorized (cannot use this agent)"
                       "\n\nCLIENT CONSTRAINTS (CR-005):"
                       "\n• Shows 'Allowed clients' for each agent with restrictions"
                       "\n• 'all (unrestricted)' means any MCP client can use this agent"
                       "\n• Specific patterns like 'claude-desktop/*' limit usage to matching clients"
                       "\n\nWHEN TO USE:"
                       "\n• Before calling select_agent() to see available options"
                       "\n• When select_agent() returns 'client not allowed' error"
                       "\n• To verify which agents you can use from your current client"
                       "\n\nPARAMETERS:"
                       "\n• organization_id: Optional if select_project() was called (uses project's org)"
                       "\n\nRETURNS: List of agents with authorization status and client constraints"
                       "\n\nRELATED TOOLS:"
                       "\n• select_agent() to set the active agent"
                       "\n• select_project() to set organization context",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Organization UUID (optional if project scope is set)"
                    }
                }
            }
        ),
        # ============================================================================
        # Requirement Tools
        # ============================================================================
        Tool(
            name="get_requirement_template",
            description="Get the markdown template for creating a new requirement (REQUIRED before create_requirement). "
                       "\n\nWHEN TO USE:"
                       "\n• ALWAYS call this FIRST before create_requirement() to get proper format"
                       "\n• Templates include YAML frontmatter structure + markdown body guidance"
                       "\n• Each requirement type (epic/component/feature/requirement) has different template"
                       "\n\nCOMMON PATTERNS:"
                       "\n• Create workflow: get_requirement_template(type='...') → fill in values → create_requirement(content=...)"
                       "\n• Reference for updates: Use to understand required frontmatter fields"
                       "\n\nRETURNS: Complete markdown template with:"
                       "\n• YAML frontmatter with required/optional fields"
                       "\n• Placeholder values to replace"
                       "\n• Detailed writing guidelines (outcome-focused, what/why not how)"
                       "\n• Examples of good vs bad requirements"
                       "\n\nRELATED TOOLS:"
                       "\n• Use this template with create_requirement() to create new requirements"
                       "\n• See also: update_requirement() for modifying existing requirements"
                       "\n\nERRORS: None (all types are valid)",
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
            description="Create a new requirement using properly formatted markdown template (with YAML frontmatter). "
                       "\n\nREQUIRED WORKFLOW:"
                       "\n1. Call get_requirement_template(type='...') to get the template"
                       "\n2. Fill in template with actual values (maintain markdown structure)"
                       "\n3. Optionally add 'depends_on: [uuid1, uuid2]' in YAML frontmatter"
                       "\n4. Pass complete markdown in create_requirement(content=...)"
                       "\n\nCOMMON PATTERNS:"
                       "\n• Create epic: get_requirement_template(type='epic') → fill → create_requirement()"
                       "\n• Create feature under component: Get template → add parent_id in frontmatter → create"
                       "\n• Create with dependencies: Add depends_on array in YAML frontmatter"
                       "\n\nHIERARCHY RULES:"
                       "\n• Epics: Top-level (no parent needed)"
                       "\n• Components: Must have parent_id pointing to an epic"
                       "\n• Features: Must have parent_id pointing to a component"
                       "\n• Requirements: Must have parent_id pointing to a feature"
                       "\n\nRETURNS: Created requirement object with generated UUID and human-readable ID"
                       "\n\nRELATED TOOLS:"
                       "\n• MUST call get_requirement_template() first to get proper format"
                       "\n• Use list_requirements(parent_id='...') to verify parent exists"
                       "\n\nERRORS:"
                       "\n• 400: Invalid markdown format (missing required frontmatter)"
                       "\n• 400: Invalid parent_id (parent not found or wrong type)"
                       "\n• 400: Dependency not found"
                       "\n• 403: Forbidden (no permission to create in this project)"
                       "\n\nREMINDER: Requirements must focus on OUTCOMES (what/why), not IMPLEMENTATION (how). "
                       "Describe capabilities, not code. See template for detailed writing guidelines.",
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
            description="List and filter requirements with pagination (lightweight, excludes full markdown content). "
                       "\n\nCOMMON PATTERNS:"
                       "\n• Browse → Details → Update: list_requirements() → get_requirement() → update_requirement()"
                       "\n• Find next work: list_requirements(ready_to_implement=true, status='approved')"
                       "\n• Explore hierarchy: list_requirements(parent_id='epic-uuid') → get children"
                       "\n• Search by tags: list_requirements(tags=['sprint-1', 'backend'])"
                       "\n\nRETURNS (lightweight data):"
                       "\n• Included: id, type, title, description (max 500 chars), status, tags, depends_on, timestamps, content_length, child_count"
                       "\n• NOT included: Full markdown content (use get_requirement for this)"
                       "\n\nRELATED TOOLS:"
                       "\n• Use get_requirement() to fetch full markdown content for a specific requirement"
                       "\n• Use get_requirement_children() to explore hierarchy"
                       "\n• Use transition_status() or update_requirement() to modify found requirements"
                       "\n\nERRORS:"
                       "\n• Invalid project_id: Returns empty results (not an error)"
                       "\n• Invalid filters: Silently ignored, returns unfiltered results",
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
                        "enum": ["draft", "review", "approved", "deprecated"],
                        "description": "Filter by lifecycle status (CR-004 Phase 4: 4-state model)"
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Filter by parent requirement UUID"
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Filter by project UUID"
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
                    "ready_to_implement": {
                        "type": "boolean",
                        "description": "Filter for requirements ready to implement (true = all dependencies code-complete, false = has unmet dependencies). "
                                     "Code-complete means deployed_version_id is set (CR-004 Phase 4). "
                                     "Use this to find 'next available work' - requirements that are unblocked and can be started immediately."
                    },
                    "blocked_by": {
                        "type": "string",
                        "description": "Filter for requirements that depend on the specified requirement UUID. "
                                     "Use this to see what work would be unblocked if a specific requirement is completed."
                    },
                    "include_deprecated": {
                        "type": "boolean",
                        "description": "Include deprecated requirements in results (default: false). "
                                     "Deprecated requirements are excluded by default."
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
            description="Get complete requirement details including full markdown content (heavy operation). "
                       "Accepts both UUID and human-readable ID (e.g., 'RAAS-FEAT-042', case-insensitive). "
                       "\n\nCOMMON PATTERNS:"
                       "\n• Read before update: get_requirement() → extract 'content' field → modify → update_requirement(content=...)"
                       "\n• Check dependencies: get_requirement() → inspect 'depends_on' array"
                       "\n• Browse then details: list_requirements() finds IDs → get_requirement() fetches full content"
                       "\n\nRETURNS (complete data):"
                       "\n• Included: ALL fields from list view PLUS full 'content' field (complete markdown with frontmatter)"
                       "\n• Use content field for read → modify → update workflows"
                       "\n\nRELATED TOOLS:"
                       "\n• Use list_requirements() first to find requirements (more efficient than fetching each individually)"
                       "\n• Use update_requirement(content=...) to save changes to the content field"
                       "\n• Use get_requirement_children() to explore child requirements"
                       "\n\nERRORS:"
                       "\n• 404: Requirement not found (invalid UUID or human-readable ID)"
                       "\n• 403: Forbidden (no access to this requirement's project/organization)",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID (e.g., 'RAAS-FEAT-042') of the requirement"
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="update_requirement",
            description="Update an existing requirement using properly formatted markdown OR update specific fields directly. "
                       "Accepts both UUID and human-readable ID. "
                       "\n\nPERSONA REQUIRED FOR STATUS CHANGES: If your update includes a status change "
                       "(either via status field or in markdown frontmatter), you MUST call select_persona() first. "
                       "Without a persona set, status transitions will return 403 Forbidden."
                       "\n\nCOMMON PATTERNS:"
                       "\n• Full content update: get_requirement() → modify content field → update_requirement(content=...)"
                       "\n• Add dependencies: update_requirement(requirement_id='...', depends_on=['uuid1', 'uuid2'])"
                       "\n• Clear dependencies: update_requirement(requirement_id='...', depends_on=[])"
                       "\n• Status-only change: Use transition_status() instead (simpler)"
                       "\n\nWORKFLOWS:"
                       "\n1. FULL MARKDOWN UPDATE (for title/description/body changes):"
                       "\n   a) Call get_requirement() to get current content"
                       "\n   b) Extract the 'content' field (markdown with YAML frontmatter)"
                       "\n   c) Modify the markdown (update frontmatter fields or body text)"
                       "\n   d) Pass complete updated markdown in update_requirement(content=...)"
                       "\n2. DEPENDENCY UPDATE (simpler, no markdown needed):"
                       "\n   a) Pass depends_on=[...] with array of requirement UUIDs or human-readable IDs"
                       "\n   b) Use empty array [] to clear all dependencies"
                       "\n\nRETURNS: Updated requirement object with all fields"
                       "\n\nRELATED TOOLS:"
                       "\n• Use get_requirement() first to fetch current content"
                       "\n• Use transition_status() for simple status changes (convenience wrapper)"
                       "\n• Deprecated: title, description, status, tags parameters (use 'content' field instead)"
                       "\n\nERRORS:"
                       "\n• 404: Requirement not found"
                       "\n• 400: Invalid markdown format (missing required frontmatter fields)"
                       "\n• 400: Invalid state transition (see transition_status for workflow rules)"
                       "\n• 400: Circular dependency detected"
                       "\n• 400: Dependency requirement not found or not in same project"
                       "\n• 403: Forbidden (no permission to update)"
                       "\n\nNOTE: Status changes via markdown frontmatter follow state machine rules (see transition_status for details)."
                       "\n\nREMINDER: Keep requirements outcome-focused (what/why), not prescriptive (how).",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the requirement to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "OPTIONAL: The complete updated markdown content with YAML frontmatter. "
                                     "Use this for full requirement updates including title, description, body text."
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "OPTIONAL: Array of requirement UUIDs this requirement depends on. "
                                     "Replaces all existing dependencies (use empty array [] to clear). "
                                     "Dependencies must be valid requirements in the same project. "
                                     "Circular dependencies are rejected. "
                                     "Example: ['uuid1', 'uuid2'] or use human-readable IDs: ['RAAS-FEAT-001', 'RAAS-REQ-042']"
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
                        "enum": ["draft", "review", "approved", "deprecated"],
                        "description": "DEPRECATED: Use content field or transition_status() instead. CR-004 Phase 4: 4-state model."
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
        # NOTE: delete_requirement removed from MCP - use API directly for destructive operations
        # For soft retirement, use transition_status to move requirement to 'deprecated' status
        Tool(
            name="get_requirement_children",
            description="Get all direct children of a requirement (lightweight, excludes full markdown content). "
                       "Accepts both UUID and human-readable ID (case-insensitive). "
                       "\n\nCOMMON PATTERNS:"
                       "\n• Explore hierarchy: get_requirement_children(epic_id) → shows components"
                       "\n• Navigate down: Get children → pick one → get_requirement_children(child_id) → deeper"
                       "\n• Preview before delete: get_requirement_children() → see what will be cascade deleted"
                       "\n\nRETURNS (lightweight data):"
                       "\n• Included: Same as list_requirements() - id, type, title, description (500 chars), status, tags, timestamps"
                       "\n• NOT included: Full markdown content (use get_requirement for specific child)"
                       "\n• Sorted by: created_at descending (newest first)"
                       "\n\nRELATED TOOLS:"
                       "\n• Use get_requirement() to fetch full content for specific children"
                       "\n• Use list_requirements(parent_id='...') for same result with more filter options"
                       "\n\nERRORS:"
                       "\n• 404: Parent requirement not found"
                       "\n• 403: Forbidden (no access to this requirement's project)",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID (e.g., 'RAAS-EPIC-001') of the parent requirement"
                    }
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="get_requirement_history",
            description="View complete change history for a requirement (audit trail). "
                       "Accepts both UUID and human-readable ID. "
                       "\n\nCOMMON PATTERNS:"
                       "\n• Audit trail: get_requirement_history() → see who changed what and when"
                       "\n• Debug changes: Check history to understand recent modifications"
                       "\n• Compliance: Retrieve full audit log for requirement"
                       "\n\nRETURNS: List of history entries with:"
                       "\n• Timestamp of change"
                       "\n• User who made the change"
                       "\n• Change type (created, updated, status_changed, etc.)"
                       "\n• Field name and old/new values"
                       "\n• Sorted by: Most recent first"
                       "\n\nRELATED TOOLS:"
                       "\n• Use get_requirement() to see current state"
                       "\n• Compare history with current content to understand evolution"
                       "\n\nERRORS:"
                       "\n• 404: Requirement not found"
                       "\n• 403: Forbidden (no access to this requirement)",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the requirement"
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
            description="Transition a requirement to a new lifecycle status (convenience tool, simpler than update_requirement). "
                       "Accepts both UUID and human-readable ID. "
                       "\n\nPREREQUISITE: You MUST call select_persona() first to set your workflow persona. "
                       "Without a persona set, this tool will return 403 Forbidden."
                       "\n\nSTATUS WORKFLOW (CR-004 Phase 4: 4-state model):"
                       "\n• Forward: draft → review → approved"
                       "\n• Back: approved → review → draft (for rework)"
                       "\n• CANNOT skip steps (e.g., draft → approved is blocked, must go draft → review → approved)"
                       "\n• deprecated is terminal (soft retirement - can transition TO deprecated from review/approved)"
                       "\n• Same-status transitions allowed (no-op)"
                       "\n\nIMPORTANT: Implementation states (in_progress, implemented, validated, deployed) are now"
                       "\ntracked on Work Items, NOT Requirements. Requirements are specifications only."
                       "\n\nPERSONA AUTHORIZATION:"
                       "\n• Different transitions require different personas (set via select_persona)"
                       "\n• Developer: draft→review"
                       "\n• Product Owner: review→approved, approved→deprecated"
                       "\n• Enterprise Architect: all transitions"
                       "\n\nCOMMON PATTERNS:"
                       "\n• select_persona(persona='developer') → transition_status(..., new_status='review')"
                       "\n• select_persona(persona='product_owner') → transition_status(..., new_status='approved')"
                       "\n\nWHEN TO USE:"
                       "\n• Use this tool for simple status-only changes (no other modifications)"
                       "\n• Use update_requirement() if you need to change content, dependencies, or other fields"
                       "\n\nRETURNS: Updated requirement object"
                       "\n\nRELATED TOOLS:"
                       "\n• select_persona() - MUST be called first to set persona"
                       "\n• get_persona() - check current persona before transitioning"
                       "\n• update_requirement() - for full updates including status"
                       "\n• Work Item tools for implementation tracking"
                       "\n\nERRORS:"
                       "\n• 403: No persona set (call select_persona first)"
                       "\n• 403: Persona not authorized for this transition"
                       "\n• 404: Requirement not found"
                       "\n• 400: Invalid state transition (e.g., draft → approved without review)"
                       "\n• 400: Invalid status value (not one of 4 valid statuses)",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the requirement"
                    },
                    "new_status": {
                        "type": "string",
                        "enum": ["draft", "review", "approved", "deprecated"],
                        "description": "Target status (CR-004 Phase 4: 4-state model)"
                    }
                },
                "required": ["requirement_id", "new_status"]
            }
        ),
        # ============================================================================
        # Guardrail Tools
        # ============================================================================
        Tool(
            name="get_guardrail_template",
            description="Get the markdown template for creating a new guardrail. "
                       "\n\nWHEN TO USE:"
                       "\n• ALWAYS call this FIRST before create_guardrail() to get proper format"
                       "\n• Template includes YAML frontmatter structure + markdown body guidance"
                       "\n\nRETURNS: Complete markdown template with:"
                       "\n• YAML frontmatter with required/optional fields"
                       "\n• Placeholder values to replace"
                       "\n• Detailed writing guidelines"
                       "\n• Examples of compliance criteria and reference patterns"
                       "\n\nRELATED TOOLS:"
                       "\n• Use this template with create_guardrail() to create new guardrails",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="create_guardrail",
            description="Create a new organizational guardrail with structured markdown content (with YAML frontmatter). "
                       "\n\nREQUIRED WORKFLOW:"
                       "\n1. Call get_guardrail_template() to get the template"
                       "\n2. Fill in template with actual values (maintain markdown structure)"
                       "\n3. Pass complete markdown in create_guardrail(content=...)"
                       "\n\nGUARDRAILS ARE:"
                       "\n• Organization-scoped (not project-scoped)"
                       "\n• Standards that guide requirement authoring across all projects"
                       "\n• Categorized (security, architecture, business)"
                       "\n• Have enforcement levels (advisory, recommended, mandatory)"
                       "\n• Specify which requirement types they apply to"
                       "\n\nRETURNS: Created guardrail object with generated UUID and human-readable ID (e.g., GUARD-SEC-001)"
                       "\n\nRELATED TOOLS:"
                       "\n• MUST call get_guardrail_template() first to get proper format"
                       "\n\nERRORS:"
                       "\n• 400: Invalid markdown format (missing required frontmatter)"
                       "\n• 400: Invalid category (must be 'security', 'architecture', or 'business')"
                       "\n• 403: Forbidden (user must be org admin or owner to create guardrails)",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Organization UUID (guardrails are organization-scoped)"
                    },
                    "content": {
                        "type": "string",
                        "description": "REQUIRED: The complete markdown content with YAML frontmatter. "
                                     "Must be obtained by calling get_guardrail_template() first and filling in the template."
                    }
                },
                "required": ["organization_id", "content"]
            }
        ),
        Tool(
            name="get_guardrail",
            description="Get complete guardrail details including full markdown content. "
                       "Accepts both UUID and human-readable ID (e.g., 'GUARD-SEC-001', case-insensitive). "
                       "\n\nRETURNS:"
                       "\n• All fields: id, human_readable_id, title, category, enforcement_level, applies_to, status, content, etc."
                       "\n• Full markdown content with frontmatter"
                       "\n\nERRORS:"
                       "\n• 404: Guardrail not found (invalid UUID or human-readable ID)"
                       "\n• 403: Forbidden (no access to this guardrail's organization)",
            inputSchema={
                "type": "object",
                "properties": {
                    "guardrail_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID (e.g., 'GUARD-SEC-001') of the guardrail"
                    }
                },
                "required": ["guardrail_id"]
            }
        ),
        Tool(
            name="update_guardrail",
            description="Update an existing guardrail with new markdown content. "
                       "\n\nWORKFLOW:"
                       "\n1. Call get_guardrail() to retrieve current content"
                       "\n2. Modify the markdown content (update title, status, body, etc.)"
                       "\n3. Pass complete updated markdown in update_guardrail(content=...)"
                       "\n\nFEATURES:"
                       "\n• All fields updatable: title, category, enforcement_level, applies_to, status, content"
                       "\n• UUID and human-readable ID remain stable across updates"
                       "\n• Validates structure same as creation"
                       "\n• Updates are immediate"
                       "\n\nRETURNS: Updated guardrail object"
                       "\n\nERRORS:"
                       "\n• 404: Guardrail not found"
                       "\n• 400: Invalid markdown format"
                       "\n• 403: Forbidden (user must be org admin or owner)",
            inputSchema={
                "type": "object",
                "properties": {
                    "guardrail_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID (e.g., 'GUARD-SEC-001') of the guardrail to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "REQUIRED: Complete updated markdown content with YAML frontmatter"
                    }
                },
                "required": ["guardrail_id", "content"]
            }
        ),
        Tool(
            name="list_guardrails",
            description="List and filter organizational guardrails with pagination and search. "
                       "\n\nFILTERS:"
                       "\n• organization_id: Filter by organization UUID"
                       "\n• category: Filter by category (security, architecture, business)"
                       "\n• enforcement_level: Filter by level (advisory, recommended, mandatory)"
                       "\n• applies_to: Filter by requirement type (epic, component, feature, requirement)"
                       "\n• status: Filter by status (defaults to 'active' only, use 'all' for all statuses)"
                       "\n• search: Keyword search in title and content"
                       "\n\nDEFAULT BEHAVIOR:"
                       "\n• Returns only active guardrails unless status filter specified"
                       "\n• Multiple filters combine with AND logic"
                       "\n• Results ordered by creation date (newest first)"
                       "\n\nRETURNS: Paginated list with lightweight items (excludes full content)"
                       "\n• Each item includes: id, human_readable_id, title, category, enforcement_level, applies_to, status, description"
                       "\n• Use get_guardrail() to fetch full content for specific guardrail"
                       "\n\nRELATED TOOLS:"
                       "\n• Use get_guardrail() to view full content of a specific guardrail",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Filter by organization UUID (optional)"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["security", "architecture", "business"],
                        "description": "Filter by category (optional)"
                    },
                    "enforcement_level": {
                        "type": "string",
                        "enum": ["advisory", "recommended", "mandatory"],
                        "description": "Filter by enforcement level (optional)"
                    },
                    "applies_to": {
                        "type": "string",
                        "enum": ["epic", "component", "feature", "requirement"],
                        "description": "Filter by requirement type applicability (optional)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "active", "deprecated", "all"],
                        "description": "Filter by status (defaults to 'active', use 'all' for all statuses)"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search keyword for title/content (optional)"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default: 50)"
                    }
                }
            }
        ),

        # ============================================================================
        # Task Queue Tools (RAAS-EPIC-027, RAAS-COMP-065)
        # ============================================================================

        Tool(
            name="create_task",
            description="Create a new task in the task queue. "
                       "\n\nTasks represent actionable items that need user attention. They can be created "
                       "directly or generated by task sources (clarification points, review requests, etc.)."
                       "\n\nREQUIRED FIELDS:"
                       "\n• organization_id: Organization UUID"
                       "\n• title: Task title"
                       "\n• task_type: Type of task (clarification, review, approval, gap_resolution, custom)"
                       "\n\nOPTIONAL FIELDS:"
                       "\n• project_id: Project UUID (for project-scoped tasks)"
                       "\n• description: Detailed description"
                       "\n• priority: low, medium (default), high, critical"
                       "\n• due_date: ISO 8601 datetime"
                       "\n• assignee_ids: List of user UUIDs to assign"
                       "\n• source_type, source_id: Link to source artifact"
                       "\n\nCLARIFICATION TASK FIELDS (CR-003 - use when task_type='clarification'):"
                       "\n• artifact_type: Type of artifact needing clarification (requirement, guardrail)"
                       "\n• artifact_id: UUID of the artifact needing clarification"
                       "\n• context: Why this clarification is needed"
                       "\n\nRETURNS: Created task with generated TASK-### ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Organization UUID"
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project UUID (optional, for project-scoped tasks)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title (required)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Task description (optional)"
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["clarification", "review", "approval", "gap_resolution", "custom"],
                        "description": "Type of task (required)"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Priority level (default: medium)"
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date in ISO 8601 format (optional)"
                    },
                    "assignee_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of user UUIDs to assign (optional)"
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Source system type (elicitation_session, clarification_point, requirement, guardrail, work_item)"
                    },
                    "source_id": {
                        "type": "string",
                        "description": "Source artifact UUID or human-readable ID (e.g., ELIC-002, CLAR-001, RAAS-FEAT-042)"
                    },
                    "artifact_type": {
                        "type": "string",
                        "description": "Type of artifact needing clarification: requirement, guardrail (for clarification tasks)"
                    },
                    "artifact_id": {
                        "type": "string",
                        "description": "UUID of artifact needing clarification (for clarification tasks)"
                    },
                    "context": {
                        "type": "string",
                        "description": "Why this clarification is needed (for clarification tasks)"
                    }
                },
                "required": ["organization_id", "title", "task_type"]
            }
        ),
        Tool(
            name="list_tasks",
            description="List tasks with filtering and pagination. "
                       "\n\nBy default, completed and cancelled tasks are excluded."
                       "\n\nFILTERS:"
                       "\n• organization_id: Filter by organization"
                       "\n• project_id: Filter by project"
                       "\n• assignee_id: Filter by assigned user"
                       "\n• status: pending, in_progress, completed, deferred, cancelled"
                       "\n• task_type: clarification, review, approval, gap_resolution, custom"
                       "\n• priority: low, medium, high, critical"
                       "\n• overdue_only: Only return overdue tasks"
                       "\n• include_completed: Include completed/cancelled tasks"
                       "\n\nORDERING: Priority (critical first) → due_date (earliest) → created_at (newest)",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Filter by organization UUID"
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Filter by project UUID"
                    },
                    "assignee_id": {
                        "type": "string",
                        "description": "Filter by assigned user UUID"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "deferred", "cancelled"],
                        "description": "Filter by status"
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["clarification", "review", "approval", "gap_resolution", "custom"],
                        "description": "Filter by task type"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Filter by priority"
                    },
                    "overdue_only": {
                        "type": "boolean",
                        "description": "Only return overdue tasks (default: false)"
                    },
                    "include_completed": {
                        "type": "boolean",
                        "description": "Include completed/cancelled tasks (default: false)"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default: 50, max: 100)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_task",
            description="Get a specific task by ID. "
                       "\n\nAccepts both UUID and human-readable ID (e.g., 'TASK-001', case-insensitive)."
                       "\n\nRETURNS: Full task details including assignees, source linking, and timestamps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the task"
                    }
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="update_task",
            description="Update a task's title, description, status, priority, or due date. "
                       "\n\nFor assignment changes, use assign_task instead."
                       "\n\nUPDATABLE FIELDS:"
                       "\n• title: New title"
                       "\n• description: New description"
                       "\n• status: pending, in_progress, completed, deferred, cancelled"
                       "\n• priority: low, medium, high, critical"
                       "\n• due_date: New due date (ISO 8601)",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the task"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title (optional)"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description (optional)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "deferred", "cancelled"],
                        "description": "New status (optional)"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "New priority (optional)"
                    },
                    "due_date": {
                        "type": "string",
                        "description": "New due date in ISO 8601 format (optional)"
                    }
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="assign_task",
            description="Assign users to a task. "
                       "\n\nCan add to existing assignees or replace all assignees."
                       "\n\nPARAMETERS:"
                       "\n• task_id: Task to assign"
                       "\n• assignee_ids: List of user UUIDs to assign"
                       "\n• replace: If true, replaces all existing assignees; if false (default), adds to existing",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the task"
                    },
                    "assignee_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of user UUIDs to assign"
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "If true, replaces all existing assignees (default: false)"
                    }
                },
                "required": ["task_id", "assignee_ids"]
            }
        ),
        Tool(
            name="complete_task",
            description="Mark a task as completed. "
                       "\n\nThis is a convenience tool equivalent to update_task(status='completed')."
                       "\n\nERRORS:"
                       "\n• 404: Task not found"
                       "\n• 400: Task already completed or cancelled",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the task"
                    }
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="resolve_clarification_task",
            description="Resolve a clarification task with an answer (CR-003). "
                       "\n\nMarks a clarification task as completed and records the resolution content. "
                       "Only works for tasks with task_type='clarification'."
                       "\n\nThis replaces the deprecated resolve_clarification_point tool."
                       "\n\nPARAMETERS:"
                       "\n• task_id: UUID or human-readable ID of the clarification task"
                       "\n• resolution_content: The answer/resolution to the clarification"
                       "\n\nERRORS:"
                       "\n• 404: Task not found"
                       "\n• 400: Task is not a clarification task"
                       "\n• 400: Task already completed",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID or human-readable ID of the clarification task"
                    },
                    "resolution_content": {
                        "type": "string",
                        "description": "The answer/resolution to the clarification"
                    }
                },
                "required": ["task_id", "resolution_content"]
            }
        ),
        Tool(
            name="get_my_tasks",
            description="Get all tasks assigned to you. "
                       "\n\nReturns tasks across all organizations and projects where you are assigned. "
                       "By default, excludes completed and cancelled tasks."
                       "\n\nThis is the primary tool for 'what needs my attention?' queries."
                       "\n\nORDERING: Priority (critical first) → due_date (earliest) → created_at (newest)",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_completed": {
                        "type": "boolean",
                        "description": "Include completed/cancelled tasks (default: false)"
                    }
                },
                "required": []
            }
        ),

        # =====================================================================
        # RAAS-EPIC-026: Elicitation Tools
        # =====================================================================

        # NOTE: CR-004 removed clarification point tools (use tasks with task_type='clarification'):
        # - create_clarification_point -> create_task(task_type='clarification')
        # - list_clarification_points -> list_tasks(task_type='clarification')
        # - get_clarification_point -> get_task()
        # - resolve_clarification_point -> resolve_clarification_task()
        # - get_my_clarifications -> get_my_tasks()
        #
        # NOTE: CR-004 removed create_elicitation_session, add_session_message (internal to workflow)

        # Elicitation Sessions (RAAS-COMP-063) - get_elicitation_session kept for viewing history
        Tool(
            name="get_elicitation_session",
            description="Get an elicitation session with full conversation history. "
                       "\n\nUse this to restore context when resuming a session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "UUID or human-readable ID (e.g., 'ELIC-001')"}
                },
                "required": ["session_id"]
            }
        ),
        # NOTE: add_session_message removed in CR-004 - sessions are internal to workflow
        Tool(
            name="complete_elicitation_session",
            description="Mark an elicitation session as completed. "
                       "\n\nUse this when the Socratic dialogue has concluded and the session's goals have been met. "
                       "Optionally link the session to a final artifact (requirement, guardrail) that was created or refined.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session UUID or human-readable ID (e.g., 'ELIC-001')"},
                    "final_artifact_id": {"type": "string", "description": "Optional UUID or human-readable ID of the artifact created/refined by this session"}
                },
                "required": ["session_id"]
            }
        ),

        # Gap Analyzer (RAAS-COMP-064)
        Tool(
            name="analyze_requirement",
            description="Analyze a requirement for completeness and gaps (RAAS-FEAT-086). "
                       "\n\nChecks for:"
                       "\n• Missing required sections"
                       "\n• Vague language (fast, easy, flexible, etc.)"
                       "\n• Incomplete information"
                       "\n\nReturns completeness score (0-100%) and findings by severity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "UUID or human-readable ID (e.g., CAAS-EPIC-006) of the requirement to analyze"},
                    "include_children": {"type": "boolean", "description": "Also analyze child requirements (default: false)"}
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="analyze_project",
            description="Batch analyze all requirements in a project (RAAS-FEAT-088). "
                       "\n\nProvides project-wide quality metrics and identifies requirements needing attention.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "UUID of the project"},
                    "requirement_types": {"type": "array", "items": {"type": "string"}, "description": "Filter by types (optional)"},
                    "statuses": {"type": "array", "items": {"type": "string"}, "description": "Filter by statuses (optional)"}
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="analyze_contradictions",
            description="Detect contradictions between requirements (RAAS-FEAT-087). "
                       "\n\nAnalyzes an epic or project for conflicting requirements.",
            inputSchema={
                "type": "object",
                "properties": {
                    "scope_id": {"type": "string", "description": "UUID of epic or project"},
                    "scope_type": {"type": "string", "enum": ["epic", "project"], "description": "Type of scope (default: epic)"}
                },
                "required": ["scope_id"]
            }
        ),

        # ========================================================================
        # Work Items (CR-010: RAAS-COMP-075)
        # ========================================================================

        Tool(
            name="list_work_items",
            description="List Work Items with filtering and pagination. "
                       "\n\nWork Items track implementation work: IR (Implementation Request), CR (Change Request), BUG, TASK."
                       "\n\nFILTERS:"
                       "\n• organization_id: Filter by organization UUID"
                       "\n• project_id: Filter by project UUID"
                       "\n• work_item_type: ir, cr, bug, task"
                       "\n• status: created, in_progress, implemented, validated, deployed, completed, cancelled"
                       "\n• assigned_to: Filter by assigned user UUID"
                       "\n• tags: Comma-separated tags"
                       "\n• include_completed: Include completed/cancelled items (default: false)"
                       "\n\nRETURNS: Paginated list of work items",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {"type": "string", "description": "Filter by organization UUID"},
                    "project_id": {"type": "string", "description": "Filter by project UUID"},
                    "work_item_type": {"type": "string", "enum": ["ir", "cr", "bug", "task"], "description": "Filter by type"},
                    "status": {"type": "string", "enum": ["created", "in_progress", "implemented", "validated", "deployed", "completed", "cancelled"], "description": "Filter by status"},
                    "assigned_to": {"type": "string", "description": "Filter by assigned user UUID"},
                    "search": {"type": "string", "description": "Search in title and description"},
                    "tags": {"type": "string", "description": "Comma-separated tags"},
                    "include_completed": {"type": "boolean", "description": "Include completed/cancelled items (default: false)"},
                    "page": {"type": "integer", "description": "Page number (default: 1)"},
                    "page_size": {"type": "integer", "description": "Items per page (default: 50, max: 100)"}
                },
                "required": []
            }
        ),
        Tool(
            name="get_work_item",
            description="Get a Work Item by UUID or human-readable ID (e.g., 'IR-001', 'CR-005'). "
                       "\n\nRETURNS: Full work item details including affected requirements and implementation refs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID (e.g., 'IR-001')"}
                },
                "required": ["work_item_id"]
            }
        ),
        Tool(
            name="create_work_item",
            description="Create a new Work Item. "
                       "\n\nWork Item types:"
                       "\n• ir: Implementation Request - new feature implementation"
                       "\n• cr: Change Request - modify existing requirements (triggers merge on completion)"
                       "\n• bug: Bug fix"
                       "\n• task: General task"
                       "\n\nAFFECTS: List requirement IDs (UUID or human-readable) that this work item affects. "
                       "For CRs, these requirements will be updated when the CR is completed."
                       "\n\nPROPOSED_CONTENT (CR only): For CRs, provide new markdown content for affected requirements. "
                       "Format: {requirement_id: \"new markdown content\"}",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {"type": "string", "description": "Organization UUID (required)"},
                    "project_id": {"type": "string", "description": "Project UUID (optional)"},
                    "work_item_type": {"type": "string", "enum": ["ir", "cr", "bug", "task"], "description": "Type of work item (required)"},
                    "title": {"type": "string", "description": "Work item title (required)"},
                    "description": {"type": "string", "description": "Detailed description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "description": "Priority (default: medium)"},
                    "assigned_to": {"type": "string", "description": "Assigned user UUID"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization"},
                    "affects": {"type": "array", "items": {"type": "string"}, "description": "Requirement IDs (UUID or human-readable) affected by this work"},
                    "proposed_content": {"type": "object", "description": "For CRs: {requirement_id: 'new markdown content'}"}
                },
                "required": ["organization_id", "work_item_type", "title"]
            }
        ),
        Tool(
            name="update_work_item",
            description="Update a Work Item's title, description, priority, assignment, or affects list. "
                       "\n\nFor status changes, use transition_work_item instead.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID"},
                    "title": {"type": "string", "description": "New title"},
                    "description": {"type": "string", "description": "New description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "description": "New priority"},
                    "assigned_to": {"type": "string", "description": "New assigned user UUID"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags (replaces existing)"},
                    "affects": {"type": "array", "items": {"type": "string"}, "description": "New affected requirements (replaces existing)"},
                    "proposed_content": {"type": "object", "description": "For CRs: updated proposed content"},
                    "implementation_refs": {"type": "object", "description": "GitHub references: {github_issue_url, pr_urls[], commit_shas[], release_tag}"}
                },
                "required": ["work_item_id"]
            }
        ),
        Tool(
            name="transition_work_item",
            description="Transition a Work Item to a new status. "
                       "\n\nLIFECYCLE: created -> in_progress -> implemented -> validated -> deployed -> completed"
                       "\n\nSPECIAL TRANSITIONS:"
                       "\n• cancelled: Can be reached from any non-terminal state"
                       "\n• completed (for CRs): Triggers automatic merge of proposed content to affected requirements"
                       "\n\nERRORS:"
                       "\n• 400: Invalid transition (must follow lifecycle)",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID"},
                    "new_status": {"type": "string", "enum": ["created", "in_progress", "implemented", "validated", "deployed", "completed", "cancelled"], "description": "Target status"}
                },
                "required": ["work_item_id", "new_status"]
            }
        ),
        Tool(
            name="get_work_item_history",
            description="Get change history for a Work Item. "
                       "\n\nRETURNS: List of changes with timestamps, change types, and who made them.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID"},
                    "limit": {"type": "integer", "description": "Max entries to return (default: 50, max: 100)"}
                },
                "required": ["work_item_id"]
            }
        ),

        # ========================================================================
        # Requirement Versioning (CR-002: RAAS-FEAT-097)
        # ========================================================================

        Tool(
            name="list_requirement_versions",
            description="List all versions of a requirement with pagination. "
                       "\n\nEvery content change creates an immutable version snapshot. "
                       "Use this to see the complete history of a requirement's evolution."
                       "\n\nRETURNS: List of versions with version_number, content_hash, title, created_at, source_work_item_id"
                       "\n\nRELATED TOOLS:"
                       "\n• get_requirement_version() to get full content of a specific version"
                       "\n• diff_requirement_versions() to compare two versions",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "UUID or human-readable ID (e.g., RAAS-FEAT-042)"},
                    "page": {"type": "integer", "description": "Page number (default: 1)"},
                    "page_size": {"type": "integer", "description": "Items per page (default: 50, max: 100)"}
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="get_requirement_version",
            description="Get a specific version of a requirement by version number. "
                       "\n\nRETURNS: Full version details including complete content snapshot."
                       "\n\nUSE CASES:"
                       "\n• View historical content at a point in time"
                       "\n• Compare what was approved vs current draft"
                       "\n• Audit trail for compliance",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "UUID or human-readable ID"},
                    "version_number": {"type": "integer", "description": "Version number (1, 2, 3...)"}
                },
                "required": ["requirement_id", "version_number"]
            }
        ),
        Tool(
            name="diff_requirement_versions",
            description="Get diff between two versions of a requirement. "
                       "\n\nRETURNS: Both versions' content for comparison, plus metadata."
                       "\n\nCOMMON PATTERNS:"
                       "\n• Compare deployed_version vs latest: See pending changes not yet in production"
                       "\n• Compare any two versions: Historical audit",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "UUID or human-readable ID"},
                    "from_version": {"type": "integer", "description": "Starting version number"},
                    "to_version": {"type": "integer", "description": "Ending version number"}
                },
                "required": ["requirement_id", "from_version", "to_version"]
            }
        ),
        Tool(
            name="mark_requirement_deployed",
            description="Mark a requirement's deployed_version_id to track production deployment. "
                       "\n\nCalled when a Release deploys to production. Updates deployed_version_id "
                       "to either a specific version or the resolved version (CR-006)."
                       "\n\nPARAMETERS:"
                       "\n• requirement_id: UUID or human-readable ID"
                       "\n• version_id: Optional specific version UUID (defaults to resolved version)"
                       "\n\nRETURNS: Updated requirement with new deployed_version_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "UUID or human-readable ID"},
                    "version_id": {"type": "string", "description": "Optional: specific version UUID to mark as deployed"}
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="batch_mark_requirements_deployed",
            description="Batch mark multiple requirements as deployed. "
                       "\n\nUse when a Release deploys multiple requirements to production. "
                       "Updates deployed_version_id to resolved version for all specified requirements (CR-006)."
                       "\n\nRETURNS: Count of successfully updated requirements",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of requirement UUIDs or human-readable IDs"
                    }
                },
                "required": ["requirement_ids"]
            }
        ),
        # CR-002 (RAAS-FEAT-104): Work Item Diffs and Conflict Detection
        Tool(
            name="get_work_item_diffs",
            description="Get diffs for all affected requirements in a Work Item (CR-002: RAAS-FEAT-104). "
                       "\n\nFor CR review, shows actual content changes for each affected requirement. "
                       "For CRs with proposed_content, shows diff between deployed_version and proposed. "
                       "For other Work Items, shows diff between deployed_version and latest version (CR-006)."
                       "\n\nUSE CASES:"
                       "\n• CR review: See exactly what will change when CR is merged"
                       "\n• Implementation review: See changes since last deployment"
                       "\n\nRETURNS: Diff details for each affected requirement with content and change summary",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID (e.g., 'CR-001', 'IR-042')"}
                },
                "required": ["work_item_id"]
            }
        ),
        Tool(
            name="check_work_item_conflicts",
            description="Check for conflicts before approving/merging a Work Item (CR-002: RAAS-FEAT-104). "
                       "\n\nProactive conflict detection that surfaces issues to reviewers before approval. "
                       "Compares baseline_hashes (captured when Work Item created) to current content hashes. "
                       "If a requirement's content changed since Work Item creation, it's flagged as conflict."
                       "\n\nWHEN TO USE:"
                       "\n• Before approving a CR - ensure no one else modified the requirements"
                       "\n• Before merging - detect concurrent changes"
                       "\n• During review - surface conflicts early"
                       "\n\nRETURNS: Conflict status for each affected requirement with has_conflicts flag",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID (e.g., 'CR-001', 'IR-042')"}
                },
                "required": ["work_item_id"]
            }
        ),
        Tool(
            name="check_work_item_drift",
            description="Check for version drift on a Work Item (RAAS-FEAT-099). "
                       "\n\nSemantic version drift detection that shows which targeted requirements "
                       "have newer versions available. Unlike check_work_item_conflicts (hash-based), "
                       "this provides semantic information: 'You're targeting RAAS-FEAT-042 v3, but it's now at v5'"
                       "\n\nWHEN TO USE:"
                       "\n• During implementation - check if specs evolved since you started"
                       "\n• Before marking implemented - ensure you implemented the correct version"
                       "\n• When picking up stale work - see if requirements have changed"
                       "\n\nRETURNS: Drift warnings showing target version vs current version for each requirement",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "string", "description": "UUID or human-readable ID (e.g., 'IR-001', 'CR-042')"}
                },
                "required": ["work_item_id"]
            }
        ),
    ]
