import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from agent.interfaces.api.main import create_app
from agent.domain.jobs import JobRecord

@pytest.fixture
def client():
    app = create_app()
    
    # Mock JobService
    mock_job_service = MagicMock()
    mock_job = JobRecord(
        job_id="job_123",
        session_id="session_1",
        request_id="req_1",
        tool_call_id="call_1",
        tool_name="bash",
        status="running"
    )
    mock_job_service.get_job.return_value = mock_job
    mock_job_service.read_output.return_value = ("hello world", 11)
    
    app.state.job_service = mock_job_service
    
    return TestClient(app)

def test_api_jobs_get(client):
    response = client.get("/jobs/job_123")
    assert response.status_code == 200
    assert response.json()["job_id"] == "job_123"
    assert response.json()["status"] == "running"

def test_api_jobs_cancel(client):
    response = client.post("/jobs/job_123/cancel", json={"reason": "user stop"})
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

def test_api_jobs_events(client):
    response = client.get("/jobs/job_123/events?offset=0")
    assert response.status_code == 200
    assert response.json()["content"] == "hello world"
    assert response.json()["offset"] == 11
