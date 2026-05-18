"""Synthesis Orchestrator — Phase B Code Agent 的主流程（PLAN §22.5.2 / §22.5.6）。

把 M4 + M5 的元件接成一條鏈：

    spec → [C1] enricher → [C3] test_gen
                              ↓ (隔離)
              ┌─────────────[C2] code_gen ←─┐
              │                              │ feedback
              ▼                              │
        [C4] static_check ──fail──┘─attempts<3
              │ ok
              ▼
        [C5] sandbox.run ──fail──┘─attempts<3
              │ ok
              ▼
        SynthesisResult(success=True)

attempts 用盡仍失敗 → SynthesisResult(success=False)，attempt_history 保留每一輪痕跡
給人類審核時看（PLAN §22.5.7）。

注意：這個 orchestrator **不寫 DB、不送 Telegram**。狀態持久化與審核 UI 是 M6 的範疇。
這層只做計算，產出可被 M6 包裝的純 result。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.providers.base import LLMProvider
from app.synthesis import static_check
from app.synthesis.code_generator import CodeGenerator
from app.synthesis.sandbox import SandboxResult, SandboxRunner, get_default
from app.synthesis.schemas import EnrichedToolSpec, ToolSpec
from app.synthesis.spec_enricher import SpecEnricher
from app.synthesis.test_generator import TestGenerator

log = logging.getLogger(__name__)


@dataclass
class SynthesisAttempt:
    """一次 code → static check → sandbox 嘗試的結果。"""

    round: int
    code: str
    static_ok: bool
    static_errors: list[str] = field(default_factory=list)
    sandbox: SandboxResult | None = None
    feedback_used: str = ""  # 上一輪餵給 LLM 的 feedback


@dataclass
class SynthesisResult:
    """整個 synthesize 的最終結果。

    success=True：code 通過 static + sandbox，可進審核
    success=False：所有 attempts 用盡，需要人類 rescue
    """

    success: bool
    spec_raw: ToolSpec
    spec_enriched: EnrichedToolSpec
    tests: str
    final_code: str = ""
    attempts: list[SynthesisAttempt] = field(default_factory=list)
    sandbox_result: SandboxResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def behavior_summary(self) -> dict[str, Any]:
        """給審核 UI 看的「sandbox 觀察到的行為」摘要（PLAN §22.5.5）。"""
        if self.sandbox_result is None:
            return {}
        by_type: dict[str, int] = {}
        for obs in self.sandbox_result.observations:
            t = obs.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "passed": self.sandbox_result.passed,
            "failed": self.sandbox_result.failed,
            "observations_by_type": by_type,
            "raw_observations": self.sandbox_result.observations[:20],
        }


class SynthesisOrchestrator:
    """串接 enricher / test_gen / code_gen / static / sandbox 的主流程。

    所有元件可被注入，方便測試。
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        enricher: SpecEnricher | None = None,
        code_gen: CodeGenerator | None = None,
        test_gen: TestGenerator | None = None,
        runner: SandboxRunner | None = None,
        max_attempts: int | None = None,
        sandbox_timeout_s: int | None = None,
    ) -> None:
        self.provider = provider
        self.enricher = enricher or SpecEnricher(provider=provider)
        self.code_gen = code_gen or CodeGenerator(provider=provider)
        self.test_gen = test_gen or TestGenerator(provider=provider)
        self.runner = runner or get_default()
        self.max_attempts = max_attempts or settings.synth_max_attempts
        self.sandbox_timeout_s = sandbox_timeout_s or settings.synth_sandbox_timeout_s

    async def synthesize(self, raw_spec: ToolSpec) -> SynthesisResult:
        log.info("Synthesizing tool for spec: %s", raw_spec.name)

        # [C1] Spec 補完（一次）
        enriched = await self.enricher.enrich(raw_spec)

        # [C3] Test 生成（一次，code-test 隔離 → 在 code 還沒生之前先做）
        tests = await self.test_gen.generate(enriched)

        result = SynthesisResult(
            success=False,
            spec_raw=raw_spec,
            spec_enriched=enriched,
            tests=tests,
        )

        feedback: str = ""
        for attempt_idx in range(1, self.max_attempts + 1):
            # [C2] Code 生成（attempt_idx > 1 時帶 feedback）
            code = await self.code_gen.generate(enriched, feedback=feedback or None)

            attempt = SynthesisAttempt(
                round=attempt_idx, code=code, static_ok=False, feedback_used=feedback
            )

            # [C4] 靜態檢查
            check = static_check.check(code)
            attempt.static_ok = check.ok
            attempt.static_errors = list(check.errors)

            if not check.ok:
                feedback = check.feedback_for_llm()
                result.attempts.append(attempt)
                log.info(
                    "Attempt %d failed static check: %s",
                    attempt_idx,
                    check.errors[:3],
                )
                continue

            # [C5] Sandbox 跑 tests
            sandbox = await self.runner.run_python(
                code, tests, timeout_s=self.sandbox_timeout_s
            )
            attempt.sandbox = sandbox
            result.attempts.append(attempt)

            if sandbox.all_passed:
                result.success = True
                result.final_code = code
                result.sandbox_result = sandbox
                log.info("Synthesis succeeded at attempt %d", attempt_idx)
                return result

            feedback = sandbox.feedback_for_llm()
            log.info(
                "Attempt %d failed sandbox: passed=%d failed=%d",
                attempt_idx,
                sandbox.passed,
                sandbox.failed,
            )

        # 所有 attempts 用盡仍失敗
        last = result.attempts[-1] if result.attempts else None
        if last and last.sandbox is not None:
            result.sandbox_result = last.sandbox
            result.final_code = last.code
        elif last:
            result.final_code = last.code
        result.error = f"超過 {self.max_attempts} 次嘗試仍失敗，需要人類 rescue"
        return result
