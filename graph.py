from __future__ import annotations

from langgraph.graph import START, END, StateGraph

from customer_orchestrator.models import RequestKind, WorkflowState
from customer_orchestrator.nodes import (
    email_agent,
    planner_agent,
    email_change_executor,
    id_card_change_executor,
    address_change_executor,
    enquiry_executor,
    human_review,
    response_agent,
)


# ==========================================================
# ENTRY ROUTER
# ==========================================================
def _entry_route(state: WorkflowState) -> str:

    if state["kind"] == RequestKind.EMAIL_CHANGE:
        return "email_endpoint"

    elif state["kind"] == RequestKind.ID_CARD_CHANGE:
        return "id_card_change_endpoint"

    elif state["kind"] == RequestKind.ADDRESS_CHANGE:
        return "address_change_endpoint"

    return "enquiry_endpoint"


# ==========================================================
# PLANNER ROUTER
# ==========================================================
def _planner_route(state: WorkflowState) -> str:

    return state["planned_executor"]


# ==========================================================
# EXECUTOR ROUTER
# ==========================================================
def _executor_route(state: WorkflowState) -> str:

    if state.get("requires_human"):
        return "human_review"

    return "response_agent"


# ==========================================================
# BUILD GRAPH
# ==========================================================
def build_graph():

    graph = StateGraph(WorkflowState)

    # ======================================================
    # Endpoint Nodes
    # ======================================================

    graph.add_node("email_endpoint", lambda state: state)
    graph.add_node("id_card_change_endpoint", lambda state: state)
    graph.add_node("address_change_endpoint", lambda state: state)
    graph.add_node("enquiry_endpoint", lambda state: state)

    # ======================================================
    # Agent Nodes
    # ======================================================

    graph.add_node("email_agent", email_agent)
    graph.add_node("planner_agent", planner_agent)

    # ======================================================
    # Executor Nodes
    # ======================================================

    graph.add_node("email_change_executor", email_change_executor)
    graph.add_node("id_card_change_executor", id_card_change_executor)
    graph.add_node("address_change_executor", address_change_executor)
    graph.add_node("enquiry_executor", enquiry_executor)

    # ======================================================
    # HITL + Response
    # ======================================================

    graph.add_node("human_review", human_review)
    graph.add_node("response_agent", response_agent)

    # ======================================================
    # START -> ENDPOINT ROUTING
    # ======================================================

    graph.add_conditional_edges(
        START,
        _entry_route,
        {
            "email_endpoint": "email_endpoint",
            "id_card_change_endpoint": "id_card_change_endpoint",
            "address_change_endpoint": "address_change_endpoint",
            "enquiry_endpoint": "enquiry_endpoint",
        },
    )

    # ======================================================
    # EMAIL FLOW
    # email_endpoint -> email_agent -> planner_agent
    # ======================================================

    graph.add_edge("email_endpoint", "email_agent")
    graph.add_edge("email_agent", "planner_agent")

    # ======================================================
    # NON EMAIL FLOWS
    # ======================================================

    graph.add_edge("id_card_change_endpoint", "planner_agent")
    graph.add_edge("address_change_endpoint", "planner_agent")
    graph.add_edge("enquiry_endpoint", "planner_agent")

    # ======================================================
    # PLANNER -> EXECUTOR
    # ======================================================

    graph.add_conditional_edges(
        "planner_agent",
        _planner_route,
        {
            "email_change_executor": "email_change_executor",
            "id_card_change_executor": "id_card_change_executor",
            "address_change_executor": "address_change_executor",
            "enquiry_executor": "enquiry_executor",
        },
    )

    # ======================================================
    # EXECUTOR -> HUMAN REVIEW / RESPONSE
    # ======================================================

    executors = [
        "email_change_executor",
        "id_card_change_executor",
        "address_change_executor",
        "enquiry_executor",
    ]

    for executor in executors:

        graph.add_conditional_edges(
            executor,
            _executor_route,
            {
                "human_review": "human_review",
                "response_agent": "response_agent",
            },
        )

    # ======================================================
    # HUMAN REVIEW -> RESPONSE
    # ======================================================

    graph.add_edge("human_review", "response_agent")

    # ======================================================
    # RESPONSE -> END
    # ======================================================

    graph.add_edge("response_agent", END)

    return graph.compile()
