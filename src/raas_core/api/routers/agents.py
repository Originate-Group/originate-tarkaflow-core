"""Agents API endpoints for agent-director authorization (CR-012)."""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from raas_core import crud, schemas, models

from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.agents")

router = APIRouter(tags=["agents"])


@router.get("/my-agents", response_model=schemas.MyAgentsResponse)
def list_my_agents(
    organization_id: UUID = Query(..., description="Organization UUID"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List agents the current user can direct in an organization.

    For org owners: returns all agents with is_authorized=True
    For other users: returns all agents with is_authorized based on explicit mappings

    This endpoint is used by MCP tools to discover available agents.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Verify user is a member of the organization
    role = crud.get_user_org_role(db, current_user.id, organization_id)
    if not role:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "You are not a member of this organization",
            }
        )

    # Get agents with authorization info
    agents = crud.get_agents_for_director(db, current_user.id, organization_id)

    return schemas.MyAgentsResponse(
        agents=[schemas.AgentResponse(**a) for a in agents],
        organization_id=organization_id,
        director_id=current_user.id,
        director_email=current_user.email,
    )


@router.get("/check-authorization")
def check_agent_authorization(
    agent_email: str = Query(..., description="Agent email to check"),
    organization_id: UUID = Query(..., description="Organization UUID"),
    user_agent: Optional[str] = Query(None, description="User-Agent header for client constraint checking"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Check if current user is authorized to direct a specific agent.

    Used by MCP select_agent() to validate authorization before setting the agent.

    CR-005/TARKA-FEAT-105: Supports client constraints via user_agent parameter.
    If the agent-director mapping has allowed_user_agents and the provided
    user_agent doesn't match, authorization is denied.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Verify user is a member of the organization
    role = crud.get_user_org_role(db, current_user.id, organization_id)
    if not role:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "You are not a member of this organization",
            }
        )

    # Check authorization (CR-005: now includes client constraint checking)
    is_authorized, auth_type, allowed_user_agents = crud.check_agent_director_authorization(
        db, current_user.id, agent_email, organization_id, user_agent=user_agent
    )

    if not is_authorized:
        # Get agent info for better error message
        agent = crud.get_agent_by_email(db, agent_email)
        if not agent:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "agent_not_found",
                    "message": f"Agent '{agent_email}' not found",
                }
            )

        # CR-005: Check if this is a client constraint rejection
        if auth_type == "client_rejected":
            patterns_str = ", ".join(allowed_user_agents) if allowed_user_agents else "none"
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "client_not_allowed",
                    "message": f"Your client '{user_agent}' is not allowed to use agent '{agent_email}'. "
                               f"Allowed clients: {patterns_str}",
                    "agent_email": agent_email,
                    "director_email": current_user.email,
                    "client": user_agent,
                    "allowed_user_agents": allowed_user_agents,
                    "organization_id": str(organization_id),
                }
            )

        raise HTTPException(
            status_code=403,
            detail={
                "error": "agent_not_authorized",
                "message": f"You are not authorized to act as agent '{agent_email}' in this organization. "
                           f"Contact an organization owner to create an agent-director mapping.",
                "agent_email": agent_email,
                "organization_id": str(organization_id),
            }
        )

    return {
        "authorized": True,
        "authorization_type": auth_type,
        "agent_email": agent_email,
        "director_id": str(current_user.id),
        "director_email": current_user.email,
        "organization_id": str(organization_id),
        "allowed_user_agents": allowed_user_agents,
    }


@router.get("/", response_model=list[schemas.AgentResponse])
def list_agents(
    organization_id: UUID = Query(..., description="Organization UUID"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List all available agent accounts with authorization status.

    Returns all agent accounts in the system with is_authorized field
    indicating whether the current user can direct each agent.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Verify user is a member of the organization
    role = crud.get_user_org_role(db, current_user.id, organization_id)
    if not role:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "You are not a member of this organization",
            }
        )

    # Get agents with authorization info
    agents = crud.get_agents_for_director(db, current_user.id, organization_id)

    return [schemas.AgentResponse(**a) for a in agents]


