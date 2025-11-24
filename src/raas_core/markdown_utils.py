"""Utilities for working with markdown requirement templates."""
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional
from uuid import UUID

import yaml

from .models import RequirementType


TEMPLATES_DIR = Path(__file__).parent / "templates"


class MarkdownParseError(Exception):
    """Raised when markdown content cannot be parsed."""
    pass


def load_template(req_type: RequirementType) -> str:
    """Load the markdown template for a requirement type.

    Args:
        req_type: The requirement type (epic, component, feature, requirement)

    Returns:
        The template content as a string

    Raises:
        FileNotFoundError: If the template file doesn't exist
    """
    template_path = TEMPLATES_DIR / f"{req_type.value}.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    return template_path.read_text()


def render_template(
    req_type: RequirementType,
    title: str,
    description: str = "",
    parent_id: Optional[UUID] = None,
    status: str = "draft",
    tags: list[str] = None,
) -> str:
    """Render a markdown template with the provided data.

    Args:
        req_type: The requirement type
        title: The requirement title
        description: The requirement description
        parent_id: The parent requirement ID (for non-epic types)
        status: The lifecycle status
        tags: List of tags

    Returns:
        The rendered markdown content
    """
    template = load_template(req_type)
    tags = tags or []

    # Format tags as YAML array
    tags_yaml = json.dumps(tags)

    # Format parent_id (null for epics, UUID string for others)
    parent_id_str = str(parent_id) if parent_id else "null"

    # Replace template variables
    content = template.format(
        title=title,
        description=description or "No description provided.",
        parent_id=parent_id_str,
        status=status,
        tags=tags_yaml,
    )

    return content


def parse_markdown(content: str) -> Dict[str, Any]:
    """Parse markdown content with YAML frontmatter.

    Args:
        content: The markdown content to parse

    Returns:
        A dictionary containing:
        - frontmatter: Dict of YAML frontmatter data
        - body: The markdown body content

    Raises:
        MarkdownParseError: If content cannot be parsed
    """
    # Match YAML frontmatter pattern (between --- markers)
    frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if not match:
        raise MarkdownParseError(
            "Invalid markdown format: missing YAML frontmatter. "
            "Content must start with --- and contain valid YAML metadata."
        )

    frontmatter_str = match.group(1)
    body = match.group(2).strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError:
        # Try unsafe_load for legacy content with Python object tags
        try:
            frontmatter = yaml.unsafe_load(frontmatter_str)
            # Sanitize: convert any enum objects to their string values
            for key, value in list(frontmatter.items()):
                if hasattr(value, 'value'):
                    frontmatter[key] = value.value
        except Exception:
            # Last resort: manually parse YAML and extract enum values from Python tags
            # This handles cases where the Python module path is wrong/missing
            frontmatter = {}
            for line in frontmatter_str.split('\n'):
                # Handle simple key: value pairs
                if ':' in line and not line.strip().startswith('-'):
                    key, _, value = line.partition(':')
                    key = key.strip()
                    value = value.strip()

                    # Skip Python object tags
                    if value.startswith('!!python/object'):
                        continue

                    # Handle quoted strings
                    if value.startswith('"') or value.startswith("'"):
                        value = value.strip('"').strip("'")

                    # Handle lists
                    if value.startswith('['):
                        import json
                        try:
                            value = json.loads(value)
                        except:
                            value = []

                    # Store the value
                    if key and value:
                        frontmatter[key] = value
                # Handle array items (for status values under Python tags)
                elif line.strip().startswith('- ') and 'status' in frontmatter_str:
                    if 'status' not in frontmatter or isinstance(frontmatter.get('status'), str) and frontmatter['status'].startswith('!!python'):
                        frontmatter['status'] = line.strip()[2:].strip()

            if not frontmatter:
                raise MarkdownParseError(f"Could not parse YAML frontmatter")

    if not isinstance(frontmatter, dict):
        raise MarkdownParseError("Frontmatter must be a YAML dictionary")

    return {
        "frontmatter": frontmatter,
        "body": body,
    }


