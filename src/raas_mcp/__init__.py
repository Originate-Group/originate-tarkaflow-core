"""RaaS MCP Server - Model Context Protocol integration.

This package provides MCP (Model Context Protocol) integration for RaaS,
enabling AI assistants to interact with requirements management.

Modules:
- server: stdio MCP server implementation
- formatters: Response formatting utilities
- tools: MCP tool definitions
- handlers: Tool implementation handlers
"""

__version__ = "1.0.0"

# Export shared modules for use by HTTP MCP implementations
from . import formatters
from . import tools
from . import handlers

__all__ = ["formatters", "tools", "handlers", "__version__"]
