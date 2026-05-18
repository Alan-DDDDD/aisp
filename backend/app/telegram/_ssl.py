"""SSL 修補 — 給企業網路（self-signed CA / 攔截式 proxy）用。

python-telegram-bot 內部用 httpx，預設信任 certifi bundled CAs；
若你的環境（公司、機構 proxy）會替換 SSL 憑證，連 Telegram 會撞
"self-signed certificate in certificate chain"。

truststore 是把 OS 的 trust store（Windows 證書管理員 / macOS Keychain /
Linux ca-certificates）當作 ssl module 的預設 trust。注入一次後，
所有後續 SSL 連線自動採用 —— 包括 PTB / httpx / chromadb。

只在 PtbBot / PtbSender 啟動時 lazy 呼叫，避免污染 unit test。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_injected = False


def ensure_truststore() -> None:
    """冪等 — 已注入過就跳過。truststore 未安裝時 log 一行不爆。"""
    global _injected
    if _injected:
        return
    try:
        import truststore  # type: ignore

        truststore.inject_into_ssl()
        _injected = True
        log.info("telegram: truststore 注入完成（採用 OS trust store）")
    except ImportError:
        log.debug("telegram: truststore 未安裝，使用 httpx 預設 SSL verify")
    except Exception as e:  # noqa: BLE001
        log.warning("telegram: truststore inject 失敗：%s", e)
