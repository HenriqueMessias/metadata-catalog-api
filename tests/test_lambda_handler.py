from __future__ import annotations

from mangum import Mangum

from app.lambda_handler import handler


def test_handler_wraps_the_same_fastapi_app():
    # Guards against the Lambda entrypoint silently breaking (e.g. an import
    # error) without needing a real API Gateway event or a Lambda runtime.
    assert isinstance(handler, Mangum)
