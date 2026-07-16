from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.http_errors import PROBLEM_CONTENT_TYPE, configure_error_handling
from app.api.request_id import RequestIDMiddleware
from app.modules.agents.exceptions import AgentNotFoundError
from app.modules.secrets.exceptions import SecretInUseError


def error_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    configure_error_handling(app)

    @app.get("/domain-error")
    async def domain_error() -> None:
        raise AgentNotFoundError("agent does not exist")

    @app.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/secret-in-use")
    async def secret_in_use() -> None:
        raise SecretInUseError("secret handle is used by a credential")

    @app.get("/validation-error/{item_id}")
    async def validation_error(item_id: int) -> int:
        return item_id

    @app.get("/unhandled-error")
    async def unhandled_error() -> None:
        raise RuntimeError("sensitive implementation detail")

    return app


def test_domain_error_uses_problem_details_and_supplied_request_id() -> None:
    response = TestClient(error_app()).get(
        "/domain-error",
        headers={"X-Request-ID": "request-123"},
    )

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_CONTENT_TYPE
    assert response.headers["x-request-id"] == "request-123"
    assert response.json() == {
        "type": "urn:wardn:error:agent_not_found",
        "title": "Not Found",
        "status": 404,
        "detail": "agent does not exist",
        "instance": "/domain-error",
        "code": "agent_not_found",
        "requestId": "request-123",
    }


def test_http_error_preserves_headers_in_problem_response() -> None:
    response = TestClient(error_app()).get("/http-error")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "http_401"
    assert response.json()["detail"] == "authentication required"
    assert response.json()["requestId"] == response.headers["x-request-id"]


def test_secret_in_use_error_is_a_typed_conflict() -> None:
    response = TestClient(error_app()).get("/secret-in-use")

    assert response.status_code == 409
    assert response.json()["code"] == "secret_in_use"
    assert response.json()["detail"] == "secret handle is used by a credential"


def test_validation_error_has_stable_code_and_safe_details() -> None:
    response = TestClient(error_app()).get("/validation-error/not-an-integer")

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_error"
    assert response.json()["detail"] == "Request validation failed."
    assert response.json()["errors"][0]["type"] == "int_parsing"


def test_invalid_request_id_is_replaced() -> None:
    response = TestClient(error_app()).get(
        "/domain-error",
        headers={"X-Request-ID": "not a safe request id"},
    )

    assert response.headers["x-request-id"] != "not a safe request id"
    assert len(response.headers["x-request-id"]) == 32


def test_unhandled_error_does_not_expose_internal_detail() -> None:
    response = TestClient(error_app(), raise_server_exceptions=False).get("/unhandled-error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_server_error"
    assert response.json()["detail"] == "An unexpected error occurred."
    assert "sensitive" not in response.text
