"""API errors with one JSON body shape for every non-2xx answer (LLD section 1)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.logging_setup import get_logger

log = get_logger(__name__)

_CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
}


class ApiError(Exception):
    """An error the endpoint raises on purpose, with its status and code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """Store the HTTP status, the machine-readable code and the message."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    """Build the standard error body."""
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


def install_handlers(app: FastAPI) -> None:
    """Replace FastAPI's default error bodies with the LLD format."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"] if p != "body")
            parts.append(f"{where}: {err['msg']}" if where else err["msg"])
        return error_response(422, "VALIDATION_ERROR", "; ".join(parts))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, "BAD_REQUEST")
        return error_response(exc.status_code, code, str(exc.detail))
