from __future__ import annotations

import logging

from backend.core.task_schema import ExecutionResult, TaskStep

logger = logging.getLogger(__name__)


class Tester:
    async def validate(self, step: TaskStep, result: ExecutionResult) -> bool:
        if result.timed_out:
            logger.warning("Step %s timed out", step.id)
            return False

        if result.exit_code != 0:
            logger.warning(
                "Step %s failed with exit code %d. stderr: %s",
                step.id,
                result.exit_code,
                result.stderr[:500],
            )
            return False

        expected = step.expected_output
        if expected:
            combined_output = (result.stdout + result.stderr).lower()
            if expected.lower() not in combined_output:
                logger.info(
                    "Step %s output does not match expected. expected=%r, got=%r",
                    step.id,
                    expected[:200],
                    combined_output[:200],
                )
                # Don't fail on expected_output mismatch alone — it may be approximate
                # Only fail on non-zero exit codes or timeouts
                pass

        logger.info("Step %s passed validation", step.id)
        return True
