"""Docker container management for task execution."""

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import tarfile

import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import docker
import docker.errors
import yaml
from docker.models.containers import Container
from pydantic import BaseModel, Field, field_validator

from src.config import (
    SERVICES_WITH_MCP,
)
from src.harness.data_models import TaskContext

logger = logging.getLogger(__name__)


class DockerConnectionPool:
    """Thread-safe connection pool for Docker clients with health monitoring."""

    def __init__(self, max_connections: int = 10, health_check_interval: int = 300):
        """
        Initialize Docker connection pool.

        Args:
            max_connections: Maximum number of connections in the pool
            health_check_interval: Health check interval in seconds
        """
        self.max_connections = max_connections
        self.health_check_interval = health_check_interval
        self._pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created_connections = 0
        self._last_health_check = 0

        # Metrics tracking
        self._metrics = {
            "connections_created": 0,
            "connections_returned": 0,
            "connections_failed": 0,
            "health_checks_performed": 0,
            "health_checks_failed": 0,
            "pool_hits": 0,
            "pool_misses": 0,
        }

        # Pre-populate pool with connections
        for _ in range(min(4, max_connections)):  # Start with 4 connections
            self._create_and_add_connection()

    def _create_and_add_connection(self):
        """Create a new Docker client and add it to the pool."""
        try:
            client = docker.from_env()
            # Perform initial health check
            if self._is_connection_healthy(client):
                self._pool.put(client)
                self._created_connections += 1
                self._metrics["connections_created"] += 1
            else:
                self._metrics["connections_failed"] += 1
                logger.warning("Created Docker connection failed health check")
        except Exception as e:
            self._metrics["connections_failed"] += 1
            logger.warning(f"Failed to create Docker connection: {e}")

    def _is_connection_healthy(self, client: docker.DockerClient) -> bool:
        """
        Check if a Docker connection is healthy.

        Args:
            client: Docker client to check

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Simple ping test
            client.ping()
            return True
        except Exception as e:
            logger.debug(f"Connection health check failed: {e}")
            return False

    def _perform_periodic_health_check(self):
        """Perform periodic health check on all connections in pool."""
        current_time = time.time()
        if current_time - self._last_health_check < self.health_check_interval:
            return

        self._last_health_check = current_time
        self._metrics["health_checks_performed"] += 1

        # Check all connections in pool
        healthy_connections = []
        while not self._pool.empty():
            try:
                client = self._pool.get_nowait()
                if self._is_connection_healthy(client):
                    healthy_connections.append(client)
                else:
                    self._metrics["health_checks_failed"] += 1
                    logger.warning("Removed unhealthy Docker connection from pool")
            except Empty:
                break

        # Return healthy connections to pool
        for client in healthy_connections:
            try:
                self._pool.put_nowait(client)
            except Exception:
                pass  # Pool might be full

    def get_connection(self) -> docker.DockerClient:
        """
        Get a Docker client from the pool with health validation.

        Returns:
            Docker client instance
        """
        # Perform periodic health check
        self._perform_periodic_health_check()

        try:
            # Try to get existing connection
            client = self._pool.get_nowait()

            # Validate connection health before returning
            if self._is_connection_healthy(client):
                self._metrics["pool_hits"] += 1
                return client
            else:
                # Connection is unhealthy, create a new one
                self._metrics["pool_misses"] += 1
                self._metrics["health_checks_failed"] += 1
                logger.warning("Retrieved unhealthy connection, creating new one")
                return self._create_new_connection()

        except Empty:
            # No connections available, create new one if under limit
            self._metrics["pool_misses"] += 1
            with self._lock:
                if self._created_connections < self.max_connections:
                    return self._create_new_connection()
                else:
                    # Wait for a connection to become available
                    return self._pool.get()

    def _create_new_connection(self) -> docker.DockerClient:
        """Create a new connection when pool is empty."""
        try:
            client = docker.from_env()
            if self._is_connection_healthy(client):
                self._created_connections += 1
                self._metrics["connections_created"] += 1
                return client
            else:
                raise RuntimeError("New Docker connection failed health check")
        except Exception as e:
            self._metrics["connections_failed"] += 1
            raise RuntimeError(f"Failed to create new Docker connection: {e}")

    def return_connection(self, client: docker.DockerClient):
        """
        Return a Docker client to the pool with health validation.

        Args:
            client: Docker client to return
        """
        try:
            # Validate connection health before returning to pool
            if self._is_connection_healthy(client):
                self._pool.put_nowait(client)
                self._metrics["connections_returned"] += 1
            else:
                # Don't return unhealthy connections
                self._metrics["health_checks_failed"] += 1
                logger.warning("Not returning unhealthy connection to pool")
        except Exception as e:
            logger.warning(f"Failed to return Docker connection to pool: {e}")

    def get_metrics(self) -> dict[str, Any]:
        """
        Get connection pool metrics.

        Returns:
            Dictionary of metrics
        """
        with self._lock:
            metrics = self._metrics.copy()
            metrics.update(
                {
                    "pool_size": self._pool.qsize(),
                    "max_connections": self.max_connections,
                    "created_connections": self._created_connections,
                    "pool_utilization": (
                        self._pool.qsize() / self.max_connections if self.max_connections > 0 else 0
                    ),
                    "hit_rate": (
                        metrics["pool_hits"] / (metrics["pool_hits"] + metrics["pool_misses"])
                        if (metrics["pool_hits"] + metrics["pool_misses"]) > 0
                        else 0
                    ),
                }
            )
            return metrics

    def close_all(self):
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                client = self._pool.get_nowait()
                client.close()
            except Empty:
                break
            except Exception as e:
                logger.warning(f"Error closing Docker connection: {e}")


# Global connection pool instance
_docker_pool = DockerConnectionPool()


def get_docker_pool() -> DockerConnectionPool:
    """Get the global Docker connection pool."""
    return _docker_pool


def close_docker_pool():
    """Close all connections in the global Docker pool."""
    _docker_pool.close_all()


# Constants - Single source of truth
class DockerConstants:
    """Docker-related constants."""

    CONTAINER_LOGS_PATH = "/logs"
    CONTAINER_AGENT_LOGS_PATH = "/agent-logs"
    CONTAINER_TEST_DIR = "/tests"
    CONTAINER_WORKSPACE = "/app"
    DEFAULT_IMAGE = "python:3.11-slim"
    DEFAULT_TIMEOUT = 1200  # 20 minutes for docker compose up
    BUILD_TIMEOUT = 1800  # 30 minutes for docker compose build (MCP servers npm install)
    CLEANUP_TIMEOUT = 60
    COMMAND_TIMEOUT = 180

    # ECR Configuration
    ECR_REGISTRY = "public.ecr.aws/k4t1e3r5"
    ECR_REPOSITORY = "apex-code"
    PLANE_IMAGE_TAG = "plane-api"
    MATTERMOST_IMAGE_TAG = "mattermost-lightweight"
    ESPOCRM_IMAGE_TAG = "espocrm"
    ZAMMAD_IMAGE_TAG = "zammad-lightweight"
    MEDUSA_IMAGE_TAG = "medusa-lightweight"


class ServicePatchConfig:
    """Configuration for a service that needs entrypoint patching."""

    def __init__(
        self,
        service_name: str,
        image_tag: str,
        entrypoint_script: str,
        patch_label: str,
        compose_env_var: str,
        dockerfile: str | None = None,
    ):
        """
        Initialize service patch configuration.

        Args:
            service_name: Name of the service (e.g., "plane", "medusa")
            image_tag: The image tag constant (e.g., "plane-api")
            entrypoint_script: Name of the entrypoint script file
            patch_label: Docker label used to track if patch was applied
            compose_env_var: Environment variable used in docker-compose (e.g., "${PLANE_IMAGE_TAG}")
            dockerfile: Dockerfile name for local builds (e.g., "Dockerfile.plane-lightweight")
        """
        self.service_name = service_name
        self.image_tag = image_tag
        self.entrypoint_script = entrypoint_script
        self.patch_label = patch_label
        self.compose_env_var = compose_env_var
        self.dockerfile = dockerfile

    @property
    def full_image_tag(self) -> str:
        """Get the full image tag including registry and repository."""
        return f"{DockerConstants.ECR_REGISTRY}/{DockerConstants.ECR_REPOSITORY}:{self.image_tag}"

    @property
    def entrypoint_container_path(self) -> str:
        """Get the path where entrypoint will be placed in container."""
        return f"/{self.entrypoint_script}"

    @classmethod
    def from_dict(cls, service_name: str, data: dict) -> "ServicePatchConfig":
        """Create a ServicePatchConfig from a dictionary (e.g., loaded from YAML)."""
        return cls(
            service_name=service_name,
            image_tag=data["image_tag"],
            entrypoint_script=data["entrypoint_script"],
            patch_label=data["patch_label"],
            compose_env_var=data["compose_env_var"],
            dockerfile=data.get("dockerfile"),
        )


def _load_service_patch_configs() -> dict[str, ServicePatchConfig]:
    """
    Load service patch configurations from external YAML file.

    The config file is located at: src/config/service_patches.yaml

    Returns:
        Dictionary mapping service names to their patch configurations.
    """
    config_path = Path(__file__).parent.parent / "config" / "service_patches.yaml"

    if not config_path.exists():
        logger.warning(f"Service patch config not found at {config_path}, using empty config")
        return {}

    try:
        with open(config_path) as f:
            raw_config = yaml.safe_load(f) or {}

        configs = {}
        for service_name, service_data in raw_config.items():
            try:
                configs[service_name] = ServicePatchConfig.from_dict(service_name, service_data)
            except (KeyError, TypeError) as e:
                logger.warning(f"Invalid config for service '{service_name}': {e}")
                continue

        logger.debug(f"Loaded {len(configs)} service patch configurations")
        return configs

    except Exception as e:
        logger.warning(f"Failed to load service patch config: {e}")
        return {}


# Service patch configurations - loaded from external YAML file
# Config file: src/config/service_patches.yaml
SERVICE_PATCH_CONFIGS: dict[str, ServicePatchConfig] = _load_service_patch_configs()


class DockerEnvironmentVars(BaseModel):
    """Environment variables for Docker Compose - optimized for internal use."""

    task_docker_client_container_name: str
    task_docker_client_image_name: str = DockerConstants.DEFAULT_IMAGE
    container_logs_path: str = DockerConstants.CONTAINER_LOGS_PATH
    container_agent_logs_path: str = DockerConstants.CONTAINER_AGENT_LOGS_PATH
    test_dir: str = DockerConstants.CONTAINER_TEST_DIR
    task_logs_path: str | None = None
    task_agent_logs_path: str | None = None
    git_commit_timestamp: str | None = None

    @field_validator("task_logs_path", "task_agent_logs_path")
    @classmethod
    def validate_paths(cls, v):
        """Validate that paths are absolute if provided."""
        if v is not None and not Path(v).is_absolute():
            raise ValueError(f"Path must be absolute: {v}")
        return v

    def to_env_dict(self) -> dict[str, str]:
        """Convert to environment dictionary for subprocess."""
        return {
            "APEX_TASK_DOCKER_CLIENT_CONTAINER_NAME": self.task_docker_client_container_name,
            "APEX_TASK_DOCKER_CLIENT_IMAGE_NAME": self.task_docker_client_image_name,
            "APEX_CONTAINER_LOGS_PATH": self.container_logs_path,
            "APEX_CONTAINER_AGENT_LOGS_PATH": self.container_agent_logs_path,
            "APEX_TEST_DIR": self.test_dir,
            # ECR Configuration
            "ECR_REGISTRY": DockerConstants.ECR_REGISTRY,
            "ECR_REPOSITORY": DockerConstants.ECR_REPOSITORY,
            "PLANE_IMAGE_TAG": DockerConstants.PLANE_IMAGE_TAG,
            "MATTERMOST_IMAGE_TAG": DockerConstants.MATTERMOST_IMAGE_TAG,
            "ESPOCRM_IMAGE_TAG": DockerConstants.ESPOCRM_IMAGE_TAG,
            "ZAMMAD_IMAGE_TAG": DockerConstants.ZAMMAD_IMAGE_TAG,
            "MEDUSA_IMAGE_TAG": DockerConstants.MEDUSA_IMAGE_TAG,
            **(
                {
                    f"APEX_{k}": v
                    for k, v in {
                        "TASK_LOGS_PATH": self.task_logs_path,
                        "TASK_AGENT_LOGS_PATH": self.task_agent_logs_path,
                    }.items()
                    if v is not None
                }
            ),
        }


class DockerSetupMetadata(BaseModel):
    """Docker setup metadata - durable for serialization and passing around."""

    docker_available: bool
    container_name: str
    docker_info: dict[str, Any]
    docker_compose_found: bool = False
    dockerfile_found: bool = False
    setup_time: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class TaskSetupMetadata(BaseModel):
    """Complete task setup metadata - durable for serialization and passing around."""

    working_dir: str
    use_docker: bool
    setup_time: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    docker_metadata: DockerSetupMetadata | None = None

    class Config:
        arbitrary_types_allowed = True


class ContainerNamingStrategy:
    """Handles container naming conventions."""

    @staticmethod
    def get_possible_names(base_name: str) -> list[str]:
        """Get all possible container names for a given base name."""
        # Docker Compose v2 uses hyphens, v1 uses underscores
        # The service name is "client" in our docker-compose.yaml
        return [
            f"{base_name}-client-1",  # Docker Compose v2
            f"{base_name}_client_1",  # Docker Compose v1
            f"{base_name}.client.1",  # Alternative format
            f"{base_name}-1",  # Fallback without service name
            f"{base_name}_1",  # Fallback without service name
        ]


class DockerComposeManager:
    """Manages Docker Compose containers for task execution with caching."""

    # Generic tracking for service patches - keyed by service name
    _service_patches_built: dict[str, bool] = {}
    _service_patch_locks: dict[str, threading.Lock] = {}

    @classmethod
    def _get_patch_lock(cls, service_name: str) -> threading.Lock:
        """Get or create a lock for a service patch operation."""
        if service_name not in cls._service_patch_locks:
            cls._service_patch_locks[service_name] = threading.Lock()
        return cls._service_patch_locks[service_name]

    @classmethod
    def _is_patch_built(cls, service_name: str) -> bool:
        """Check if a service patch has been built."""
        return cls._service_patches_built.get(service_name, False)

    @classmethod
    def _set_patch_built(cls, service_name: str, built: bool = True) -> None:
        """Mark a service patch as built."""
        cls._service_patches_built[service_name] = built

    def __init__(
        self,
        container_name: str,
        compose_path: Path,
        image_name: str = DockerConstants.DEFAULT_IMAGE,
        no_rebuild: bool = False,
        sessions_logs_path: Path | None = None,
        agent_logs_path: Path | None = None,
        enable_caching: bool = True,
    ):
        """Initialize Docker Compose manager with minimal required parameters."""
        # Validate basic inputs first
        if not container_name or not container_name.strip():
            raise ValueError("Container name cannot be empty")

        if sessions_logs_path and not sessions_logs_path.is_absolute():
            raise ValueError(f"Sessions logs path must be absolute: {sessions_logs_path}")

        if agent_logs_path and not agent_logs_path.is_absolute():
            raise ValueError(f"Agent logs path must be absolute: {agent_logs_path}")

        # Get Docker client from connection pool
        self._client = _docker_pool.get_connection()
        try:
            self._client.ping()  # Verify connection immediately
        except docker.errors.DockerException as e:
            _docker_pool.return_connection(self._client)
            raise RuntimeError(f"Docker not available: {e}")

        # Validate compose file after Docker check
        if not compose_path.exists():
            raise FileNotFoundError(f"Compose file not found: {compose_path}")

        self._container_name = container_name
        self._compose_path = compose_path
        self._image_name = image_name
        self._no_rebuild = no_rebuild
        self._enable_caching = enable_caching
        self._container: Container | None = None
        self._cached_image_tag = None

        # Build environment variables using Pydantic for type safety
        self._env_vars = DockerEnvironmentVars(
            task_docker_client_container_name=container_name,
            task_docker_client_image_name=image_name,
            container_logs_path=DockerConstants.CONTAINER_LOGS_PATH,
            container_agent_logs_path=DockerConstants.CONTAINER_AGENT_LOGS_PATH,
            test_dir=DockerConstants.CONTAINER_TEST_DIR,
            task_logs_path=str(sessions_logs_path.absolute()) if sessions_logs_path else None,
            task_agent_logs_path=str(agent_logs_path.absolute()) if agent_logs_path else None,
        )
        self._env = self._env_vars.to_env_dict()

    def _run_compose(
        self, command: list[str], timeout: int | None = None
    ) -> subprocess.CompletedProcess:
        """Run docker compose command with optimized error handling."""
        # Allow environment variable override for timeout
        actual_timeout = timeout or int(
            os.environ.get("APEX_DOCKER_COMPOSE_TIMEOUT", DockerConstants.DEFAULT_TIMEOUT)
        )

        cmd = [
            "docker",
            "compose",
            "-p",
            self._container_name,
            "-f",
            str(self._compose_path.absolute()),
            *command,
        ]

        try:
            # Merge current environment with task environment to preserve PATH
            env = os.environ.copy()
            env.update(self._env)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=actual_timeout,
                env=env,
                check=False,
            )
            return result
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Docker compose timeout after {actual_timeout}s")
        except Exception as e:
            raise RuntimeError(f"Docker compose failed: {e}")

    def start(self) -> None:
        """Start containers with optimized startup sequence and caching."""
        if self._enable_caching:
            self._try_cached_start()
        else:
            self._normal_start()

        # Wait for services to be healthy
        self._wait_for_services_healthy()

        # Get container using naming strategy
        self._container = self._find_container()

    def _wait_for_services_healthy(self, timeout: int = 800) -> None:
        """Wait for all docker-compose services to be healthy.

        Args:
            timeout: Maximum time to wait in seconds (default: 800 seconds for Plane tasks)
        """

        print(
            f"[DOCKER] Waiting for services to be healthy (timeout: {timeout}s)...",
            flush=True,
        )
        start_time = time.time()

        # Parse docker-compose to get list of services
        try:
            with open(self._compose_path) as f:
                compose_config = yaml.safe_load(f) or {}

            services = list(compose_config.get("services", {}).keys())
            if not services:
                print("[DOCKER] No services found in docker-compose", flush=True)
                return

            print(
                f"[DOCKER] Found {len(services)} services: {', '.join(services)}",
                flush=True,
            )

            # Check which services have health checks
            services_with_health = []
            for service_name in services:
                service_config = compose_config["services"][service_name]
                if "healthcheck" in service_config:
                    services_with_health.append(service_name)

            if not services_with_health:
                print(
                    "[DOCKER] No services have health checks defined, skipping health wait",
                    flush=True,
                )
                return

            print(
                f"[DOCKER] Waiting for {len(services_with_health)} services with health checks: {', '.join(services_with_health)}",
                flush=True,
            )

            # Wait for each service to be healthy
            healthy_services = set()
            check_interval = 5  # Check every 5 seconds

            while time.time() - start_time < timeout:
                # Get service status
                result = self._run_compose(["ps", "--format", "json"])
                if result.returncode == 0:
                    try:
                        # Parse JSON output (one JSON object per line)
                        for line in result.stdout.strip().split("\n"):
                            if line:
                                container_info = json.loads(line)
                                service = container_info.get("Service")
                                health = container_info.get("Health", "")

                                if service in services_with_health:
                                    if health == "healthy":
                                        if service not in healthy_services:
                                            healthy_services.add(service)
                                            elapsed = time.time() - start_time
                                            print(
                                                f"[DOCKER] ✅ {service} is healthy ({elapsed:.1f}s)",
                                                flush=True,
                                            )

                        # Check if all services are healthy
                        if len(healthy_services) == len(services_with_health):
                            elapsed = time.time() - start_time
                            print(
                                f"[DOCKER] ✅ All services healthy after {elapsed:.1f}s",
                                flush=True,
                            )
                            return

                    except json.JSONDecodeError:
                        pass  # Continue waiting

                # Wait before next check
                time.sleep(check_interval)

            # Timeout reached
            elapsed = time.time() - start_time
            unhealthy = set(services_with_health) - healthy_services
            if unhealthy:
                print(
                    f"[DOCKER] ⚠️  Timeout after {elapsed:.1f}s. Unhealthy services: {', '.join(unhealthy)}",
                    flush=True,
                )
                logger.warning(f"Services not healthy after {elapsed:.1f}s: {unhealthy}")
            else:
                print(f"[DOCKER] All services healthy after {elapsed:.1f}s", flush=True)

        except Exception as e:
            logger.warning(f"Failed to check service health: {e}")
            print(f"[DOCKER] ⚠️  Could not verify service health: {e}", flush=True)

    def _inject_default_healthchecks(self) -> None:
        """Inject default healthchecks for common services if not present."""

        # Default healthchecks for common services
        DEFAULT_HEALTHCHECKS = {
            "espocrm": {
                "test": [
                    "CMD-SHELL",
                    "wget --quiet --tries=1 --spider http://127.0.0.1:80/ || exit 1",
                ],
                "interval": "15s",
                "timeout": "10s",
                "retries": 20,
                "start_period": "240s",
            },
            "medusa": {
                "test": ["CMD-SHELL", "curl -f http://127.0.0.1:9000/ || exit 1"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 10,
                "start_period": "120s",
            },
            "zammad": {
                "test": ["CMD-SHELL", "curl -f http://127.0.0.1:8080/ || exit 1"],
                "interval": "30s",
                "timeout": "10s",
                "retries": 3,
                "start_period": "120s",
            },
            "localstack": {
                "test": ["CMD-SHELL", "awslocal s3 ls >/dev/null 2>&1 || exit 1"],
                "interval": "15s",
                "timeout": "10s",
                "retries": 20,
                "start_period": "180s",
            },
            "mailhog": {
                "test": [
                    "CMD-SHELL",
                    "wget --quiet --tries=1 --spider http://127.0.0.1:8025/ || exit 1",
                ],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
                "start_period": "10s",
            },
        }

        try:
            # Read current compose file
            with open(self._compose_path) as f:
                compose_config = yaml.safe_load(f) or {}

            if "services" not in compose_config:
                return

            modified = False
            for service_name, service_config in compose_config["services"].items():
                # Special handling for Localstack: enforce wget-free awslocal probe
                if service_name == "localstack":
                    desired = DEFAULT_HEALTHCHECKS["localstack"]
                    current = service_config.get("healthcheck")
                    current_test = current.get("test") if isinstance(current, dict) else None
                    test_str = ""
                    if current_test:
                        if isinstance(current_test, list):
                            test_str = " ".join(str(part) for part in current_test)
                        else:
                            test_str = str(current_test)
                    if not current or "awslocal" not in test_str:
                        service_config["healthcheck"] = desired
                        modified = True
                        logger.info("Replaced localstack healthcheck with awslocal probe")
                    # Ensure localstack runs without auth requirement
                    env = service_config.get("environment", [])
                    env_key = "LOCALSTACK_ACKNOWLEDGE_ACCOUNT_REQUIREMENT"
                    if isinstance(env, list):
                        if not any(env_key in str(e) for e in env):
                            env.append(f"{env_key}=1")
                            service_config["environment"] = env
                            modified = True
                    elif isinstance(env, dict):
                        if env_key not in env:
                            env[env_key] = "1"
                            modified = True
                    continue

                # Skip if service already has healthcheck
                if "healthcheck" in service_config:
                    continue

                # Add default healthcheck if we have one for this service
                if service_name in DEFAULT_HEALTHCHECKS:
                    service_config["healthcheck"] = DEFAULT_HEALTHCHECKS[service_name]
                    modified = True
                    logger.info(f"Injected default healthcheck for service: {service_name}")

            # Write back if modified
            if modified:
                with open(self._compose_path, "w") as f:
                    yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)
                logger.info("Injected default healthchecks into docker-compose.yaml")

        except Exception as e:
            logger.warning(f"Failed to inject default healthchecks: {e}")

    def _normal_start(self) -> None:
        """Normal startup sequence without caching."""
        # Ensure patched service images if needed before any builds
        self._ensure_all_entrypoint_patches()

        # Inject default healthchecks if missing
        self._inject_default_healthchecks()

        # Build if needed (single command) - use longer timeout for npm builds
        if not self._no_rebuild:
            result = self._run_compose(["build"], timeout=DockerConstants.BUILD_TIMEOUT)
            if result.returncode != 0:
                raise RuntimeError(f"Build failed: {result.stderr}")

        # Start containers
        result = self._run_compose(["up", "-d"])
        if result.returncode != 0:
            raise RuntimeError(f"Start failed: {result.stderr}")

    def _try_cached_start(self) -> None:
        """Try to start using cached image, fallback to normal start."""
        try:
            # Check if we have a cached image
            cached_tag = self._get_cached_image_tag()
            if cached_tag and self._image_exists(cached_tag):
                logger.info(f"Using cached image: {cached_tag}")
                # Use cached image
                self._normal_start()
                return
        except Exception as e:
            logger.warning(f"Failed to use cached image: {e}")

        # Fallback to normal start
        self._normal_start()

        # Cache the image after successful start
        self._cache_current_image()

    def _get_cached_image_tag(self) -> str | None:
        """Get the cached image tag for this task."""
        if not self._cached_image_tag:
            # Generate a cache tag based on task directory and compose file
            task_dir = self._compose_path.parent
            cache_key = f"{task_dir.name}_{self._container_name}_cache"
            self._cached_image_tag = f"apex-cache:{cache_key}"
        return self._cached_image_tag

    def _image_exists(self, image_tag: str) -> bool:
        """Check if an image exists locally."""
        try:
            self._client.images.get(image_tag)
            return True
        except docker.errors.ImageNotFound:
            return False

    def _cache_current_image(self) -> None:
        """Cache the current container image with disk space management."""
        try:
            container = self.get_container()
            if container:
                cached_tag = self._get_cached_image_tag()

                # Check disk space before caching
                if not self._check_disk_space():
                    logger.warning("Insufficient disk space, skipping cache")
                    return

                # Perform cache cleanup if needed
                self._cleanup_old_caches()

                # Commit container to image
                image = self._client.images.commit(container, tag=cached_tag)
                logger.info(f"Cached image: {cached_tag}")

                # Update cache metadata
                self._update_cache_metadata(cached_tag)

        except Exception as e:
            logger.warning(f"Failed to cache image: {e}")

    def _check_disk_space(self, min_free_gb: float = 2.0) -> bool:
        """
        Check if there's enough disk space for caching.

        Args:
            min_free_gb: Minimum free space required in GB

        Returns:
            True if enough space, False otherwise
        """
        try:
            free_bytes = shutil.disk_usage("/").free
            free_gb = free_bytes / (1024**3)
            return free_gb >= min_free_gb
        except Exception as e:
            logger.warning(f"Failed to check disk space: {e}")
            return True  # Assume OK if we can't check

    def _cleanup_old_caches(self) -> None:
        """Clean up old cached images to free space."""
        try:
            # Get all apex-cache images
            cache_images = self._client.images.list(filters={"reference": "apex-cache:*"})

            if len(cache_images) <= 5:  # Keep at least 5 cached images
                return

            # Sort by creation time (oldest first)
            cache_images.sort(key=lambda x: x.attrs.get("Created", "0"))

            # Remove oldest images (keep newest 5)
            images_to_remove = cache_images[:-5]

            for image in images_to_remove:
                try:
                    self._client.images.remove(image.id, force=True)
                    logger.info(
                        f"Removed old cache image: {image.tags[0] if image.tags else image.id[:12]}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to remove cache image {image.id}: {e}")

        except Exception as e:
            logger.warning(f"Cache cleanup failed: {e}")

    def _update_cache_metadata(self, cached_tag: str) -> None:
        """Update cache metadata for tracking."""
        try:
            # Create cache metadata file
            cache_dir = Path.home() / ".apex" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            metadata_file = cache_dir / "cache_metadata.json"

            # Load existing metadata
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
            else:
                metadata = {"cached_images": []}

            # Add new cache entry
            cache_entry = {
                "tag": cached_tag,
                "created_at": time.time(),
                "task_dir": str(self._compose_path.parent),
                "container_name": self._container_name,
            }

            # Remove old entries for same task
            metadata["cached_images"] = [
                entry
                for entry in metadata["cached_images"]
                if entry.get("task_dir") != str(self._compose_path.parent)
            ]

            # Add new entry
            metadata["cached_images"].append(cache_entry)

            # Save metadata
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

        except Exception as e:
            logger.warning(f"Failed to update cache metadata: {e}")

    # -------------------------------------------------------------------------
    # Generic Service Entrypoint Patching Methods
    # -------------------------------------------------------------------------

    def _compose_uses_service(self, config: ServicePatchConfig) -> bool:
        """Check if compose file references a specific service image.

        Args:
            config: Service patch configuration

        Returns:
            True if compose uses this service, False otherwise
        """
        # Check cache first
        cache_key = f"_compose_uses_{config.service_name}"
        if hasattr(self, cache_key):
            return getattr(self, cache_key)

        try:
            with open(self._compose_path) as f:
                compose_data = yaml.safe_load(f) or {}
            services = (compose_data.get("services") or {}).values()
            for service in services:
                image = str(service.get("image", "")).strip()
                if not image:
                    continue
                # Check for both env var pattern and direct image tag
                if config.compose_env_var in image or config.image_tag in image:
                    setattr(self, cache_key, True)
                    return True
        except Exception as e:
            logger.debug(f"Failed to inspect compose for {config.service_name} service: {e}")

        setattr(self, cache_key, False)
        return False

    def _get_entrypoint_hash(self, config: ServicePatchConfig) -> str:
        """Hash the entrypoint script so label changes force rebuild when file changes.

        Args:
            config: Service patch configuration

        Returns:
            SHA256 hash of the entrypoint file, or empty string on error
        """
        try:
            # __file__ is src/utils/docker_manager.py, so parents[2] is integration/
            repo_root = Path(__file__).resolve().parents[2]
            entrypoint_path = (
                repo_root / "tasks" / "shared" / "dockerfiles" / config.entrypoint_script
            )
            return hashlib.sha256(entrypoint_path.read_bytes()).hexdigest()
        except Exception as exc:
            logger.debug(f"Failed to hash {config.service_name} entrypoint: {exc}")
            return ""

    def _is_image_patched(self, config: ServicePatchConfig, entrypoint_hash: str) -> bool:
        """Check if the locally tagged image already includes our patched entrypoint.

        Args:
            config: Service patch configuration
            entrypoint_hash: Hash of the current entrypoint file

        Returns:
            True if image is already patched with matching hash, False otherwise
        """
        try:
            image = self._client.images.get(config.full_image_tag)
        except docker.errors.ImageNotFound:
            return False
        except Exception as exc:
            logger.debug(f"Failed to inspect {config.service_name} image for patch: {exc}")
            return False

        labels = {}
        try:
            labels = image.labels or image.attrs.get("Config", {}).get("Labels", {}) or {}
        except Exception as exc:
            logger.debug(f"Failed to read labels on {config.service_name} image: {exc}")

        label_value = labels.get(config.patch_label)
        # If we couldn't compute the hash, fall back to rejecting old labels
        if not entrypoint_hash:
            return False
        return label_value == entrypoint_hash

    def _ensure_service_entrypoint_patch(self, config: ServicePatchConfig) -> None:
        """Ensure a service image locally has the patched entrypoint."""
        # Skip if compose doesn't use this service
        if not self._compose_uses_service(config):
            return

        # Check if already built (fast path without lock)
        if DockerComposeManager._is_patch_built(config.service_name):
            return

        entrypoint_hash = self._get_entrypoint_hash(config)

        # Check if image already has correct patch
        if self._is_image_patched(config, entrypoint_hash):
            DockerComposeManager._set_patch_built(config.service_name, True)
            return

        # Acquire lock for this service
        with DockerComposeManager._get_patch_lock(config.service_name):
            # Double-check after acquiring lock
            if DockerComposeManager._is_patch_built(config.service_name):
                return

            if self._is_image_patched(config, entrypoint_hash):
                DockerComposeManager._set_patch_built(config.service_name, True)
                return

            # Build the image from local Dockerfile (no ECR pulls)
            # __file__ is src/utils/docker_manager.py, so parents[2] is integration/
            repo_root = Path(__file__).resolve().parents[2]
            dockerfiles_dir = repo_root / "tasks" / "shared" / "dockerfiles"

            # Dockerfile is required - we don't pull from ECR
            if not config.dockerfile:
                logger.warning(f"Skipping {config.service_name} - no dockerfile configured")
                DockerComposeManager._set_patch_built(config.service_name, True)
                return

            dockerfile_path = dockerfiles_dir / config.dockerfile
            if not dockerfile_path.exists():
                logger.warning(
                    f"Skipping {config.service_name} - dockerfile not found: {dockerfile_path}"
                )
                DockerComposeManager._set_patch_built(config.service_name, True)
                return

            try:
                logger.info(f"Building {config.service_name} from {config.dockerfile}")
                build_cmd = [
                    "docker",
                    "build",
                    "-f",
                    str(dockerfile_path),
                    "-t",
                    config.full_image_tag,
                    "--label",
                    f"{config.patch_label}={entrypoint_hash or 'unknown'}",
                    str(repo_root / "tasks"),  # Context is tasks/ dir
                ]

                result = subprocess.run(build_cmd, capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr or result.stdout)

                DockerComposeManager._set_patch_built(config.service_name, True)
                logger.info(f"Built {config.service_name} image locally")
            except Exception as e:
                logger.warning(f"Failed to build {config.service_name} image: {e}")

    def _ensure_all_entrypoint_patches(self) -> None:
        """Ensure all configured services have their entrypoint patches applied.

        This iterates through all services defined in SERVICE_PATCH_CONFIGS
        and applies patches as needed.
        """
        for config in SERVICE_PATCH_CONFIGS.values():
            self._ensure_service_entrypoint_patch(config)

    def cleanup_all_caches(self) -> None:
        """Clean up all cached images."""
        try:
            # Get all apex-cache images
            cache_images = self._client.images.list(filters={"reference": "apex-cache:*"})

            for image in cache_images:
                try:
                    self._client.images.remove(image.id, force=True)
                    logger.info(
                        f"Removed cache image: {image.tags[0] if image.tags else image.id[:12]}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to remove cache image {image.id}: {e}")

            # Clean up metadata file
            try:
                cache_dir = Path.home() / ".apex" / "cache"
                metadata_file = cache_dir / "cache_metadata.json"
                if metadata_file.exists():
                    metadata_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to clean up cache metadata: {e}")

        except Exception as e:
            logger.warning(f"Cache cleanup failed: {e}")

    def _find_container(self) -> Container:
        """Find the container using multiple naming conventions."""
        # First try the exact container name that was set in env vars
        exact_name = self._env_vars.task_docker_client_container_name
        try:
            return self._client.containers.get(exact_name)
        except docker.errors.NotFound:
            pass

        # Then try common patterns
        possible_names = ContainerNamingStrategy.get_possible_names(self._container_name)

        for name in possible_names:
            try:
                return self._client.containers.get(name)
            except docker.errors.NotFound:
                continue

        # Last resort: find by compose project label
        try:
            containers = self._client.containers.list(
                filters={
                    "label": f"com.docker.compose.project={self._container_name}",
                    "status": "running",
                }
            )
            if containers:
                return containers[0]
        except Exception:
            pass

        raise RuntimeError(
            f"Container not found. Tried exact name: {exact_name}, patterns: {possible_names}"
        )

    def get_required_mcp_requirements(self) -> list[str]:
        """Derive required MCP requirement tokens from docker-compose services.

        Derived exclusively from compose services using SERVICES_WITH_MCP.
        """
        # Derived from compose services
        try:
            with open(self._compose_path) as f:
                compose_data = yaml.safe_load(f) or {}
        except Exception:
            return []

        services = (compose_data or {}).get("services", {}) or {}

        requirements: list[str] = []
        for service_name in services.keys():
            token = SERVICES_WITH_MCP.get(service_name)
            if token and token not in requirements:
                requirements.append(token)

        return requirements

    def get_container(self) -> Container | None:
        """Get the container if it exists."""
        try:
            return self._container
        except AttributeError:
            return None

    def exec_command(
        self, command: str, timeout: int = 30, working_dir: str | None = None
    ) -> dict[str, Any]:
        """Execute a command in the container."""
        if not hasattr(self, "_container") or not self._container:
            raise RuntimeError("Container not available")

        try:
            # Prepare exec command
            exec_cmd = f"cd {working_dir} && {command}" if working_dir else command

            # Execute in container
            result = self._container.exec_run(
                cmd=["sh", "-c", exec_cmd], stdout=True, stderr=True, demux=True
            )

            stdout, stderr = result.output

            return {
                "exit_code": result.exit_code,
                "stdout": stdout.decode("utf-8") if stdout else "",
                "stderr": stderr.decode("utf-8") if stderr else "",
            }

        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    def stop(self) -> None:
        """Stop containers with consistent error handling."""
        try:
            self._run_compose(["down"], timeout=DockerConstants.CLEANUP_TIMEOUT)
        except Exception as e:
            logger.warning(f"Stop failed: {e}")
        finally:
            # Return connection to pool
            if hasattr(self, "_client") and self._client:
                _docker_pool.return_connection(self._client)

    def cleanup(self) -> None:
        """Clean up containers and volumes with consistent error handling."""
        try:
            self._run_compose(
                ["down", "-v", "--remove-orphans"],
                timeout=DockerConstants.CLEANUP_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
        finally:
            # Return connection to pool
            if hasattr(self, "_client") and self._client:
                _docker_pool.return_connection(self._client)

    def __del__(self):
        """Ensure connection is returned to pool when object is destroyed."""
        if hasattr(self, "_client") and self._client:
            try:
                _docker_pool.return_connection(self._client)
            except Exception:
                pass  # Ignore errors during cleanup

    @property
    def container(self) -> Container:
        """Get the client container."""
        if self._container is None:
            raise RuntimeError("Container not started")
        return self._container

    def copy_files(
        self, paths: list[Path], dest_dir: str = DockerConstants.CONTAINER_WORKSPACE
    ) -> None:
        """Copy files to container efficiently using single tar archive."""
        if not paths:
            return

        # Validate paths
        valid_paths = [p for p in paths if p.exists()]
        if not valid_paths:
            logger.warning("No valid paths to copy")
            return

        # Create single tar archive for all files
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w", dereference=True) as tar:
            for path in valid_paths:
                try:
                    # Dereference symlinks to avoid broken relative symlinks
                    tar.add(path, arcname=path.name)
                except (OSError, tarfile.TarError) as e:
                    # Skip files that can't be added (e.g., broken symlinks)
                    logger.warning(f"Skipping file that can't be archived: {path} - {e}")
                    continue

        tar_stream.seek(0)

        try:
            self.container.put_archive(dest_dir, tar_stream.getvalue())
        except Exception as e:
            raise RuntimeError(f"Copy failed: {e}")

    def execute(
        self, command: list[str], timeout: int = DockerConstants.COMMAND_TIMEOUT
    ) -> subprocess.CompletedProcess:
        """Execute command in container with optimized error handling."""
        try:
            result = self.container.exec_run(command, demux=True)
            stdout, stderr = result.output

            return subprocess.CompletedProcess(
                args=command,
                returncode=result.exit_code,
                stdout=stdout.decode("utf-8") if stdout else "",
                stderr=stderr.decode("utf-8") if stderr else "",
            )
        except Exception as e:
            raise RuntimeError(f"Command execution failed: {e}")

    def is_healthy(self) -> bool:
        """Check container health efficiently."""
        try:
            self._container.reload()
            return self._container.status == "running"
        except Exception:
            return False

    def get_logs(self, tail: int = 100) -> str:
        """Get container logs with consistent error handling."""
        try:
            return self._container.logs(tail=tail).decode("utf-8")
        except Exception as e:
            logger.warning(f"Log retrieval failed: {e}")
            return f"Log retrieval failed: {e}"

    def has_tool_containers(self, task_context: TaskContext) -> bool:
        """Check if the task has tool containers by examining the docker-compose.yaml file."""
        compose_path = task_context.task_dir / "docker-compose.yaml"

        with open(compose_path) as f:
            compose_data = yaml.safe_load(f)
            services = compose_data.get("services", {})

            # Check for known MCP-related services via config mapping
            has_tool_services = any(service in services for service in SERVICES_WITH_MCP.keys())
            return has_tool_services


@contextmanager
def docker_environment(
    task_context: TaskContext,
    working_dir: Path,
    sessions_logs_path: Path | None = None,
    agent_logs_path: Path | None = None,
    no_rebuild: bool = False,
    cleanup: bool = True,
) -> Generator[DockerComposeManager, None, None]:
    """Context manager for Docker environment lifecycle."""
    compose_path = task_context.task_dir / "docker-compose.yaml"
    if not compose_path.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_path}")

    # Generate unique container name - using underscores for compatibility
    task_id_safe = task_context.task_id.replace("-", "_")
    # Use high precision timestamp and thread ID to ensure uniqueness across parallel executions

    timestamp_ns = time.time_ns()  # Nanosecond precision
    thread_id = threading.current_thread().ident
    unique_suffix = f"{timestamp_ns}_{thread_id}"
    project_name = f"apex_{task_id_safe}_{unique_suffix}"
    container_name = f"apex_task_{task_id_safe}_{unique_suffix}"

    manager = DockerComposeManager(
        container_name=project_name,  # Use project name for compose
        compose_path=compose_path,
        no_rebuild=no_rebuild,
        sessions_logs_path=sessions_logs_path,
        agent_logs_path=agent_logs_path,
    )
    # Override the container name env var to use simpler name
    manager._env_vars.task_docker_client_container_name = container_name
    manager._env = manager._env_vars.to_env_dict()

    try:
        manager.start()

        # Copy task files efficiently
        if task_context.files:
            manager.copy_files(task_context.files)

        yield manager

    finally:
        if cleanup:
            manager.cleanup()
        else:
            manager.stop()


def check_docker() -> bool:
    """Check if Docker is available."""
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


def get_docker_info() -> dict[str, Any]:
    """Get Docker system information."""
    try:
        client = docker.from_env()
        info = client.info()
        return {
            "available": True,
            "version": info.get("ServerVersion", "unknown"),
            "containers": info.get("Containers", 0),
            "images": info.get("Images", 0),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
