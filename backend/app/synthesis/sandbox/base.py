"""SandboxRunner 抽象介面。

設計（PLAN §22.5.3）：
- 業務邏輯只跟介面互動，未來換 E2B / Docker / Firecracker 都不用改 orchestrator
- 一次 run_python 就提供完整 sandbox 生命週期：起、跑、收結果、銷毀
- 行為觀察結果也在 SandboxResult 裡（PLAN §22.5.5）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxResult:
    """sandbox 一次執行的完整結果。"""

    # pytest 退出碼（0 = 全綠；非 0 = 有失敗或內部錯誤）
    exit_code: int

    # pytest 統計
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0

    # 原始輸出（前若干 KB 即可，不要塞太多）
    stdout: str = ""
    stderr: str = ""

    # 失敗訊息（給 LLM 修正迴圈用，已抽出來方便餵回去）
    failure_messages: list[str] = field(default_factory=list)

    # 行為觀察結果（PLAN §22.5.5）
    # 結構：[{"type": "socket", "args": "(...)"}, {"type": "open", "path": "..."}]
    observations: list[dict[str, Any]] = field(default_factory=list)

    # 是否觸發 timeout / OOM 等基礎錯誤
    timed_out: bool = False
    setup_error: str | None = None

    @property
    def all_passed(self) -> bool:
        return (
            self.exit_code == 0
            and self.failed == 0
            and self.errors == 0
            and not self.timed_out
            and self.setup_error is None
        )

    def feedback_for_llm(self) -> str:
        """格式化成可餵給 code generator [C2] 的下一輪修正訊息。"""
        if self.all_passed:
            return ""

        parts: list[str] = ["sandbox 測試未通過，請修正後重新產生 code。"]
        if self.timed_out:
            parts.append("  - 執行 timeout，code 可能有死循環或極慢的操作")
        if self.setup_error:
            parts.append(f"  - sandbox 啟動或載入失敗：{self.setup_error}")
        if self.failed or self.errors:
            parts.append(
                f"  - pytest: {self.passed} passed, {self.failed} failed, {self.errors} errors"
            )
        for msg in self.failure_messages[:5]:
            parts.append(f"  - {msg}")
        # 把 stderr 的最後幾行也帶上，幫 LLM 抓 ImportError / NameError
        if self.stderr:
            tail = "\n".join(self.stderr.strip().splitlines()[-10:])
            parts.append("stderr (尾部)：\n" + tail)
        return "\n".join(parts)


class SandboxRunner(ABC):
    """所有 sandbox 實作的契約。

    實作要保證：
    1. 完全隔離（builtin / network / fs 都該限縮）—— 至少要禁 host fs 寫入
    2. 一次 call 自我清理；下一次 call 是乾淨環境
    3. timeout 必須生效（避免死循環卡爆主流程）
    """

    name: str

    @abstractmethod
    async def run_python(
        self,
        code: str,
        tests: str,
        *,
        timeout_s: int = 60,
    ) -> SandboxResult:
        """在隔離環境執行 code + tests。

        code 會寫成 `generated_tool.py`，tests 寫成 `test_generated_tool.py`。
        實作會自動 prepend 行為觀察 shim。
        """
        raise NotImplementedError
