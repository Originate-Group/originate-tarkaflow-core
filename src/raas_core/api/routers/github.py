"""GitHub Integration API router (CR-010: RAAS-COMP-051).

Endpoints for:
- RAAS-FEAT-043: GitHub Repository Configuration
- RAAS-FEAT-044: Work Item to GitHub Issue Sync
- RAAS-FEAT-045: GitHub Webhook Event Handling
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.orm import Session

from ...models import (
    GitHubConfiguration,
    GitHubAuthType,
    WorkItem,
    Project,
    User,
)
from ...schemas import (
    GitHubConfigurationCreate,
    GitHubConfigurationUpdate,
    GitHubConfigurationResponse,
    GitHubWebhookPayload,
    GitHubIssueSyncRequest,
    GitHubIssueSyncResponse,
)
from ...github_integration import (
    GitHubClient,
    GitHubWebhookHandler,
    encrypt_credentials,
    decrypt_credentials,
    generate_webhook_secret,
    verify_webhook_signature,
)
from ..database import get_db
from ..dependencies import get_current_user_optional
from .work_items import resolve_work_item_id

logger = logging.getLogger("raas-core.github_api")

router = APIRouter(prefix="/github", tags=["github"])


def config_to_response(config: GitHubConfiguration) -> GitHubConfigurationResponse:
    """Convert GitHubConfiguration model to response schema."""
    return GitHubConfigurationResponse(
        id=config.id,
        project_id=config.project_id,
        repository_owner=config.repository_owner,
        repository_name=config.repository_name,
        full_repo_name=config.full_repo_name,
        auth_type=config.auth_type,
        has_credentials=config.encrypted_credentials is not None,
        webhook_configured=config.webhook_id is not None,
        label_mapping=config.label_mapping or {},
        auto_create_issues=config.auto_create_issues,
        sync_pr_status=config.sync_pr_status,
        sync_releases=config.sync_releases,
        is_active=config.is_active,
        last_sync_at=config.last_sync_at,
        last_error=config.last_error,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# =============================================================================
# Configuration Endpoints (RAAS-FEAT-043)
# =============================================================================


@router.post("/configurations", response_model=GitHubConfigurationResponse, status_code=status.HTTP_201_CREATED)
async def create_configuration(
    data: GitHubConfigurationCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Create a GitHub configuration for a project.

    Connects a RaaS project to a GitHub repository for Work Item sync.
    Credentials are encrypted before storage.
    """
    # Check project exists
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {data.project_id}"
        )

    # Check no existing config
    existing = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == data.project_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"GitHub configuration already exists for project {data.project_id}"
        )

    # Encrypt credentials
    encrypted_creds = encrypt_credentials(data.credentials)

    # Create configuration
    config = GitHubConfiguration(
        project_id=data.project_id,
        repository_owner=data.repository_owner,
        repository_name=data.repository_name,
        auth_type=data.auth_type,
        encrypted_credentials=encrypted_creds,
        label_mapping=data.label_mapping or {
            "ir": "raas:implementation-request",
            "cr": "raas:change-request",
            "bug": "raas:bug",
            "task": "raas:task",
        },
        auto_create_issues=data.auto_create_issues,
        sync_pr_status=data.sync_pr_status,
        sync_releases=data.sync_releases,
        created_by_user_id=current_user.id,
    )

    db.add(config)
    db.commit()
    db.refresh(config)

    logger.info(f"Created GitHub config for project {data.project_id}: {config.full_repo_name}")
    return config_to_response(config)


@router.get("/configurations/{project_id}", response_model=GitHubConfigurationResponse)
async def get_configuration(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get GitHub configuration for a project."""
    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == project_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GitHub configuration for project {project_id}"
        )

    return config_to_response(config)


@router.patch("/configurations/{project_id}", response_model=GitHubConfigurationResponse)
async def update_configuration(
    project_id: UUID,
    data: GitHubConfigurationUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Update GitHub configuration for a project."""
    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == project_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GitHub configuration for project {project_id}"
        )

    # Update fields
    if data.repository_owner is not None:
        config.repository_owner = data.repository_owner
    if data.repository_name is not None:
        config.repository_name = data.repository_name
    if data.credentials is not None:
        config.encrypted_credentials = encrypt_credentials(data.credentials)
    if data.label_mapping is not None:
        config.label_mapping = data.label_mapping
    if data.auto_create_issues is not None:
        config.auto_create_issues = data.auto_create_issues
    if data.sync_pr_status is not None:
        config.sync_pr_status = data.sync_pr_status
    if data.sync_releases is not None:
        config.sync_releases = data.sync_releases
    if data.is_active is not None:
        config.is_active = data.is_active

    config.updated_at = datetime.utcnow()
    config.last_error = None  # Clear any previous errors

    db.commit()
    db.refresh(config)

    logger.info(f"Updated GitHub config for project {project_id}")
    return config_to_response(config)


@router.delete("/configurations/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_configuration(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Delete GitHub configuration for a project."""
    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == project_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GitHub configuration for project {project_id}"
        )

    # Try to delete webhook if configured
    if config.webhook_id:
        try:
            client = GitHubClient(config)
            await client.delete_webhook(config.webhook_id)
        except Exception as e:
            logger.warning(f"Could not delete webhook: {e}")

    db.delete(config)
    db.commit()

    logger.info(f"Deleted GitHub config for project {project_id}")


