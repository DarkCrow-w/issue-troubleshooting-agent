"""Trusted deterministic skill strategies."""

from .exceptions import exception_analysis
from .failures import failure_localization
from .ordering import time_key
from .requests import request_response
from .trace import trace_reconstruction

HANDLERS = {
    "request_response": request_response,
    "exception_analysis": exception_analysis,
    "trace_reconstruction": trace_reconstruction,
    "failure_localization": failure_localization,
}
__all__ = ["HANDLERS", "time_key"]
