"""Vertical assistants: a supervisor routes each message to an HR, Healthcare or
Finance agent, each with its own tools, prompt and guardrails.

safety_check -> supervisor -> hr | healthcare | finance | unknown -> compliance
             +-> emergency ---------------------------------------> compliance
"""
import re
from datetime import date
from typing import Annotated, Literal, Optional, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from config import get_llm
from finance_tools import FINANCE_TOOLS
from health_tools import HEALTH_TOOLS
from hr_tools import HR_TOOLS

TODAY = f"Today is {date.today():%A, %d %B %Y} ({date.today().isoformat()})."
DOMAINS = ("hr", "healthcare", "finance")

EMERGENCY_RE = re.compile(
    r"chest pain|can'?t breathe|difficulty breathing|unconscious|severe bleeding|stroke|"
    r"heart attack|suicid|kill myself|overdose", re.I)
KEYWORDS = {
    "hr": r"leave|holiday|vacation|policy|wfh|work from home|expense|reimburse|notice period|employee|E1\d\d|manager|parental",
    "healthcare": r"doctor|appointment|clinic|symptom|cardio|derma|ortho|pediatric|physician|fever|pain|book",
    "finance": r"account|balance|transaction|spend|spent|credit card|ACC-\d+|salary|bank|statement",
}
DISCLAIMERS = {
    "healthcare": "\n\nNote: I can help with appointments and general information, not diagnosis "
                  "or treatment. For urgent symptoms call 112 or go to the nearest emergency room.",
    "finance": "\n\nNote: This is account information only, not personalised financial or investment advice.",
}

PROMPTS = {
    "hr": f"""You are the HR assistant for Acme Corp employees. {TODAY}
- Identify the employee by employee code (E101-E105). Ask for it if needed.
- Answer policy questions only from search_hr_policy results.
- Before submitting leave, confirm dates and reason with the employee; use YYYY-MM-DD dates.
- Never reveal another employee's details unless the user gives that employee code.
Keep answers short and clear.""",
    "healthcare": f"""You are the patient services assistant for CityCare Clinic. {TODAY}
- Help patients find doctors, check availability, and book, list or cancel appointments.
- To book you need: patient name, email, doctor, date (YYYY-MM-DD), slot time and reason.
  Check availability first and confirm details before booking.
- Do NOT diagnose, interpret symptoms or recommend medication. You may suggest which
  specialty usually handles a concern (e.g. skin -> Dermatologist).
Keep answers short and kind.""",
    "finance": f"""You are the banking assistant for ShopEase Pay. {TODAY}
- You can show balances, recent transactions and spending by category.
- Every tool needs the account number (e.g. ACC-5001) and the account email; ask for both.
- You are read-only: you cannot move money, open accounts or change limits.
- Do not give investment, tax or loan advice.
Keep answers short and precise with amounts in Rs.""",
}

AGENTS = {
    "hr": create_agent(get_llm(), HR_TOOLS, system_prompt=PROMPTS["hr"]),
    "healthcare": create_agent(get_llm(), HEALTH_TOOLS, system_prompt=PROMPTS["healthcare"]),
    "finance": create_agent(get_llm(), FINANCE_TOOLS, system_prompt=PROMPTS["finance"]),
}


class Route(BaseModel):
    domain: Literal["hr", "healthcare", "finance", "unknown"]


class VState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    domain: Optional[str]     # persists across turns via the checkpointer
    draft: str


def latest_user_text(state: VState) -> str:
    return next(m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage))


def safety_check(state: VState) -> dict:
    if EMERGENCY_RE.search(latest_user_text(state)):
        return {"domain": "emergency"}
    return {}


def supervisor(state: VState) -> dict:
    text, previous = latest_user_text(state), state.get("domain")
    prompt = (
        "Route the user's message to one assistant:\n"
        "hr = employee questions: leave, HR policies, work from home, expenses, notice period\n"
        "healthcare = doctors, clinic appointments, which specialist to see\n"
        "finance = bank accounts, balances, transactions, spending\n"
        "unknown = anything else\n"
        f"The previous message was handled by: {previous or 'nobody'}. Short follow-ups "
        "like 'yes', 'book it' or 'what about last month' belong to that same assistant.\n\n"
        f"Message: {text}"
    )
    try:
        domain = get_llm().with_structured_output(Route).invoke(prompt).domain
    except Exception:
        domain = next((d for d, pattern in KEYWORDS.items() if re.search(pattern, text, re.I)), "unknown")
    if domain == "unknown" and previous in DOMAINS and len(text.split()) <= 6:
        domain = previous
    return {"domain": domain}


def make_domain_node(domain: str):
    def node(state: VState) -> dict:
        result = AGENTS[domain].invoke({"messages": state["messages"]})
        return {"draft": result["messages"][-1].content}
    return node


def emergency(state: VState) -> dict:
    return {"draft": "This sounds like it could be a medical emergency. Please call 112 (India "
                     "emergency number) or go to the nearest emergency room right now. Do not "
                     "wait for an appointment."}


def unknown(state: VState) -> dict:
    return {"draft": "I can help with HR (leave, policies), Healthcare (doctors and appointments) "
                     "or Finance (balances, transactions, spending). What do you need?"}


def compliance(state: VState) -> dict:
    """Deterministic post-processing: domain disclaimers are added by code, not by the LLM."""
    text = state["draft"] + DISCLAIMERS.get(state.get("domain"), "")
    return {"messages": [AIMessage(text)]}


builder = StateGraph(VState)
builder.add_node("safety_check", safety_check)
builder.add_node("supervisor", supervisor)
for d in DOMAINS:
    builder.add_node(d, make_domain_node(d))
builder.add_node("emergency", emergency)
builder.add_node("unknown", unknown)
builder.add_node("compliance", compliance)

builder.add_edge(START, "safety_check")
builder.add_conditional_edges("safety_check",
                              lambda s: "emergency" if s.get("domain") == "emergency" else "supervisor",
                              ["emergency", "supervisor"])
builder.add_conditional_edges("supervisor", lambda s: s["domain"], [*DOMAINS, "unknown"])
for node in (*DOMAINS, "emergency", "unknown"):
    builder.add_edge(node, "compliance")
builder.add_edge("compliance", END)

graph = builder.compile(checkpointer=InMemorySaver())