# Admin endpoints for managing agent-director mappings

@router.post("/directors", response_model=schemas.AgentDirectorResponse)
def create_agent_director_mapping(
    data: schemas.AgentDirectorCreate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Create an agent-director authorization mapping.

    Only organization owners and admins can create mappings.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if user is org owner or admin
    role = crud.get_user_org_role(db, current_user.id, data.organization_id)
    if role not in [models.MemberRole.OWNER, models.MemberRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "Only organization owners and admins can manage agent-director mappings",
            }
        )

    try:
        mapping = crud.create_agent_director_mapping(
            db=db,
            agent_id=data.agent_id,
            director_id=data.director_id,
            organization_id=data.organization_id,
            created_by=current_user.id,
            allowed_user_agents=data.allowed_user_agents,  # CR-005
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fetch related objects for response
    agent = db.query(models.User).filter(models.User.id == mapping.agent_id).first()
    director = db.query(models.User).filter(models.User.id == mapping.director_id).first()
    creator = db.query(models.User).filter(models.User.id == mapping.created_by).first() if mapping.created_by else None

    return schemas.AgentDirectorResponse(
        id=mapping.id,
        agent_id=mapping.agent_id,
        agent_email=agent.email if agent else "unknown",
        agent_name=agent.full_name if agent else None,
        director_id=mapping.director_id,
        director_email=director.email if director else "unknown",
        director_name=director.full_name if director else None,
        organization_id=mapping.organization_id,
        created_at=mapping.created_at,
        created_by_email=creator.email if creator else None,
        allowed_user_agents=mapping.allowed_user_agents,  # CR-005
    )


@router.get("/directors", response_model=list[schemas.AgentDirectorResponse])
def list_agent_director_mappings(
    organization_id: UUID = Query(..., description="Organization UUID"),
    agent_id: Optional[UUID] = Query(None, description="Filter by agent"),
    director_id: Optional[UUID] = Query(None, description="Filter by director"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List agent-director mappings for an organization.

    Only organization owners and admins can view mappings.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if user is org owner or admin
    role = crud.get_user_org_role(db, current_user.id, organization_id)
    if role not in [models.MemberRole.OWNER, models.MemberRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "Only organization owners and admins can view agent-director mappings",
            }
        )

    mappings = crud.list_agent_director_mappings(
        db=db,
        organization_id=organization_id,
        agent_id=agent_id,
        director_id=director_id,
    )

    result = []
    for mapping in mappings:
        agent = db.query(models.User).filter(models.User.id == mapping.agent_id).first()
        director = db.query(models.User).filter(models.User.id == mapping.director_id).first()
        creator = db.query(models.User).filter(models.User.id == mapping.created_by).first() if mapping.created_by else None

        result.append(schemas.AgentDirectorResponse(
            id=mapping.id,
            agent_id=mapping.agent_id,
            agent_email=agent.email if agent else "unknown",
            agent_name=agent.full_name if agent else None,
            director_id=mapping.director_id,
            director_email=director.email if director else "unknown",
            director_name=director.full_name if director else None,
            organization_id=mapping.organization_id,
            created_at=mapping.created_at,
            created_by_email=creator.email if creator else None,
            allowed_user_agents=mapping.allowed_user_agents,  # CR-005
        ))

    return result


@router.delete("/directors/{agent_id}/{director_id}")
def delete_agent_director_mapping(
    agent_id: UUID,
    director_id: UUID,
    organization_id: UUID = Query(..., description="Organization UUID"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Delete an agent-director authorization mapping.

    Only organization owners and admins can delete mappings.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if user is org owner or admin
    role = crud.get_user_org_role(db, current_user.id, organization_id)
    if role not in [models.MemberRole.OWNER, models.MemberRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "message": "Only organization owners and admins can delete agent-director mappings",
            }
        )

    deleted = crud.delete_agent_director_mapping(
        db=db,
        agent_id=agent_id,
        director_id=director_id,
        organization_id=organization_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Agent-director mapping not found",
        )

    return {"message": "Agent-director mapping deleted"}
