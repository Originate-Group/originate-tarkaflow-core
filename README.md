# RaaS Core

Shared requirements management engine used by all RaaS deployments.

## Overview

RaaS Core provides the foundational components for AI-native requirements management:

- **Database Models**: SQLAlchemy models for Users, Organizations, Projects, and Requirements
- **CRUD Operations**: Complete data access layer for all entities
- **Markdown Utilities**: YAML frontmatter parsing and requirement template system
- **4-Level Hierarchy**: Epic → Component → Feature → Requirement structure
- **MCP Server**: Model Context Protocol integration for AI assistants

## For End Users

**Don't use this package directly.** Instead, use one of the deployment repositories:

- **[raas-solo](https://github.com/Originate-Group/originate-raas-solo)** - For solo developers (zero auth, 5-minute setup)
- **[raas-teams](https://github.com/Originate-Group/originate-raas-teams)** - For self-hosted teams (simple auth, 15-minute setup)

## For Contributors

### Installation

```bash
# Clone with git
git clone https://github.com/Originate-Group/originate-raas-core.git
cd raas-core

# Install dependencies
pip install -e .

# Install with MCP support
pip install -e ".[mcp]"
```

### Package Structure

```
src/
├── raas_core/
│   ├── models.py           # SQLAlchemy models
│   ├── crud.py             # CRUD operations
│   ├── schemas.py          # Pydantic schemas
│   ├── markdown_utils.py   # Markdown/YAML parsing
│   └── database.py         # Database connection
└── raas_mcp/
    └── server.py           # MCP protocol server
```

### Usage in Deployment Repos

RaaS Core is typically used as a git submodule or PyPI dependency:

```python
from raas_core import (
    create_requirement,
    get_requirement,
    RequirementCreate,
    RequirementResponse,
)
```

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
