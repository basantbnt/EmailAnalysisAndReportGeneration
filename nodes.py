from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx

from customer_orchestrator.models import PriorityLabel, RequestKind, WorkflowResponse, WorkflowState


DEFAULT_ID_CARD_SERVICE_URL = "http://127.0.0.1:8000/demo/id-card-change"
DEFAULT_ADDRESS_SERVICE_URL = "http://127.0.0.1:8000/demo/address-change"


def _id_card_service_url(state: WorkflowState) -> str:
    metadata = state.get("metadata", {})
    return str(metadata.get("id_card_service_url") or os.getenv("ID_CARD_SERVICE_URL") or DEFAULT_ID_CARD_SERVICE_URL)


def _address_service_url(state: WorkflowState) -> str:
    metadata = state.get("metadata", {})
    return str(
        metadata.get("address_service_url")
        or os.getenv("ADDRESS_SERVICE_URL")
        or DEFAULT_ADDRESS_SERVICE_URL
    )


def _string_payload(state: WorkflowState) -> str:
    payload = state.get("payload", {})
    raw_email = payload.get("raw_email")
    message = payload.get("message")
    return str(raw_email or message or payload)


def _infer_priority(payload_text: str) -> PriorityLabel:
    lowered = payload_text.lower()
    if any(term in lowered for term in ("urgent", "asap", "immediately", "blocked")):
        return PriorityLabel.HIGH
    if any(term in lowered for term in ("soon", "today", "important")):
        return PriorityLabel.MEDIUM
    return PriorityLabel.LOW


def _infer_sentiment(payload_text: str) -> str:
    lowered = payload_text.lower()
    if any(term in lowered for term in ("angry", "unhappy", "frustrated", "complaint")):
        return "negative"
    if any(term in lowered for term in ("thanks", "great", "happy")):
        return "positive"
    return "neutral"


def _infer_intent(kind: RequestKind, payload: Mapping[str, Any]) -> str:
    if kind == RequestKind.EMAIL_CHANGE:
        return "update_email"
    if kind == RequestKind.ID_CARD_CHANGE:
        return "replace_id_card"
    if kind == RequestKind.ADDRESS_CHANGE:
        return "update_address"
    if payload.get("question"):
        return "customer_enquiry"
    return "general_enquiry"


async def email_agent(state: WorkflowState) -> WorkflowState:
    payload_text = _string_payload(state)
    payload = state.get("payload", {})
    summary = payload.get("summary") or payload_text[:200]
    priority = _infer_priority(payload_text)
    sentiment = _infer_sentiment(payload_text)
    intent = _infer_intent(RequestKind.EMAIL_CHANGE, payload)

    return {
        "summary": summary,
        "priority": priority,
        "sentiment": sentiment,
        "intent": intent,
    }


async def planner_agent(state: WorkflowState) -> WorkflowState:
    kind = state["kind"]
    payload_text = _string_payload(state)
    requires_human = bool(state.get("metadata", {}).get("requires_human"))

    if "manual" in payload_text.lower() or "human" in payload_text.lower():
        requires_human = True

    summary = state.get("summary") or payload_text[:200]
    priority = state.get("priority") or _infer_priority(payload_text)
    sentiment = state.get("sentiment") or _infer_sentiment(payload_text)
    intent = state.get("intent") or _infer_intent(kind, state.get("payload", {}))

    planned_executor = {
        RequestKind.EMAIL_CHANGE: "email_change_executor",
        RequestKind.ID_CARD_CHANGE: "id_card_change_executor",
        RequestKind.ADDRESS_CHANGE: "address_change_executor",
        RequestKind.ENQUIRY: "enquiry_executor",
    }[kind]

    update: WorkflowState = {
        "summary": summary,
        "priority": priority,
        "sentiment": sentiment,
        "intent": intent,
        "planned_executor": planned_executor,
        "requires_human": requires_human,
    }
    if requires_human:
        update["human_reason"] = "Planner flagged this request for manual review."
    return update


async def email_change_executor(state: WorkflowState) -> WorkflowState:
    new_email = state.get("payload", {}).get("new_email") or state.get("payload", {}).get("raw_email")
    return {
        "executor_result": {
            "action": "email_change",
            "target": new_email,
            "system": "email-agent-downstream",
        }
    }


async def id_card_change_executor(state: WorkflowState) -> WorkflowState:
    payload = state.get("payload", {})
    request_body = {
        "request_id": state["request_id"],
        "user_id": state["user_id"],
        "delivery_method": payload.get("delivery_method", "standard"),
        "id_card_number": payload.get("id_card_number"),
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(_id_card_service_url(state), json=request_body)
        response.raise_for_status()
        api_result = response.json()

    return {
        "executor_result": {
            "action": "id_card_change",
            "delivery_method": request_body["delivery_method"],
            "api_result": api_result,
            "system": "id-card-service",
        }
    }


async def address_change_executor(state: WorkflowState) -> WorkflowState:
    payload = state.get("payload", {})
    request_body = {
        "request_id": state["request_id"],
        "user_id": state["user_id"],
        "new_address": payload.get("new_address"),
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(_address_service_url(state), json=request_body)
        response.raise_for_status()
        api_result = response.json()

    return {
        "executor_result": {
            "action": "address_change",
            "new_address": request_body["new_address"],
            "api_result": api_result,
            "system": "address-service",
        }
    }


async def enquiry_executor(state: WorkflowState) -> WorkflowState:
    return {
        "executor_result": {
            "action": "enquiry",
            "answer_stub": "Attach knowledge-base or retrieval pipeline here.",
            "system": "enquiry-service",
        }
    }


async def human_review(state: WorkflowState) -> WorkflowState:
    return {
        "executor_result": {
            "action": "human_review",
            "reason": state.get("human_reason", "Manual review requested."),
            "status": "pending_human",
        }
    }


async def response_agent(state: WorkflowState) -> WorkflowState:
    response = WorkflowResponse(
        request_id=state["request_id"],
        user_id=state["user_id"],
        kind=state["kind"],
        status="human_review" if state.get("requires_human") else "completed",
        planned_executor=state["planned_executor"],
        summary=state["summary"],
        priority=state["priority"],
        sentiment=state["sentiment"],
        intent=state["intent"],
        requires_human=bool(state.get("requires_human")),
        result=state.get("executor_result", {}),
    )
    return {"response": response}