@router.post("/configurations/{project_id}/verify", response_model=dict)
async def verify_configuration(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Verify GitHub credentials can access the repository."""
    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == project_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GitHub configuration for project {project_id}"
        )

    client = GitHubClient(config)
    try:
        is_valid = await client.verify_token()
        config.last_error = None if is_valid else "Token verification failed"
        config.updated_at = datetime.utcnow()
        db.commit()

        return {
            "valid": is_valid,
            "repository": config.full_repo_name,
        }
    except Exception as e:
        config.last_error = str(e)
        config.updated_at = datetime.utcnow()
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Verification failed: {e}"
        )


@router.post("/configurations/{project_id}/webhook", response_model=dict)
async def setup_webhook(
    project_id: UUID,
    webhook_url: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Set up a GitHub webhook for the repository.

    The webhook_url should be the public URL for the RaaS webhook endpoint.
    E.g., https://raas.example.com/api/v1/github/webhook
    """
    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == project_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No GitHub configuration for project {project_id}"
        )

    # Generate webhook secret
    secret = generate_webhook_secret()

    client = GitHubClient(config)
    try:
        webhook_data = await client.create_webhook(webhook_url, secret)

        # Store webhook info
        config.webhook_id = str(webhook_data["id"])
        config.webhook_secret_encrypted = encrypt_credentials(secret)
        config.updated_at = datetime.utcnow()
        config.last_error = None
        db.commit()

        return {
            "webhook_id": config.webhook_id,
            "webhook_url": webhook_url,
            "events": ["issues", "pull_request", "release"],
        }
    except Exception as e:
        config.last_error = str(e)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook setup failed: {e}"
        )


# =============================================================================
# Issue Sync Endpoints (RAAS-FEAT-044)
# =============================================================================


@router.post("/sync-issue", response_model=GitHubIssueSyncResponse)
async def sync_work_item_to_issue(
    data: GitHubIssueSyncRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Sync a Work Item to a GitHub Issue.

    Creates a new issue if none exists, or updates existing.
    """
    # Find work item
    work_item = resolve_work_item_id(db, data.work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {data.work_item_id}"
        )

    # Get GitHub config for work item's project
    if not work_item.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Work Item must have a project to sync to GitHub"
        )

    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.project_id == work_item.project_id,
        GitHubConfiguration.is_active == True,
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active GitHub configuration for project {work_item.project_id}"
        )

    # Get affected requirement HRIDs
    affected_hrids = []
    db.refresh(work_item, ["affected_requirements"])
    for req in work_item.affected_requirements:
        if req.human_readable_id:
            affected_hrids.append(req.human_readable_id)

    client = GitHubClient(config)

    # Check if issue already exists
    refs = work_item.implementation_refs or {}
    existing_issue_number = refs.get("github_issue_number")

    try:
        if existing_issue_number:
            # Update existing issue
            issue_data = await client.get_issue(existing_issue_number)
            action = "linked"  # Already exists
        else:
            # Create new issue
            issue_data = await client.create_issue(work_item, affected_hrids)
            action = "created"

            # Store issue reference
            refs["github_issue_url"] = issue_data["html_url"]
            refs["github_issue_number"] = issue_data["number"]
            work_item.implementation_refs = refs
            work_item.updated_at = datetime.utcnow()

        config.last_sync_at = datetime.utcnow()
        config.last_error = None
        db.commit()

        return GitHubIssueSyncResponse(
            work_item_id=work_item.id,
            work_item_hrid=work_item.human_readable_id,
            github_issue_url=issue_data["html_url"],
            github_issue_number=issue_data["number"],
            action=action,
        )

    except Exception as e:
        config.last_error = str(e)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"GitHub sync failed: {e}"
        )


# =============================================================================
# Webhook Endpoint (RAAS-FEAT-045)
# =============================================================================


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def handle_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
):
    """Handle incoming GitHub webhook events.

    Supports:
    - Issue events (closed, reopened)
    - Pull request events (merged)
    - Release events (published)
    """
    # Get raw body for signature verification
    body = await request.body()

    # Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    # Get repository info to find config
    repository = payload.get("repository", {})
    repo_owner = repository.get("owner", {}).get("login")
    repo_name = repository.get("name")

    if not repo_owner or not repo_name:
        logger.warning("Webhook received without repository info")
        return {"status": "ignored", "reason": "no_repository"}

    # Find matching config
    config = db.query(GitHubConfiguration).filter(
        GitHubConfiguration.repository_owner == repo_owner,
        GitHubConfiguration.repository_name == repo_name,
        GitHubConfiguration.is_active == True,
    ).first()

    if not config:
        logger.debug(f"No config for {repo_owner}/{repo_name}")
        return {"status": "ignored", "reason": "no_config"}

    # Verify signature if webhook secret is configured
    if config.webhook_secret_encrypted and x_hub_signature_256:
        secret = decrypt_credentials(config.webhook_secret_encrypted)
        if not verify_webhook_signature(body, x_hub_signature_256, secret):
            logger.warning(f"Invalid webhook signature for {repo_owner}/{repo_name}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

    # Handle event
    handler = GitHubWebhookHandler(db)
    action = payload.get("action")
    result = None

    if x_github_event == "issues":
        issue = payload.get("issue", {})
        result = await handler.handle_issue_event(action, issue, repository)

    elif x_github_event == "pull_request":
        pr = payload.get("pull_request", {})
        result = await handler.handle_pull_request_event(action, pr, repository)

    elif x_github_event == "release":
        release = payload.get("release", {})
        result = await handler.handle_release_event(action, release, repository)

    elif x_github_event == "ping":
        # GitHub sends ping to verify webhook
        return {"status": "pong", "zen": payload.get("zen")}

    config.last_sync_at = datetime.utcnow()
    db.commit()

    return {
        "status": "processed",
        "event": x_github_event,
        "action": action,
        "result": result,
    }
