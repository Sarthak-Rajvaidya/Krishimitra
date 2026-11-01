import json
import logging
import re


class JsonFormatter(logging.Formatter):
    SECRET = re.compile(r"(api[_-]?key|authorization|password|secret)\S*", re.I)

    def format(self, record: logging.LogRecord) -> str:
        msg = self.SECRET.sub("[redacted]", record.getMessage())
        return json.dumps({"level": record.levelname, "logger": record.name, "msg": msg})


def setup_logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(logging.INFO)
