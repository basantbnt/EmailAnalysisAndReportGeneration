from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from customer_orchestrator.concurrency import RequestScheduler
from customer_orchestrator.graph import build_graph
from customer_orchestrator.models import CustomerRequest, RequestKind, WorkflowResponse

app = FastAPI(title="Customer Orchestrator LangGraph", version="0.1.0")

graph = build_graph()


def _parse_request_kind(value: Any) -> RequestKind | None:
    if value is None:
        return None
    if isinstance(value, RequestKind):
        return value
    try:
        return RequestKind(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unsupported request kind: {value}") from exc


def _resolve_request_kind(payload: CustomerRequest) -> RequestKind:
    explicit_kind = (
        payload.metadata.get("kind")
        or payload.metadata.get("request_kind")
        or payload.payload.get("kind")
        or payload.payload.get("request_kind")
    )
    parsed_kind = _parse_request_kind(explicit_kind)
    if parsed_kind is not None:
        return parsed_kind

    if "new_address" in payload.payload:
        return RequestKind.ADDRESS_CHANGE
    
    if any(
        key in payload.payload
        for key in ("delivery_method", "id_card_number", "id_card_details", "id_card_reason")
    ):
        return RequestKind.ID_CARD_CHANGE
    
    return RequestKind.ENQUIRY
    
    raise HTTPException(
        status_code=422,
        detail="Unable to determine request kind. Provide metadata.kind or payload.kind.",
    )


async def _run_graph(kind: RequestKind, payload: CustomerRequest) -> WorkflowResponse:
    state = await graph.ainvoke(
        {
            "request_id": payload.request_id,
            "user_id": payload.user_id,
            "kind": kind,
            "payload": payload.payload,
            "metadata": payload.metadata,
        }
    )
    return state["response"]


scheduler = RequestScheduler(runner=_run_graph)


async def _submit(payload: CustomerRequest) -> WorkflowResponse:
    kind = _resolve_request_kind(payload)
    return await scheduler.submit(kind, payload)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/requests", response_model=WorkflowResponse)
async def submit_request(payload: CustomerRequest) -> WorkflowResponse:
    return await _submit(payload)


@app.post("/requests/email-classifier", response_model=WorkflowResponse)
async def email_classifier(payload: CustomerRequest) -> WorkflowResponse:
    return await _submit(payload)


@app.post("/requests/id-card-change", response_model=WorkflowResponse)
async def id_card_change(payload: CustomerRequest) -> WorkflowResponse:
    return await _submit(payload)


@app.post("/requests/address-change", response_model=WorkflowResponse)
async def address_change(payload: CustomerRequest) -> WorkflowResponse:
    return await _submit(payload)


@app.post("/requests/enquiry", response_model=WorkflowResponse)
async def enquiry(payload: CustomerRequest) -> WorkflowResponse:
    return await _submit(payload)
