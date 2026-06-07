"""Versioned prompts for action-item extraction workflows with context enrichment."""

from __future__ import annotations

PROMPT_VERSION = "action_items_v2"

ACTION_ITEMS_SYSTEM = """\
You are an expert business analyst extracting action items from meeting notes, transcripts, or documents.

Rules:
- Extract ONLY concrete, assignable tasks — not observations or discussion points.
- Each action item must have a clear title (≤ 120 chars).
- If an owner is mentioned (name or role), include it. Use the provided context documents to resolve
  shorthand names or initials (e.g. "Anish") to email addresses or full names if found.
- If a due date or deadline is mentioned, include it as ISO date (YYYY-MM-DD) or natural language.
- Set confidence between 0.0 (very uncertain) and 1.0 (explicitly stated task).
- destination must be one of: notion, freshdesk, slack, manual.
- Check the RECENT ACTION ITEMS section below. If a task has already been extracted (similar title and
  matching owner), do NOT extract it again to avoid duplicates.
- Return a JSON object with key "items" containing an array of action item objects.

Output format (strict JSON, no markdown fences in final output):
{
  "items": [
    {
      "title": "string",
      "owner": "string or null",
      "due_date": "string or null",
      "destination": "manual",
      "source_quote": "exact quote from input that triggered this item",
      "confidence": 0.9
    }
  ]
}
"""


def build_extraction_prompt(
    input_text: str,
    destination: str,
    context_documents: list[dict] | None = None,
    existing_action_items: list[dict] | None = None,
) -> str:
    """Build prompt containing meeting text, Qdrant document context, and existing task list."""
    prompt_parts = [ACTION_ITEMS_SYSTEM]

    if context_documents:
        prompt_parts.append("### RELATED ORG CONTEXT:")
        for doc in context_documents:
            title = doc.get("title", "Untitled")
            text = doc.get("text", "")
            src = doc.get("source_type", "unknown")
            prompt_parts.append(f"[{src.upper()}] {title}:\n{text}\n")

    if existing_action_items:
        prompt_parts.append("### RECENT ACTION ITEMS (Avoid duplicating these):")
        for item in existing_action_items:
            title = item.get("title")
            owner = item.get("owner") or "Unassigned"
            status = item.get("status")
            prompt_parts.append(f"- {title} (Assignee: {owner}, Status: {status})")
        prompt_parts.append("")

    prompt_parts.extend(
        [
            f"Default destination for extracted items: {destination}\n",
            f"INPUT TEXT:\n{input_text}\n",
            "Extract all new, unique action items and return the JSON object:",
        ]
    )

    return "\n".join(prompt_parts)
