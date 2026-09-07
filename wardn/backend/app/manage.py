import logging
import sys
import time
import uuid

from app.commands import app
from app.core.logging import configure_logging, elapsed_ms, log_context
from app.modules.observability.job_logs import flush_job_logs

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging("cli")
    started = time.perf_counter()
    code = 0
    with log_context(command_id=uuid.uuid4().hex):
        logger.info("command_started")
        try:
            app(args=argv, prog_name="wardn")
        except SystemExit as exc:
            code = int(exc.code or 0)
        except Exception:
            code = 1
            logger.exception("command_failed")
        finally:
            logger.log(
                logging.WARNING if code else logging.INFO,
                "command_completed",
                extra={"exit_code": code, "duration_ms": elapsed_ms(started)},
            )
    flush_job_logs()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
