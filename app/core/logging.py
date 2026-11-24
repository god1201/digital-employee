import logging
import sys

from app.core.config import settings
from app.core.context import request_id_ctx, trace_id_ctx


class ContextFilter(logging.Filter):
    """把请求 ID 与任务 trace_id 注入日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")
        record.trace_id = trace_id_ctx.get("-")
        return True


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s | %(levelname)-7s | rid=%(request_id)s | "
            "tid=%(trace_id)s | %(name)s | %(message)s"
        ),
        stream=sys.stdout,
        force=True,
    )
    context_filter = ContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(context_filter)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
