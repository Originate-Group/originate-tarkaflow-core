"""SQLAlchemy database models."""
from datetime import datetime
from typing import Optional
from uuid import uuid4
import enum

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    Enum,
    CheckConstraint,
    ARRAY,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

# Base class for all models
Base = declarative_base()


class RequirementType(str, enum.Enum):
    """Requirement type enum for hierarchy levels."""

    EPIC = "epic"
    COMPONENT = "component"
    FEATURE = "feature"
    REQUIREMENT = "requirement"


class LifecycleStatus(str, enum.Enum):
    """Lifecycle status enum."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    VALIDATED = "validated"
    DEPLOYED = "deployed"


class MemberRole(str, enum.Enum):
    """Organization member role enum."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectVisibility(str, enum.Enum):
    """Project visibility enum."""

    PUBLIC = "public"
    PRIVATE = "private"


class ProjectStatus(str, enum.Enum):
    """Project status enum."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    PLANNING = "planning"
    ON_HOLD = "on_hold"


class ProjectRole(str, enum.Enum):
    """Project member role enum."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class QualityScore(str, enum.Enum):
    """Quality score enum for content length validation."""

    OK = "OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LOW_QUALITY = "LOW_QUALITY"


class Organization(Base):
    """
    Organization model for workspaces/teams.

    Each organization is an isolated workspace with its own requirements.
    """

    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    settings = Column(JSONB, default={})

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    requirements = relationship("Requirement", back_populates="organization", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="valid_slug"),
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}: {self.name}>"


class User(Base):
    """
    User model for authentication via Keycloak.

    Users authenticate via Keycloak SSO. No passwords stored locally.
    External ID links to Keycloak user (sub claim from JWT).
    Users can belong to multiple organizations with different roles.
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id = Column(String(255), nullable=False, unique=True, index=True)  # Keycloak 'sub' claim
    auth_provider = Column(String(50), nullable=False, default="keycloak")       # Future: support multiple providers
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_superuser = Column(Boolean, nullable=False, default=False)

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    created_requirements = relationship(
        "Requirement",
        foreign_keys="Requirement.created_by_user_id",
        back_populates="created_by_user"
    )
    updated_requirements = relationship(
        "Requirement",
        foreign_keys="Requirement.updated_by_user_id",
        back_populates="updated_by_user"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.auth_provider})>"


class OrganizationMember(Base):
    """
    Junction table linking users to organizations with roles.

    Defines what access level a user has within an organization.
    """

    __tablename__ = "organization_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(MemberRole, values_callable=lambda x: [e.value for e in x]), nullable=False, default=MemberRole.MEMBER, index=True)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="memberships")

    # Constraints
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="unique_org_user"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember {self.role.value}>"


class Project(Base):
    """
    Project model for scope boundaries within an organization.

    Projects represent distinct workstreams, products, or initiatives.
    All epics must belong to a project.
    """

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Core fields
    name = Column(String(255), nullable=False)
    slug = Column(String(4), nullable=False)  # 3-4 uppercase alphanumeric chars, unique within org
    description = Column(Text)
    visibility = Column(
        Enum(ProjectVisibility, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProjectVisibility.PUBLIC,
        index=True
    )
    status = Column(
        Enum(ProjectStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        index=True
    )

    # Optional metadata
    value_statement = Column(Text)
    project_type = Column(String(100))
    tags = Column(ARRAY(String), default=[])
    settings = Column(JSONB, default={})

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Relationships
    organization = relationship("Organization", backref="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    requirements = relationship("Requirement", back_populates="project", cascade="all, delete-orphan")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])

    # Constraints
    __table_args__ = (
        CheckConstraint("slug ~ '^[A-Z0-9]{3,4}$'", name="valid_project_slug"),
        UniqueConstraint("organization_id", "slug", name="unique_org_project_slug"),
    )

    def __repr__(self) -> str:
        return f"<Project {self.slug}: {self.name}>"


class ProjectMember(Base):
    """
    Junction table linking users to projects with roles.

    Defines what access level a user has within a project.
    """

    __tablename__ = "project_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        Enum(ProjectRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProjectRole.EDITOR,
        index=True
    )
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="members")
    user = relationship("User", backref="project_memberships")

    # Constraints
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="unique_project_user"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMember {self.role.value}>"


class Requirement(Base):
    """
    Requirement model for all hierarchy levels.

    Uses single-table inheritance with type discriminator.
    """

    __tablename__ = "requirements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    type = Column(Enum(RequirementType, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    parent_id = Column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )

    # Core fields
    title = Column(String(200), nullable=False)
    description = Column(String(500))  # Auto-extracted from content
    content = Column(Text)  # Full markdown content with frontmatter
    human_readable_id = Column(String(20), unique=True, nullable=True, index=True)  # e.g., RAAS-FEAT-042
    status = Column(
        Enum(LifecycleStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, default=LifecycleStatus.DRAFT, index=True
    )

    # Metadata
    tags = Column(ARRAY(String), default=[])

    # Quality tracking
    content_length = Column(Integer, nullable=False, default=0)
    quality_score = Column(
        Enum(QualityScore, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=QualityScore.OK,
        index=True
    )

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Relationships
    parent = relationship("Requirement", remote_side=[id], backref="children")
    history = relationship("RequirementHistory", back_populates="requirement", cascade="all, delete-orphan")
    organization = relationship("Organization", back_populates="requirements")
    project = relationship("Project", back_populates="requirements")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_requirements")
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id], back_populates="updated_requirements")

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "(type = 'epic' AND parent_id IS NULL AND project_id IS NOT NULL) OR "
            "(type != 'epic' AND parent_id IS NOT NULL AND project_id IS NOT NULL)",
            name="valid_parent_and_project",
        ),
    )

    @property
    def child_count(self) -> int:
        """Count the number of direct children."""
        return len(self.children) if self.children else 0

    def __repr__(self) -> str:
        return f"<Requirement {self.type.value}: {self.title}>"


class ChangeType(str, enum.Enum):
    """Change type enum for history tracking."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    STATUS_CHANGED = "status_changed"


