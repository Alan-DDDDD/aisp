"""Sandbox 子套件 — Phase B 的 [C5]。

公開介面：
  SandboxRunner   抽象介面
  SandboxResult   執行結果
  LocalSubprocessRunner  本機 subprocess 實作（dev 用，不真正隔離）
  E2BRunner       E2B 雲端 sandbox 實作（PROD，需 E2B_API_KEY）
  get_default     依環境變數選擇實作
"""

from app.synthesis.sandbox.base import SandboxResult, SandboxRunner
from app.synthesis.sandbox.local import LocalSubprocessRunner

__all__ = [
    "E2BRunner",
    "LocalSubprocessRunner",
    "SandboxResult",
    "SandboxRunner",
    "get_default",
]


def get_default() -> SandboxRunner:
    """選擇 runner：有 E2B_API_KEY 用 E2B；否則 LocalSubprocessRunner。

    lazy 載入 E2BRunner 避免在沒裝 e2b SDK 的環境 import 失敗。
    """
    import os

    if os.environ.get("E2B_API_KEY"):
        from app.synthesis.sandbox.e2b import E2BRunner

        return E2BRunner()
    return LocalSubprocessRunner()


# E2BRunner 的 lazy attribute：import 它的人才會觸發 e2b SDK 載入
def __getattr__(name: str):
    if name == "E2BRunner":
        from app.synthesis.sandbox.e2b import E2BRunner

        return E2BRunner
    raise AttributeError(name)
