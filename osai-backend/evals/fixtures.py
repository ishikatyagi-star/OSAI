"""University-operations eval fixtures.

Each case: a question, the category of skill it exercises, and `expected`
keywords that a correct answer should contain. Grounded in the seeded demo
knowledge base so results are reproducible without a live LLM.
"""

from __future__ import annotations

from typing import TypedDict


class Fixture(TypedDict):
    id: str
    category: str  # ticket_triage | ownership | routing | qa
    question: str
    expected: list[str]


FIXTURES: list[Fixture] = [
    {
        "id": "qa-red-tier",
        "category": "qa",
        "question": "What are the rules for red tier data routing?",
        "expected": ["red", "local", "ollama"],
    },
    {
        "id": "qa-linear",
        "category": "qa",
        "question": "How does OSAI integrate with Linear?",
        "expected": ["linear", "issue", "assignee"],
    },
    {
        "id": "qa-freshdesk-sla",
        "category": "qa",
        "question": "What is the Freshdesk SLA for urgent tickets?",
        "expected": ["freshdesk", "sla", "urgent"],
    },
    {
        "id": "qa-vpc-ollama",
        "category": "qa",
        "question": "How are VPC and Ollama security configured?",
        "expected": ["vpc", "ollama", "local"],
    },
    {
        "id": "routing-amber",
        "category": "routing",
        "question": "What happens to connectors under the amber data tier?",
        "expected": ["amber"],
    },
    {
        "id": "qa-onboarding",
        "category": "qa",
        "question": "Where is the team onboarding guide and what must developers configure?",
        "expected": ["onboard", "docker", "8000"],
    },
    {
        "id": "ownership-zoom",
        "category": "ownership",
        "question": "Who owns the Zoom webhook task?",
        "expected": ["anish"],
    },
    {
        "id": "triage-projector",
        "category": "ticket_triage",
        "question": "A projector is broken in Room 204 — what should be done?",
        "expected": ["ticket"],
    },
]
