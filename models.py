from __future__ import annotations

from enum import Enum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class RequestKind(str, Enum):
    EMAIL_CHANGE = "email_change"
    ID_CARD_CHANGE = "id_card_change"
    ADDRESS_CHANGE = "address_change"
    ENQUIRY = "enquiry"


class PriorityLabel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CustomerRequest(BaseModel):
    request_id: str = Field(..., description="Unique request identifier.")
    user_id: str = Field(..., description="Customer identifier used for user-scoped scheduling.")
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    request_id: str
    user_id: str
    kind: RequestKind
    status: Literal["completed", "human_review"]
    planned_executor: str
    summary: str
    priority: PriorityLabel
    sentiment: str
    intent: str
    requires_human: bool
    result: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(TypedDict, total=False):
    request_id: str
    user_id: str
    kind: RequestKind
    payload: dict[str, Any]
    metadata: dict[str, Any]
    summary: str
    priority: PriorityLabel
    sentiment: str
    intent: str
    requires_human: bool
    human_reason: str
    planned_executor: str
    executor_result: dict[str, Any]
    response: WorkflowResponse