class RequirementHistory(Base):
    """Audit trail for requirement changes."""

    __tablename__ = "requirement_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    requirement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    change_type = Column(Enum(ChangeType, values_callable=lambda x: [e.value for e in x]), nullable=False)

    # What changed
    field_name = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)

    # Who and when
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Context
    change_reason = Column(Text)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    # Relationships
    requirement = relationship("Requirement", back_populates="history")
    changed_by_user = relationship("User")
    organization = relationship("Organization")

    def __repr__(self) -> str:
        return f"<RequirementHistory {self.change_type.value} at {self.changed_at}>"


class PersonalAccessToken(Base):
    """
    Personal Access Token for API/MCP authentication.

    Allows users to authenticate MCP clients and scripts without using
    session cookies. Tokens are hashed before storage (like passwords).
    """

    __tablename__ = "personal_access_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # User-friendly name like "Claude Desktop - Laptop"
    token_hash = Column(String(255), nullable=False, unique=True, index=True)  # SHA-256 hash of token
    scopes = Column(ARRAY(String), default=[])  # Future: scope-based access control
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)  # Soft delete via revocation

    # Relationships
    user = relationship("User", backref="access_tokens")

    @property
    def is_active(self) -> bool:
        """Check if token is active (not revoked and not expired)."""
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def __repr__(self) -> str:
        return f"<PersonalAccessToken {self.name} for user_id={self.user_id}>"


class IDSequence(Base):
    """
    Tracks next available number for human-readable IDs per project+type.

    Used by database trigger to generate sequential IDs like RAAS-FEAT-042.
    """

    __tablename__ = "id_sequences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    requirement_type = Column(String(20), nullable=False)
    next_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project")

    # Constraints
    __table_args__ = (
        UniqueConstraint("project_id", "requirement_type", name="unique_project_type"),
        CheckConstraint("next_number > 0", name="chk_next_number_positive"),
    )

    def __repr__(self) -> str:
        return f"<IDSequence {self.project_id}:{self.requirement_type} next={self.next_number}>"
