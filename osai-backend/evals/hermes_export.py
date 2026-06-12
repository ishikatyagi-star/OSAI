"""Bridge OSAI's eval harness to Hermes Agent Self-Evolution (services/hermes).

Hermes (DSPy + GEPA) evolves a SKILL.md against a "golden" dataset of
inputs + expected-behavior rubrics. This module exports an OSAI skill and our
eval fixtures into that shape, so a Hermes optimization run is one command away.

Run the optimization (after `pip install -e services/hermes`):

    python -m evolution.skills.evolve_skill \
        --skill osai-answer-synthesis \
        --eval-source golden \
        --dataset <out>/datasets/osai-answer-synthesis \
        --iterations 10

with DSPy pointed at Groq:  GROQ_API_KEY=$OSAI_LLM_API_KEY
and eval_model = "groq/llama-3.3-70b-versatile".

This is the P6 self-improvement layer: it only produces signal now that LLM
answers are live (Groq), and gets better as real session logs feed the fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.fixtures import FIXTURES

# The OSAI skill we expose to Hermes first: the answer-synthesis prompt used in
# memory/retriever.py. Kept here as the editable artifact Hermes evolves.
ANSWER_SYNTHESIS_SKILL = """# OSAI Answer Synthesis

You are a precise enterprise knowledge assistant for university operations.
Answer the question using ONLY the provided context (documents + OSAI memory).
Be concise. Cite document titles inline. If the context is insufficient, say so
and state what is missing rather than guessing.
"""


def export_golden_dataset(out_dir: Path) -> Path:
    """Write OSAI eval fixtures as a Hermes golden dataset (inputs + rubric)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    examples = [
        {
            "inputs": {"question": fx["question"]},
            "expected_behavior": (
                f"A correct answer to '{fx['question']}' should address the "
                f"{fx['category']} intent and reference: {', '.join(fx['expected'])}."
            ),
        }
        for fx in FIXTURES
    ]
    path = out_dir / "dataset.json"
    path.write_text(json.dumps(examples, indent=2))
    return path


def export_skill(skills_dir: Path, name: str = "osai-answer-synthesis") -> Path:
    """Write the OSAI skill as a SKILL.md Hermes can evolve."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(ANSWER_SYNTHESIS_SKILL)
    return path


def export_all(out_dir: Path) -> dict[str, Path]:
    name = "osai-answer-synthesis"
    return {
        "skill": export_skill(out_dir / "skills", name),
        "dataset": export_golden_dataset(out_dir / "datasets" / name),
    }


def main() -> None:
    out = Path("hermes_export")
    paths = export_all(out)
    print(f"Skill:   {paths['skill']}")
    print(f"Dataset: {paths['dataset'].parent}")
    print(
        "\nNext: pip install -e services/hermes, then\n"
        "  GROQ_API_KEY=$OSAI_LLM_API_KEY \\\n"
        "  python -m evolution.skills.evolve_skill --skill osai-answer-synthesis \\\n"
        f"    --eval-source golden --dataset {paths['dataset'].parent} --iterations 10"
    )


if __name__ == "__main__":
    main()
