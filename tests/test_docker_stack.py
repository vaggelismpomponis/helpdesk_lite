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
    if result.returncode != 0 and (
        "Access is denied" in result.stderr
        or "permission denied" in result.stderr.lower()
    ):
        pytest.skip("docker access restricted in current environment or sandbox")
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


def test_docker_compose_seed_service_defined():
    """Verify automated seed service and app dependency in docker-compose.yml."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist"

    data = yaml.safe_load(compose_file.read_text())
    services = data.get("services", {})
    assert "seed" in services, "seed service must be defined in compose"

    seed_service = services["seed"]
    assert seed_service.get("container_name") == "helpdesk_seed"
    assert "scripts/seed.py" in " ".join(seed_service.get("command", []))
    assert seed_service.get("restart") == "no"

    app_depends = services["app"].get("depends_on", {})
    assert "seed" in app_depends, "app service must depend on seed service"
    assert app_depends["seed"]["condition"] == "service_completed_successfully"


def test_seed_script_structure_and_contracts():
    """Verify scripts/seed.py coordinates knowledge ingestion and neo4j seeding."""
    seed_script = REPO_ROOT / "scripts" / "seed.py"
    assert seed_script.exists(), "scripts/seed.py must exist"

    content = seed_script.read_text(encoding="utf-8")
    assert "ingest" in content
    assert "seed" in content
    assert "wait_for_services" in content


def test_gitattributes_enforces_lf():
    """Verify .gitattributes exists and enforces LF line endings for cross-platform stability."""
    gitattributes = REPO_ROOT / ".gitattributes"
    assert gitattributes.exists(), ".gitattributes must exist"

    content = gitattributes.read_text()
    assert "text=auto eol=lf" in content
    assert "*.sql text eol=lf" in content
    assert "*.py text eol=lf" in content


def test_cross_platform_compose_ports_configurable():
    """Verify docker-compose.yml ports are parameterizable to prevent port collision friction."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist"

    content = compose_file.read_text()
    assert "POSTGRES_PORT" in content
    assert "APP_PORT" in content
    assert "NEO4J_HTTP_PORT" in content
    assert "NEO4J_BOLT_PORT" in content


def test_env_example_contains_all_service_ports():
    """Verify .env.example specifies all configurable ports for clean-clone reproducibility."""
    env_example = REPO_ROOT / ".env.example"
    assert env_example.exists(), ".env.example must exist"

    content = env_example.read_text()
    assert "POSTGRES_PORT=" in content
    assert "APP_PORT=" in content
    assert "NEO4J_HTTP_PORT=" in content
    assert "NEO4J_BOLT_PORT=" in content


def test_readme_cross_platform_getting_started():
    """Verify README.md includes verified cross-platform commands for Windows, Linux, and macOS."""
    readme = REPO_ROOT / "README.md"
    assert readme.exists(), "README.md must exist"

    content = readme.read_text()
    assert "cp .env.example .env" in content
    assert "Copy-Item .env.example .env" in content
    assert "copy .env.example .env" in content
    assert "CLEAN_CLONE_BENCHMARK.md" in content


def test_app_restart_configuration():
    """Verify app service defines resilient restart policy and graceful shutdown for checkpoint safety."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist"

    data = yaml.safe_load(compose_file.read_text())
    services = data.get("services", {})
    app_service = services.get("app", {})

    assert app_service.get("restart") == "unless-stopped"
    assert app_service.get("stop_grace_period") == "15s"

    volumes = data.get("volumes", {})
    assert "postgres_data" in volumes, "postgres_data volume must be persistent"
    assert "neo4j_data" in volumes, "neo4j_data volume must be persistent"

