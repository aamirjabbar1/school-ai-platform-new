"""
The AI management assistant (ERP phase 8, specification §66).

"How many students are absent today?" — answered from the school's real data,
through tools, never through generated SQL.

The safety model is different from the curriculum chatbot's, and deliberately
so. That one is constrained by *what it may talk about*; this one is
constrained by *what it may look at*:

  * The model chooses which prepared question to ask and with what arguments.
    It cannot compose a query. A model able to write SQL against a school's
    payroll is a model able to write the wrong one.
  * It is offered only the tools the asking user already has permission for, so
    a coordinator asking about salaries is not refused — the question simply
    was not available to ask.
  * Every figure comes back with what it is as at, and the answer says so,
    because "how much did we collect today" means something different at 9am.
"""
from __future__ import annotations

import json
import logging
import time

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import User
from services.erp import insights

logger = logging.getLogger("agent")

MAX_ROUNDS = 4          # ask, look, ask again, answer. More is a loop, not thought.


SYSTEM = """You are the management assistant for {school}'s school ERP.

You answer questions about this school using the tools provided. Rules:

- Use a tool for anything factual. Never guess a number, and never state a
  figure the tools did not give you.
- If no tool can answer, say plainly what you cannot see and suggest where in
  the ERP the person would find it.
- Give the figure first, in one short sentence, then any detail worth having.
  The person asking is usually busy and often on a phone.
- Say what the figure is as at when the tool tells you ("as at today", "as at
  9 September").
- Amounts are Pakistani rupees. Write them as "Rs 12,500".
- Never speculate about individuals, and never repeat a student's or an
  employee's personal details beyond what was asked.
- If a tool returns nothing, say so — an empty defaulter list is good news and
  should be reported as good news, not as a failure.

You are talking to {name}, whose role here is {role}."""


def _tool_schema(names: list[str]) -> list[dict]:
    """Anthropic tool definitions for the questions this user may ask."""
    schemas = []
    for name in names:
        spec = insights.TOOLS[name]
        properties = {}
        if name == "attendance_today":
            properties["on_date"] = {
                "type": "string",
                "description": "Date as YYYY-MM-DD. Omit for today.",
            }
        if name == "defaulter_list":
            properties["limit"] = {
                "type": "integer",
                "description": "How many students to list. Default 20.",
            }
        schemas.append({
            "name": name,
            "description": spec["description"],
            "input_schema": {"type": "object", "properties": properties, "required": []},
        })
    return schemas


async def _run_tool(db: AsyncSession, name: str, arguments: dict) -> dict:
    spec = insights.TOOLS.get(name)
    if spec is None:
        return {"error": "That question is not available."}

    kwargs = {}
    if name == "attendance_today" and arguments.get("on_date"):
        from datetime import date
        try:
            kwargs["on_date"] = date.fromisoformat(arguments["on_date"])
        except ValueError:
            return {"error": f"{arguments['on_date']} is not a date I understand."}
    if name == "defaulter_list" and arguments.get("limit"):
        kwargs["limit"] = min(int(arguments["limit"]), 50)

    try:
        return await spec["fn"](db, **kwargs)
    except Exception as exc:                       # noqa: BLE001 — reported, not raised
        logger.warning("Assistant tool %s failed: %s", name, exc)
        return {"error": "That information could not be read just now."}


async def ask(
    db: AsyncSession, *, question: str, user: User, held: set[str],
) -> dict:
    """Answer a management question. Returns the answer and what was consulted."""
    from config.settings import ANTHROPIC_API_KEY, AI_MODEL, SCHOOL_NAME
    from services.ai_service import get_async_client

    available = insights.tools_for(held)
    if not available:
        return {
            "answer": "You do not have access to any of the school's reports, "
                      "so there is nothing I can look up for you.",
            "used": [],
        }

    if not ANTHROPIC_API_KEY:
        return {"answer": "The assistant is not configured yet.", "used": []}

    client = get_async_client()
    system = SYSTEM.format(school=SCHOOL_NAME, name=user.name, role=user.role)
    tools = _tool_schema(available)
    messages: list[dict] = [{"role": "user", "content": question}]
    used: list[str] = []
    started = time.monotonic()
    input_tokens = output_tokens = 0

    for _ in range(MAX_ROUNDS):
        response = await client.messages.create(
            model=AI_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=messages,
        )
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            answer = "".join(
                block.text for block in response.content if block.type == "text"
            ).strip()
            return {
                "answer": answer or "I could not work that out.",
                "used": used,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        messages.append({"role": "assistant", "content": response.content})

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            used.append(block.name)
            data = await _run_tool(db, block.name, block.input or {})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(data, default=str),
            })
        messages.append({"role": "user", "content": results})

    return {
        "answer": "I looked at several reports but could not settle on an answer. "
                  "Try asking about one thing at a time.",
        "used": used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
