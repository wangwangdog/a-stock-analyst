"""
错误压缩器 — 12-Factor Agent F9 实现

结构化错误格式 + 自动重试逻辑 + 升级上报。
"""

import json
import time
import logging
from typing import Optional, Callable
from datetime import datetime

logger = logging.getLogger("error_compactor")


class CompactError:
    """结构化压缩错误"""
    def __init__(self, step: str, error_type: str, message: str,
                 attempts: int = 1, next_action: str = "retry",
                 details: dict = None):
        self.step = step
        self.error_type = error_type      # timeout | api_block | data_corrupt | login_failed
        self.message = message            # 简短可读
        self.attempts = attempts
        self.next_action = next_action     # retry | skip | escalate
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "error_type": self.error_type,
            "message": self.message[:200],
            "attempts": self.attempts,
            "next_action": self.next_action,
            "timestamp": self.timestamp,
        }


class RetryHandler:
    """
    自动重试处理器
    
    用法：
        handler = RetryHandler(max_retries=3, backoff_base=2)
        result = handler.run("tencent_fq_sync", lambda: do_sync())
        if not result.success:
            # 升级处理
    """

    def __init__(self, max_retries: int = 3, backoff_base: float = 2.0,
                 on_retry: Callable = None, on_fail: Callable = None):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.on_retry = on_retry
        self.on_fail = on_fail

    class Result:
        def __init__(self, success: bool, data=None, error: CompactError = None,
                     attempts: int = 0):
            self.success = success
            self.data = data
            self.error = error
            self.attempts = attempts

    def run(self, step: str, fn: Callable, *args, **kwargs) -> "RetryHandler.Result":
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                data = fn(*args, **kwargs)
                if attempt > 1:
                    logger.info(f"[{step}] 重试第{attempt}次成功")
                return self.Result(success=True, data=data, attempts=attempt)
            except Exception as e:
                last_error = e
                err_type = self._classify_error(e)
                msg = str(e)[:200]
                logger.warning(f"[{step}] 失败(attempt {attempt}/{self.max_retries}): {err_type} - {msg}")

                if self.on_retry:
                    self.on_retry(CompactError(step, err_type, msg, attempt))

                if attempt < self.max_retries:
                    sleep_sec = self.backoff_base ** (attempt - 1)
                    logger.info(f"[{step}] 等待 {sleep_sec}s 后重试...")
                    time.sleep(sleep_sec)

        # 全部失败
        final_error = CompactError(
            step=step,
            error_type=self._classify_error(last_error),
            message=str(last_error)[:200],
            attempts=self.max_retries,
            next_action="escalate",
        )

        if self.on_fail:
            self.on_fail(final_error)

        return self.Result(success=False, error=final_error, attempts=self.max_retries)

    @staticmethod
    def _classify_error(e: Exception) -> str:
        msg = str(e).lower()
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
        if "login" in msg or "auth" in msg or "authenticate" in msg:
            return "login_failed"
        if "connect" in msg or "refused" in msg or "reset" in msg:
            return "api_block"
        if "duplicate" in msg or "unique constraint" in msg or "integrity" in msg:
            return "data_duplicate"
        if "no such table" in msg or "column" in msg:
            return "schema_error"
        return "unknown"


def format_error_for_context(error: CompactError) -> str:
    """格式化为适合放入 LLM context 窗口的文本"""
    return f"""
<error>
  <step>{error.step}</step>
  <type>{error.error_type}</type>
  <message>{error.message}</message>
  <attempts>{error.attempts}</attempts>
  <next_action>{error.next_action}</next_action>
  <timestamp>{error.timestamp}</timestamp>
</error>
"""
