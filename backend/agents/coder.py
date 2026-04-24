"""Coder agent — generates code files for a plan step."""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.llm.client import chat_completion
from backend.models import GeneratedFile, PlanStep, ProjectPlan

SYSTEM_PROMPT = """You are an expert software engineer. You write production-quality code.

Given a project goal and the current step to implement, you output real, working source code files.

Rules:
- Output ONLY valid JSON — no markdown outside the JSON structure.
- Each file must have a "path" (relative to project root), "content" (full file content), and "language".
- Write complete, runnable files — no placeholders like "TODO" or "# implement this".
- Use modern best practices for each language.
- Include a requirements.txt if Python packages are needed.
- Include a package.json if Node packages are needed.
- Make sure the code is syntactically correct and would actually run.

Respond ONLY with this JSON structure:
{
  "files": [
    {
      "path": "relative/path/to/file.ext",
      "language": "python",
      "content": "full file content here"
    }
  ],
  "explanation": "brief explanation of what was built"
}
"""


async def generate_files(
    goal: str,
    plan: ProjectPlan,
    step: PlanStep,
    existing_files: dict[str, str],
    history: list[dict],
) -> tuple[list[GeneratedFile], str]:
    """
    Generate code files for a specific plan step.
    Returns (list of GeneratedFile, explanation string).
    """
    existing_summary = _summarize_existing(existing_files)
    step_prompt = f"""Project goal: {goal}

Full plan:
{_format_plan(plan)}

Current step to implement ({step.index + 1}/{len(plan.steps)}):
Title: {step.title}
Description: {step.description}

Files already created:
{existing_summary}

Generate the code files needed for this step. Build on existing files where appropriate."""

    messages = [
        *history[-4:],
        {"role": "user", "content": step_prompt},
    ]
    response = await chat_completion(
        messages,
        system_prompt=SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=8192,
    )
    files, explanation = _parse_files(response)
    return files, explanation


def _parse_files(raw: str) -> tuple[list[GeneratedFile], str]:
    """Parse JSON file list from LLM response."""
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    # Handle trailing fences
    text = re.sub(r"```\s*$", "", text).strip()
    try:
        data = json.loads(text)
        raw_files = data.get("files", [])
        explanation = data.get("explanation", "Files generated.")
        files = [
            GeneratedFile(
                path=f["path"],
                content=f["content"],
                language=f.get("language", _guess_language(f["path"])),
            )
            for f in raw_files
            if "path" in f and "content" in f
        ]
        return files, explanation
    except (json.JSONDecodeError, KeyError) as exc:
        # Try to extract code blocks as fallback
        code_blocks = re.findall(r"```(\w+)?\n(.*?)```", raw, re.DOTALL)
        files = []
        for i, (lang, code) in enumerate(code_blocks):
            ext = _lang_to_ext(lang or "text")
            files.append(GeneratedFile(path=f"main{ext}", content=code.strip(), language=lang or "text"))
        return files, f"Parsed {len(files)} file(s) from response (JSON parse failed: {exc})."


def _format_plan(plan: ProjectPlan) -> str:
    lines = []
    for step in plan.steps:
        status_marker = "✓" if step.status == "done" else "→" if step.status == "active" else "○"
        lines.append(f"  {status_marker} Step {step.index + 1}: {step.title}")
    return "\n".join(lines)


def _summarize_existing(existing: dict[str, str]) -> str:
    if not existing:
        return "None yet."
    lines = []
    for path, content in existing.items():
        preview = content[:200].replace("\n", " ")
        lines.append(f"  - {path} ({len(content)} chars): {preview}...")
    return "\n".join(lines)


def _guess_language(path: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".html": "html", ".css": "css", ".json": "json", ".md": "markdown",
        ".sh": "bash", ".yml": "yaml", ".yaml": "yaml", ".txt": "text",
        ".sql": "sql", ".go": "go", ".rs": "rust",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return "text"


def _lang_to_ext(lang: str) -> str:
    ext_map = {
        "python": ".py", "javascript": ".js", "typescript": ".ts",
        "html": ".html", "css": ".css", "json": ".json",
        "bash": ".sh", "yaml": ".yml", "sql": ".sql",
    }
    return ext_map.get(lang.lower(), ".txt")