def validate_frontmatter(frontmatter: Dict[str, Any], req_type: RequirementType) -> None:
    """Validate that frontmatter contains required fields.

    Args:
        frontmatter: The parsed frontmatter dictionary
        req_type: The expected requirement type

    Raises:
        MarkdownParseError: If frontmatter is invalid
    """
    # Required fields for all types
    required_fields = ["type", "title", "status"]

    # parent_id required for non-epic types
    if req_type != RequirementType.EPIC:
        required_fields.append("parent_id")

    # Check for missing required fields
    missing = [f for f in required_fields if f not in frontmatter]
    if missing:
        raise MarkdownParseError(
            f"Missing required frontmatter fields: {', '.join(missing)}"
        )

    # Validate type matches
    if frontmatter["type"] != req_type.value:
        raise MarkdownParseError(
            f"Type mismatch: frontmatter type '{frontmatter['type']}' "
            f"does not match expected type '{req_type.value}'"
        )

    # Validate title is not empty
    if not frontmatter["title"] or not frontmatter["title"].strip():
        raise MarkdownParseError("Title cannot be empty")


def _truncate_description(text: str, max_length: int = 500) -> str:
    """Truncate description to max_length at word boundary.

    Args:
        text: The text to truncate
        max_length: Maximum length (default 500)

    Returns:
        Truncated text with ellipsis if needed
    """
    # Normalize whitespace (collapse newlines and multiple spaces to single space)
    text = re.sub(r'\s+', ' ', text.strip())

    if len(text) <= max_length:
        return text

    # Truncate at word boundary
    truncated = text[:max_length].rsplit(' ', 1)[0]
    return truncated + '...'


def extract_metadata(content: str) -> Dict[str, Any]:
    """Extract metadata from markdown content.

    This parses the markdown and returns a dictionary with all metadata
    that can be used to populate database fields.

    Args:
        content: The markdown content to parse

    Returns:
        Dictionary containing: type, title, description, status, tags, parent_id, depends_on, adheres_to

    Raises:
        MarkdownParseError: If content is invalid
    """
    parsed = parse_markdown(content)
    frontmatter = parsed["frontmatter"]
    body = parsed["body"]

    # Determine type
    try:
        req_type = RequirementType(frontmatter["type"])
    except (KeyError, ValueError) as e:
        raise MarkdownParseError(f"Invalid requirement type: {e}")

    # Validate frontmatter
    validate_frontmatter(frontmatter, req_type)

    # Extract description from body (first paragraph or first section)
    # Enforce 500 character limit with intelligent truncation
    description_match = re.search(r'##\s+(?:Vision|Purpose|User Story|Description)\s*\n\n(.+?)(?:\n\n|\n#|$)', body, re.DOTALL)
    raw_description = description_match.group(1).strip() if description_match else body[:500]
    description = _truncate_description(raw_description, max_length=500)

    # Build metadata dictionary
    metadata = {
        "type": req_type,
        "title": frontmatter["title"],
        "description": description,
        "status": frontmatter.get("status", "draft"),
        "tags": frontmatter.get("tags", []),
        "parent_id": frontmatter.get("parent_id"),
        "depends_on": frontmatter.get("depends_on", []),
        "adheres_to": frontmatter.get("adheres_to", []),
    }

    # Convert parent_id string to UUID if present and not null
    if metadata["parent_id"] and metadata["parent_id"] != "null":
        try:
            metadata["parent_id"] = UUID(metadata["parent_id"])
        except ValueError as e:
            raise MarkdownParseError(f"Invalid parent_id UUID: {e}")
    else:
        metadata["parent_id"] = None

    # Convert depends_on strings to UUIDs
    depends_on_uuids = []
    if metadata["depends_on"]:
        if not isinstance(metadata["depends_on"], list):
            raise MarkdownParseError("depends_on must be a list of requirement IDs")
        for dep_id in metadata["depends_on"]:
            try:
                depends_on_uuids.append(UUID(str(dep_id)))
            except (ValueError, AttributeError) as e:
                raise MarkdownParseError(f"Invalid dependency UUID '{dep_id}': {e}")
    metadata["depends_on"] = depends_on_uuids

    # Validate adheres_to is a list (can contain UUIDs or human-readable IDs)
    adheres_to_list = []
    if metadata["adheres_to"]:
        if not isinstance(metadata["adheres_to"], list):
            raise MarkdownParseError("adheres_to must be a list of guardrail identifiers")
        # Keep as strings - can be UUID or human-readable ID (e.g., GUARD-SEC-001)
        adheres_to_list = [str(g) for g in metadata["adheres_to"]]
    metadata["adheres_to"] = adheres_to_list

    return metadata


