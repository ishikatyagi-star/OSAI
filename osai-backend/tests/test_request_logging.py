import json
import logging

from fastapi.testclient import TestClient

from api.main import app


def test_request_logging_emits_correlation_id(caplog):
    with caplog.at_level(logging.INFO, logger="osai.request"):
        response = TestClient(app).post("/mcp", headers={"X-Request-ID": "request-test"}, json={})

    assert response.headers["X-Request-ID"] == "request-test"
    event = json.loads(next(record.message for record in caplog.records if record.name == "osai.request"))
    assert event == {
        "event": "request_completed",
        "request_id": "request-test",
        "method": "POST",
        "path": "/mcp",
        "status_code": 401,
        "duration_ms": event["duration_ms"],
    }
