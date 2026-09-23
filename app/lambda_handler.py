"""AWS Lambda entrypoint.

Wraps the same FastAPI app used locally (`app.main:app`) with Mangum, which
translates API Gateway events into ASGI calls and back. This file is only
ever imported by the Lambda runtime (as `app.lambda_handler.handler`) — it
is never imported by `app/main.py` or the test suite, so `uvicorn` and
`pytest` run exactly as before, with no AWS dependency in the loop.
"""

from mangum import Mangum

from app.main import app

# lifespan="auto" (Mangum's default) runs the FastAPI startup/shutdown
# lifespan handlers once per Lambda execution environment: the Mongo client
# is created on the first (cold-start) invocation and reused by warm
# invocations of the same container, same as it would be reused across
# requests handled by a single long-lived uvicorn process.
handler = Mangum(app, lifespan="auto")