def strip_system_fields_from_frontmatter(content: str) -> str:
    """Strip system-managed fields from frontmatter before storage.

    System-managed fields (status, id, timestamps, etc.) should only live in
    database columns, not in stored frontmatter. This prevents desync issues
    when database values change but frontmatter stays stale.

    Authored fields that REMAIN in frontmatter:
    - type
    - title
    - parent_id
    - tags
    - depends_on
    - adheres_to

    System-managed fields that are STRIPPED:
    - status (managed via lifecycle state machine)
    - id, human_readable_id (generated by database)
    - created_at, updated_at (managed by database)
    - created_by, updated_by (managed by API)
    - organization_id, project_id (inherited from parent)
    - description (auto-extracted from body)
    - content_length, quality_score (calculated)

    Args:
        content: The markdown content with frontmatter

    Returns:
        Markdown content with system fields removed from frontmatter

    Raises:
        MarkdownParseError: If content cannot be parsed
    """
    parsed = parse_markdown(content)
    frontmatter = parsed["frontmatter"]
    body = parsed["body"]

    # Define authored fields (everything else gets stripped)
    AUTHORED_FIELDS = {
        "type",
        "title",
        "parent_id",
        "tags",
        "depends_on",
        "adheres_to"
    }

    # Keep only authored fields
    cleaned_frontmatter = {
        key: value for key, value in frontmatter.items()
        if key in AUTHORED_FIELDS
    }

    # Convert any enum values to strings for safe YAML serialization
    for key, value in cleaned_frontmatter.items():
        if hasattr(value, 'value'):
            cleaned_frontmatter[key] = value.value

    # Reconstruct markdown with cleaned frontmatter
    frontmatter_yaml = yaml.safe_dump(cleaned_frontmatter, default_flow_style=False, sort_keys=False)
    return f"---\n{frontmatter_yaml}---\n\n{body}"


def inject_database_state(content: str, status: str, human_readable_id: Optional[str] = None) -> str:
    """Inject current database state into frontmatter for retrieval.

    When returning requirements to clients, we need to compose complete frontmatter
    by injecting current database values. This ensures clients always see the
    current authoritative state, not stale values from stored frontmatter.

    Args:
        content: The stored markdown content (with only authored fields)
        status: Current lifecycle status from database
        human_readable_id: Human-readable ID from database (e.g., RAAS-FEAT-042)

    Returns:
        Markdown content with complete frontmatter including current database state

    Raises:
        MarkdownParseError: If content cannot be parsed
    """
    parsed = parse_markdown(content)
    frontmatter = parsed["frontmatter"]
    body = parsed["body"]

    # Inject current database state
    frontmatter["status"] = status
    if human_readable_id:
        frontmatter["human_readable_id"] = human_readable_id

    # Convert any enum values to strings
    for key, value in frontmatter.items():
        if hasattr(value, 'value'):
            frontmatter[key] = value.value

    # Reconstruct markdown with injected state
    frontmatter_yaml = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
    return f"---\n{frontmatter_yaml}---\n\n{body}"


def merge_content(original_content: str, updates: Dict[str, Any]) -> str:
    """Merge updates into existing markdown content.

    This updates the frontmatter fields while preserving the markdown body.

    Args:
        original_content: The original markdown content
        updates: Dictionary of fields to update

    Returns:
        The updated markdown content

    Raises:
        MarkdownParseError: If content cannot be parsed
    """
    parsed = parse_markdown(original_content)
    frontmatter = parsed["frontmatter"]
    body = parsed["body"]

    # Update frontmatter with new values
    for key, value in updates.items():
        if key in ["type", "title", "status", "tags", "parent_id", "depends_on"]:
            if value is not None:
                # Convert UUID to string for YAML
                if isinstance(value, UUID):
                    frontmatter[key] = str(value)
                # Convert list of UUIDs to list of strings
                elif isinstance(value, list) and value and isinstance(value[0], UUID):
                    frontmatter[key] = [str(uuid) for uuid in value]
                # Convert enums to their string values
                elif hasattr(value, 'value'):
                    frontmatter[key] = value.value
                else:
                    frontmatter[key] = value

    # Convert any remaining enum values in frontmatter to strings for safe YAML serialization
    for key, value in frontmatter.items():
        if hasattr(value, 'value'):
            frontmatter[key] = value.value

    # Reconstruct markdown - use safe_dump to avoid Python-specific tags
    frontmatter_yaml = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
    new_content = f"---\n{frontmatter_yaml}---\n\n{body}"

    return new_content
