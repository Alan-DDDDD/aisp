"""AST 靜態檢查 — Phase B 的 [C4]，sandbox 跑 test 前先把 LLM 失誤擋下來。

設計要點（PLAN §22.5.2）：
- 寧可 reject 太多也別放過危險 code
- 失敗訊息要可餵回 LLM 做下一輪修正（[C2] 的 feedback 參數）
- 三層檢查：(1) 能 parse (2) 結構合契約 (3) 沒有禁用 pattern

允許 / 禁止清單刻意保守。M5 之後若 spec 宣告需要網路/DB，可動態擴充白名單。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# ── 安全策略 ───────────────────────────────────────────────────────


ALLOWED_TOP_LEVEL_MODULES: set[str] = {
    "__future__",
    "abc",
    "asyncio",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "functools",
    "itertools",
    "json",
    "logging",
    "math",
    "pydantic",
    "re",
    "statistics",
    "string",
    "typing",
    "uuid",
}

# 允許從 app 命名空間 import 的東西（嚴格白名單）
ALLOWED_APP_IMPORTS: set[str] = {
    "app.schemas.agent",
    "app.tools.base",
}

# 任何 import 出現這些名稱（或前綴）就直接判失敗 —— 不管是不是被「主動」用
FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "subprocess",
    "socket",
    "ssl",
    "ctypes",
    "pickle",
    "marshal",
    "shelve",
    "shutil",
    "tempfile",
    "pathlib",
    "os",
    "io",
    "fcntl",
    "select",
    "selectors",
    "urllib",
    "http",
    "httpx",
    "requests",
    "aiohttp",
    "websockets",
    "sqlalchemy",
    "sqlite3",
    "pymysql",
    "psycopg",
    "redis",
    "boto3",
    "google",  # google sdks
    "app.db",
    "app.km",
    "app.providers",
)

FORBIDDEN_BUILTINS: set[str] = {
    "exec",
    "eval",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "open",
    "input",
    "breakpoint",
}


# ── 結果 ──────────────────────────────────────────────────────────


@dataclass
class StaticCheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL: " + " | ".join(self.errors[:5])

    def feedback_for_llm(self) -> str:
        """格式化成可餵給 LLM [C2] 做下一輪修正的訊息。"""
        if self.ok:
            return ""
        lines = ["靜態檢查失敗，請修正以下問題後重新產生 code："]
        lines.extend(f"  - {e}" for e in self.errors)
        if self.warnings:
            lines.append("（warning，可不修但建議改）：")
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────────────


def check(code: str) -> StaticCheckResult:
    """對 generated tool 的原始碼做靜態檢查。"""
    result = StaticCheckResult(ok=True)

    if not code or not code.strip():
        result.ok = False
        result.errors.append("code 為空")
        return result

    # 1. 能 parse
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        result.ok = False
        result.errors.append(f"SyntaxError: {e.msg} (line {e.lineno})")
        return result

    # 2. import 白名單
    _check_imports(tree, result)

    # 3. 禁用 pattern
    _check_forbidden_patterns(tree, result)

    # 4. 結構契約：恰好一個 BaseTool subclass，含 async def call
    _check_structure(tree, result)

    if result.errors:
        result.ok = False
    return result


# ── 各層檢查 ─────────────────────────────────────────────────────


def _check_imports(tree: ast.AST, result: StaticCheckResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_one_module(alias.name, result, node)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            _check_one_module(mod, result, node)


def _check_one_module(module_name: str, result: StaticCheckResult, node: ast.AST) -> None:
    top = module_name.split(".", 1)[0]

    # 1. 是不是禁用清單（前綴比對）
    for forbidden in FORBIDDEN_MODULE_PREFIXES:
        if module_name == forbidden or module_name.startswith(forbidden + "."):
            result.errors.append(
                f"line {getattr(node, 'lineno', '?')}: 禁止 import {module_name}（屬於 {forbidden}）"
            )
            return

    # 2. 是不是 app.* 但不在白名單
    if top == "app" and module_name not in ALLOWED_APP_IMPORTS:
        result.errors.append(
            f"line {getattr(node, 'lineno', '?')}: 禁止 import {module_name}"
            f"，app 命名空間只允許 {sorted(ALLOWED_APP_IMPORTS)}"
        )
        return

    # 3. 是不是頂層白名單
    if top in ALLOWED_TOP_LEVEL_MODULES or top == "app":
        return

    result.errors.append(
        f"line {getattr(node, 'lineno', '?')}: import {module_name} 不在白名單"
    )


def _check_forbidden_patterns(tree: ast.AST, result: StaticCheckResult) -> None:
    forbidden_dunders = {"__builtins__", "__import__", "__class__", "__subclasses__"}
    for node in ast.walk(tree):
        # 1. 呼叫 forbidden builtin
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FORBIDDEN_BUILTINS
        ):
            result.errors.append(
                f"line {node.lineno}: 禁止呼叫 {node.func.id}()"
            )
        # 2. 存取 __builtins__ / __import__ 等魔法名
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("__")
            and node.attr.endswith("__")
            and node.attr in forbidden_dunders
        ):
            result.errors.append(
                f"line {node.lineno}: 禁止存取 {node.attr}"
            )
        # 3. getattr/setattr 對動態屬性（getattr(obj, dyn_str)）— 太寬，先警告不擋
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "setattr"}
            and len(node.args) > 1
            and not isinstance(node.args[1], ast.Constant)
        ):
            result.warnings.append(
                f"line {node.lineno}: 動態 {node.func.id}() 可能被用來繞過白名單"
            )


def _check_structure(tree: ast.AST, result: StaticCheckResult) -> None:
    tool_classes: list[ast.ClassDef] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _inherits_basetool(node):
            tool_classes.append(node)

    if len(tool_classes) == 0:
        result.errors.append("找不到 BaseTool subclass（必須 subclass `BaseTool`）")
        return
    if len(tool_classes) > 1:
        result.errors.append(
            f"找到 {len(tool_classes)} 個 BaseTool subclass，請只定義一個："
            f"{[c.name for c in tool_classes]}"
        )

    cls = tool_classes[0]
    required_attrs = {
        "id",
        "description",
        "when_to_use",
        "when_NOT_to_use",
        "examples",
        "input_schema",
        "output_schema",
    }
    defined_attrs: set[str] = set()
    has_async_call = False

    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    defined_attrs.add(tgt.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            defined_attrs.add(stmt.target.id)
        elif isinstance(stmt, ast.AsyncFunctionDef) and stmt.name == "call":
            has_async_call = True
        elif isinstance(stmt, ast.FunctionDef) and stmt.name == "call":
            result.errors.append(f"class {cls.name}: call() 必須是 async def，目前是 sync def")

    missing = required_attrs - defined_attrs
    if missing:
        result.errors.append(
            f"class {cls.name}: 缺少必要欄位 {sorted(missing)}"
        )
    if not has_async_call:
        result.errors.append(f"class {cls.name}: 缺 async def call(self, ctx, payload)")


def _inherits_basetool(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "BaseTool":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseTool":
            return True
    return False
