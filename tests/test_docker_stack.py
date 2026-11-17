"""Tests for Dockerfile and Docker Compose stack configuration.

Ensures Platform role deliverables satisfy architectural constraints:
- Multi-stage Dockerfile with pinned python:3.11-slim base image.
- Non-root user and healthchecks configured.
- Pinned requirements.txt dependencies without floating versions.
- docker-compose.yml defines app, postgres, neo4j services linked on a shared network.
"""

from pathlib import Path
import subprocess
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_file_pinned():
    """Verify requirements.txt exists and all packages are strictly pinned."""
    req_file = REPO_ROOT / "requirements.txt"
    assert req_file.exists(), "requirements.txt must exist"

    lines = [
        line.strip()
        for line in req_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(lines) > 0, "requirements.txt must not be empty"

    for line in lines:
        pkg_spec = line.split("#")[0].strip()
        assert "==" in pkg_spec, f"Package {pkg_spec} is not strictly pinned with '=='"
        assert ">=" not in pkg_spec, f"Package {pkg_spec} must not use '>='"
        assert "<=" not in pkg_spec, f"Package {pkg_spec} must not use '<='"
        assert "~=" not in pkg_spec, f"Package {pkg_spec} must not use '~='"


def test_dockerfile_multi_stage_and_pinned():
    """Verify Dockerfile is multi-stage and uses pinned base image."""
    dockerfile = REPO_ROOT / "Dockerfile"
    assert dockerfile.exists(), "Dockerfile must exist"

    content = dockerfile.read_text()
    assert "FROM python:3.11-slim AS builder" in content
    assert "FROM python:3.11-slim AS runner" in content
    assert "COPY --from=builder" in content
    assert "USER appuser" in content
    assert "HEALTHCHECK" in content
    assert "chainlit" in content
    assert "src/app.py" in content


def test_docker_compose_config_valid():
    """Verify docker compose config validates without error if docker is installed."""
    import shutil
    if shutil.which("docker") is None:
        pytest.skip("docker binary not installed in test environment")
    result = subprocess.run(
        ["docker", "compose", "config"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"docker compose config failed:\n{result.stderr}"


def test_docker_compose_service_definitions():
    """Verify docker-compose.yml structure, dependencies, and network linking."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist"

    data = yaml.safe_load(compose_file.read_text())
    services = data.get("services", {})

    assert "postgres" in services, "postgres service must be defined"
    assert "neo4j" in services, "neo4j service must be defined"
    assert "app" in services, "app service must be defined"

    app_service = services["app"]
    assert "build" in app_service
    assert app_service.get("container_name") == "helpdesk_app"

    # Dependency check
    depends_on = app_service.get("depends_on", {})
    assert "postgres" in depends_on
    assert depends_on["postgres"]["condition"] == "service_healthy"
    assert "neo4j" in depends_on
    assert depends_on["neo4j"]["condition"] == "service_healthy"

    # Network linking check
    networks = data.get("networks", {})
    assert "helpdesk_network" in networks
    assert "helpdesk_network" in services["postgres"].get("networks", [])
    assert "helpdesk_network" in services["neo4j"].get("networks", [])
    assert "helpdesk_network" in app_service.get("networks", [])


def test_chainlit_starter_app_contracts():
    """Verify src/app.py binds session id to thread_id per architecture contract."""
    app_py = REPO_ROOT / "src" / "app.py"
    assert app_py.exists(), "src/app.py must exist"

    content = app_py.read_text()
    assert "thread_id" in content
    assert "cl.context.session.id" in content
