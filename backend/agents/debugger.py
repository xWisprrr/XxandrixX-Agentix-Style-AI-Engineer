"""Debugger agent — analyzes execution errors and produces fixes."""
from __future__ import annotations

import json
import re

from backend.llm.client import chat_completion
from backend.models import ExecutionResult, GeneratedFile

SYSTEM_PROMPT = """You are an expert software debugger. You analyze error output and fix code.

Given:
- The project goal
- The current source files  
- The execution output (stdout + stderr)
- The error/exit code

You identify the root cause and produce fixed versions of the affected files.

Rules:
- Output ONLY valid JSON — no markdown outside the JSON.
- Include ALL files that need changes (full content, not patches).
- Fix the actual root cause, not just suppress the symptom.
- If the error is a missing dependency, add it to requirements.txt or package.json.
- Be precise and confident — don't hedge.

Respond with:
{
  "root_cause": "brief description of the bug",
  "fix_description": "what you changed and why",
  "files": [
    {
      "path": "relative/path/to/file.ext",
      "language": "python",
      "content": "complete fixed file content"
    }
  ]
}
"""


async def fix_errors(
    goal: str,
    existing_files: dict[str, str],
    execution_result: ExecutionResult,
    attempt: int,
    history: list[dict],
) -> tuple[list[GeneratedFile], str, str]:
    """
    Analyze errors and generate fixed files.
    Returns (fixed_files, root_cause, fix_description).
    """
    files_dump = "\n\n".join(
        f"=== {path} ===\n{content}" for path, content in existing_files.items()
    )
    prompt = f"""Project goal: {goal}

Execution failed (attempt {attempt}):
- Exit code: {execution_result.exit_code}
- Timed out: {execution_result.timed_out}

STDOUT:
{execution_result.stdout[-2000:] if execution_result.stdout else "(empty)"}

STDERR:
{execution_result.stderr[-2000:] if execution_result.stderr else "(empty)"}

Current source files:
{files_dump[:6000]}

Identify the root cause and provide fixed files."""

    messages = [
        *history[-4:],
        {"role": "user", "content": prompt},
    ]
    response = await chat_completion(
        messages,
        system_prompt=SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=8192,
    )
    return _parse_fix(response)


def _parse_fix(raw: str) -> tuple[list[GeneratedFile], str, str]:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    text = re.sub(r"```\s*$", "", text).strip()
    try:
        data = json.loads(text)
        root_cause = data.get("root_cause", "Unknown error")
        fix_desc = data.get("fix_description", "Applied fixes.")
        raw_files = data.get("files", [])
        files = [
            GeneratedFile(
                path=f["path"],
                content=f["content"],
                language=f.get("language", "text"),
            )
            for f in raw_files
            if "path" in f and "content" in f
        ]
        return files, root_cause, fix_desc
    except (json.JSONDecodeError, KeyError) as exc:
        return [], "Parse error", f"Could not parse fix response: {exc}"
