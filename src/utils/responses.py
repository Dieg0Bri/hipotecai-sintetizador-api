from typing import Any
from fastapi.responses import JSONResponse


def success_response(data: Any = None, message: str | None = None, status_code: int = 200):
    body: dict = {"status": "success"}
    if data is not None:
        body["data"] = data
    if message:
        body["message"] = message
    return JSONResponse(status_code=status_code, content=body)


def error_response(message: str, code: str = "INTERNAL_ERROR", data: Any = None, status_code: int = 500):
    body: dict = {"status": "error", "code": code, "message": message}
    if data is not None:
        body["data"] = data
    return JSONResponse(status_code=status_code, content=body)
