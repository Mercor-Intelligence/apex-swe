"""
Docker execution utilities for running tests in containers.

This module provides functions for:
- Running commands in Docker containers
- Managing container lifecycle (pull, run, cleanup)
- Applying patches and capturing test output

Note: This module intentionally does NOT import from eval_runner to maintain
independence. The parser module can be used standalone without the eval_runner.
Git config values here mirror those in eval_runner.config.CONTAINER_CONFIG.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import hashlib

# Use standard logging instead of custom logger since this is in parser module
logger = logging.getLogger(__name__)

# Default git config values (mirrors eval_runner.config.CONTAINER_CONFIG)
_GIT_USER_EMAIL = "eval@apexcode.local"
_GIT_USER_NAME = "Eval Runner"
_DEFAULT_WORKDIR = "/app/repo"


@dataclass
class DockerRunResult:
    """Result from running a command in Docker."""

    exit_code: int
    stdout: str
    stderr: str
    success: bool

    @property
    def output(self) -> str:
        """Combined stdout and stderr."""
        return f"{self.stdout}\n{self.stderr}"


class DockerRunner:
    """Utility class for running commands in Docker containers."""

    def __init__(
        self,
        image: str,
        workdir: str = "/app/repo",
        timeout: int = 900,
    ):
        """
        Initialize DockerRunner.

        Args:
            image: Docker image name/tag to use
            workdir: Working directory inside the container
            timeout: Timeout in seconds for commands (default: 15 minutes)
        """
        self.image = image
        self.workdir = workdir
        self.timeout = timeout

    def image_exists_locally(self) -> bool:
        """Check if the Docker image exists locally."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout checking if image exists: {self.image}")
            return False
        except FileNotFoundError:
            logger.error("Docker not found in PATH")
            return False
        except Exception as e:
            logger.warning(f"Error checking image existence: {e}")
            return False

    def build_from_compose(self, compose_path: str | Path) -> DockerRunResult:
        """
        Build the Docker image from a compose.yaml file.
        
        Args:
            compose_path: Path to the compose.yaml file
            
        Returns:
            DockerRunResult with build status
        """
        compose_path = Path(compose_path)
        if not compose_path.exists():
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr=f"Compose file not found: {compose_path}",
                success=False,
            )
        
        try:
            # Build using docker compose with stdin disabled to prevent hanging
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose_path), "build"],
                capture_output=True,
                text=True,
                timeout=900,  # 15 minutes for build
                cwd=compose_path.parent,
                stdin=subprocess.DEVNULL,  # Prevent hanging on prompts
            )
            return DockerRunResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                success=result.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout building image from {compose_path} (15 min limit)")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr="Timeout building image (15 min limit)",
                success=False,
            )
        except FileNotFoundError:
            logger.error("Docker not found in PATH")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr="Docker not found in PATH",
                success=False,
            )
        except Exception as e:
            logger.error(f"Error building image: {e}")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                success=False,
            )

    def pull_image(self, compose_path: str | Path | None = None) -> DockerRunResult:
        """
        Ensure the Docker image is available (check local, then build from compose, then pull).

        Args:
            compose_path: Optional path to compose.yaml for auto-building
            
        Returns:
            DockerRunResult with status
        """
        # First check if image exists locally
        if self.image_exists_locally():
            return DockerRunResult(
                exit_code=0,
                stdout=f"Image {self.image} exists locally",
                stderr="",
                success=True,
            )

        # Try to build from compose if provided
        if compose_path:
            compose_path = Path(compose_path)
            if compose_path.exists():
                logger.info(f"Building image from {compose_path}...")
                build_result = self.build_from_compose(compose_path)
                if build_result.success:
                    return build_result
                # If build failed, try pull as fallback
                logger.warning(f"Build failed, trying to pull: {build_result.stderr[:200]}")

        # Try to pull from registry
        try:
            result = subprocess.run(
                ["docker", "pull", self.image],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes for pull
                stdin=subprocess.DEVNULL,
            )
            return DockerRunResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                success=result.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout pulling image: {self.image}")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr="Timeout pulling image (10 min limit)",
                success=False,
            )
        except Exception as e:
            logger.error(f"Error pulling image: {e}")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                success=False,
            )

    def run_command(
        self,
        command: str,
        volumes: Optional[dict[str, str]] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> DockerRunResult:
        """
        Run a command in the Docker container.

        Args:
            command: Bash command to execute
            volumes: Dict of host_path -> container_path for bind mounts
            env_vars: Environment variables to set

        Returns:
            DockerRunResult with command output
        """
        docker_cmd = ["docker", "run", "--rm"]

        # Add volume mounts
        if volumes:
            for host_path, container_path in volumes.items():
                docker_cmd.extend(["-v", f"{host_path}:{container_path}"])

        # Add environment variables
        if env_vars:
            for key, value in env_vars.items():
                docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.extend([self.image, "bash", "-c", command])

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                stdin=subprocess.DEVNULL,
            )
            return DockerRunResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                success=result.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"Command timeout after {self.timeout}s")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr=f"Timeout after {self.timeout}s",
                success=False,
            )
        except Exception as e:
            logger.error(f"Error running command in Docker: {e}")
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                success=False,
            )

    def run_with_patches(
        self,
        test_command: str,
        test_patch: str,
        golden_patch: Optional[str] = None,
        agent_diff: Optional[str] = None,
        bind_mount_results: bool = True,
        test_framework: Optional[str] = None,
        test_metadata_path: Optional[str | Path] = None,
    ) -> DockerRunResult:
        """
        Run tests with patches applied.

        Uses `tee` to capture ALL stdout/stderr to a file - this ensures we get
        both terminal output AND structured output (JSON/XML) for frameworks
        that output to stdout (like Go's -json flag).

        Args:
            test_command: Test command to execute
            test_patch: Test patch content to apply
            golden_patch: Optional golden patch content to apply
            agent_diff: Optional agent diff to apply before tests
            bind_mount_results: Whether to bind mount a results directory
            test_framework: Optional test framework name for adding output flags
            test_metadata_path: Optional path to test_metadata.json to mount

        Returns:
            DockerRunResult with test output (terminal + structured files combined)
        """
        from .frameworks import get_test_command_with_output
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Write patches to files
            test_patch_file = tmpdir_path / "test.patch"
            test_patch_file.write_text(test_patch)

            volumes = {
                str(test_patch_file): "/tmp/test.patch:ro",
            }
            
            # Mount test_metadata.json if provided (makes it available inside container)
            if test_metadata_path:
                metadata_path = Path(test_metadata_path)
                if metadata_path.exists():
                    volumes[str(metadata_path)] = "/app/test_metadata.json:ro"

            if golden_patch:
                golden_patch_file = tmpdir_path / "golden.patch"
                golden_patch_file.write_text(golden_patch)
                volumes[str(golden_patch_file)] = "/tmp/golden.patch:ro"

            if agent_diff:
                agent_diff_file = tmpdir_path / "agent.patch"
                agent_diff_file.write_text(agent_diff)
                volumes[str(agent_diff_file)] = "/tmp/agent.patch:ro"

            # Always create results directory for output capture
            results_dir = tmpdir_path / "test-results"
            results_dir.mkdir()
            volumes[str(results_dir)] = "/workspace/test-results"

            # Enhance test command with framework-specific output flags
            enhanced_command = test_command
            if test_framework:
                enhanced_command = get_test_command_with_output(test_command, test_framework)

            # Build command sequence with tee for output capture
            cmd_parts = [
                f"cd {self.workdir}",
                "",
                "# Set Go module mode only if not already configured in the container",
                'export GO111MODULE="${GO111MODULE:-on}"',
                'export GOPROXY="${GOPROXY:-https://proxy.golang.org,direct}"',
                "",
                "# Configure git",
                f'git config --global user.email "{_GIT_USER_EMAIL}"',
                f'git config --global user.name "{_GIT_USER_NAME}"',
                f'git config --global --add safe.directory {self.workdir}',
                "",
                "# Create results directory",
                "mkdir -p /workspace/test-results",
                "",
            ]

            # Apply test patch FIRST to establish test files
            cmd_parts.extend([
                "# Apply test patch first (establish test files)",
                "git apply /tmp/test.patch 2>/dev/null || patch -p1 < /tmp/test.patch || true",
                "",
            ])

            # Apply golden patch if provided (implementation fixes)
            if golden_patch:
                cmd_parts.extend([
                    "# Apply golden patch",
                    "git apply /tmp/golden.patch 2>/dev/null || patch -p1 < /tmp/golden.patch || true",
                    "",
                ])

            # Apply agent diff if provided
            if agent_diff:
                cmd_parts.extend([
                    "# Apply agent diff",
                    "git apply /tmp/agent.patch 2>/dev/null || patch -p1 < /tmp/agent.patch || true",
                    "",
                ])

            # Run tests with tee to capture ALL output (stdout + stderr) to file
            # Using PIPESTATUS to preserve the test command's exit code
            cmd_parts.extend([
                "# Run tests and capture ALL output via tee",
                f"({enhanced_command}) 2>&1 | tee /workspace/test-results/output.txt",
                "_test_exit_code=${PIPESTATUS[0]}",
                "",
                "# Copy test results from common framework locations",
                "# Gradle test results",
                "find . -path '*/build/test-results/*/TEST-*.xml' -exec cp {} /workspace/test-results/ \\; 2>/dev/null || true",
                "# Maven Surefire reports",
                "find . -path '*/target/surefire-reports/TEST-*.xml' -exec cp {} /workspace/test-results/ \\; 2>/dev/null || true",
                "# Any JUnit XML files",
                "find . -name 'TEST-*.xml' ! -path '*/.git/*' ! -path '*/node_modules/*' -exec cp {} /workspace/test-results/ \\; 2>/dev/null || true",
                "# Jest/Vitest JSON results",
                "find . -name '*-results.json' ! -path '*/.git/*' ! -path '*/node_modules/*' -exec cp {} /workspace/test-results/ \\; 2>/dev/null || true",
                "# cargo-nextest junit.xml",
                "find . -name 'junit.xml' ! -path '*/.git/*' ! -path '*/target/debug/*' -exec cp {} /workspace/test-results/ \\; 2>/dev/null || true",
                "",
                "# Exit with test command's exit code",
                "exit $_test_exit_code",
            ])

            full_command = "\n".join(cmd_parts)
            result = self.run_command(full_command, volumes=volumes)
            
            # Read captured output from the tee'd file
            output_file = results_dir / "output.txt"
            if output_file.exists():
                try:
                    terminal_output = output_file.read_text()
                except OSError as e:
                    logger.warning(f"Failed to read output file: {e}")
                    terminal_output = result.stdout
            else:
                # Fallback to captured output if file wasn't created
                terminal_output = result.stdout
            
            # Read structured result files (XML, JSON) from the bind-mounted directory
            result_files_content = _read_result_files(results_dir)
            
            # Combine terminal output with structured result files
            combined_output = terminal_output
            if result_files_content:
                combined_output += f"\n\n=== RESULT FILES ===\n{result_files_content}"
            
            return DockerRunResult(
                exit_code=result.exit_code,
                stdout=combined_output,
                stderr=result.stderr,
                success=result.success,
            )

    def run_with_compose(
        self,
        compose_path: str | Path,
        test_command: str,
        test_patch: str,
        golden_patch: Optional[str] = None,
        agent_diff: Optional[str] = None,
        test_framework: Optional[str] = None,
        service_name: str = "default",
    ) -> DockerRunResult:
        """
        Run tests using docker compose exec (for tasks requiring services like Redis).

        This method:
        1. Starts all compose services (including Redis, etc.)
        2. Applies patches inside the container
        3. Runs the test command via docker compose exec
        4. Captures output and cleans up

        Args:
            compose_path: Path to the compose.yaml file
            test_command: Test command to execute
            test_patch: Test patch content to apply
            golden_patch: Optional golden patch content to apply
            agent_diff: Optional agent diff to apply
            test_framework: Optional test framework name for adding output flags
            service_name: Name of the service to exec into (default: "default")

        Returns:
            DockerRunResult with test output
        """
        from .frameworks import get_test_command_with_output

        compose_path = Path(compose_path)
        if not compose_path.exists():
            return DockerRunResult(
                exit_code=-1,
                stdout="",
                stderr=f"Compose file not found: {compose_path}",
                success=False,
            )

        compose_dir = compose_path.parent

        name_hash = hashlib.md5(compose_dir.name.encode()).hexdigest()[:8]
        project_name = f"f2p-{compose_dir.name[:16]}-{name_hash}"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Write patches to temp files
            test_patch_file = tmpdir_path / "test.patch"
            test_patch_file.write_text(test_patch)

            golden_patch_file = None
            if golden_patch:
                golden_patch_file = tmpdir_path / "golden.patch"
                golden_patch_file.write_text(golden_patch)

            agent_diff_file = None
            if agent_diff:
                agent_diff_file = tmpdir_path / "agent.patch"
                agent_diff_file.write_text(agent_diff)

            # Results directory
            results_dir = tmpdir_path / "test-results"
            results_dir.mkdir()

            try:
                # Step 1: Build and start compose services
                logger.info(f"Starting compose services for {project_name}...")
                up_cmd = [
                    "docker", "compose", "-f", str(compose_path),
                    "-p", project_name,
                    "up", "-d", "--build", "--wait"
                ]
                up_result = subprocess.run(
                    up_cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 min for startup
                    cwd=compose_dir,
                    stdin=subprocess.DEVNULL,
                )
                if up_result.returncode != 0:
                    return DockerRunResult(
                        exit_code=up_result.returncode,
                        stdout=up_result.stdout,
                        stderr=f"Failed to start compose services: {up_result.stderr}",
                        success=False,
                    )

                # Step 2: Copy patches into container
                container_name = f"{project_name}-{service_name}-1"
                
                for patch_file, dest in [
                    (test_patch_file, "/tmp/test.patch"),
                    (golden_patch_file, "/tmp/golden.patch") if golden_patch_file else (None, None),
                    (agent_diff_file, "/tmp/agent.patch") if agent_diff_file else (None, None),
                ]:
                    if patch_file and dest:
                        cp_result = subprocess.run(
                            ["docker", "cp", str(patch_file), f"{container_name}:{dest}"],
                            capture_output=True,
                            text=True,
                            timeout=30,
                            stdin=subprocess.DEVNULL,
                        )
                        if cp_result.returncode != 0:
                            logger.warning(f"Failed to copy {patch_file}: {cp_result.stderr}")

                # Step 3: Build and execute the test command
                enhanced_command = test_command
                if test_framework:
                    enhanced_command = get_test_command_with_output(test_command, test_framework)

                cmd_parts = [
                    f"cd {self.workdir}",
                    "",
                    "# Configure git",
                    f'git config --global user.email "{_GIT_USER_EMAIL}"',
                    f'git config --global user.name "{_GIT_USER_NAME}"',
                    f'git config --global --add safe.directory {self.workdir}',
                    "",
                    "# Apply test patch first",
                    "git apply /tmp/test.patch 2>/dev/null || patch -p1 < /tmp/test.patch || true",
                    "",
                ]

                if golden_patch:
                    cmd_parts.extend([
                        "# Apply golden patch",
                        "git apply /tmp/golden.patch 2>/dev/null || patch -p1 < /tmp/golden.patch || true",
                        "",
                    ])

                if agent_diff:
                    cmd_parts.extend([
                        "# Apply agent diff",
                        "git apply /tmp/agent.patch 2>/dev/null || patch -p1 < /tmp/agent.patch || true",
                        "",
                    ])

                cmd_parts.extend([
                    "# Create results directory",
                    "mkdir -p /workspace/test-results",
                    "",
                    "# Run tests",
                    f"({enhanced_command}) 2>&1 | tee /workspace/test-results/output.txt",
                    "_test_exit_code=${PIPESTATUS[0]}",
                    "",
                    "exit $_test_exit_code",
                ])

                full_command = "\n".join(cmd_parts)

                # Execute via docker compose exec
                exec_cmd = [
                    "docker", "compose", "-f", str(compose_path),
                    "-p", project_name,
                    "exec", "-T", service_name,
                    "bash", "-c", full_command
                ]

                logger.info(f"Running tests in compose service {service_name}...")
                exec_result = subprocess.run(
                    exec_cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=compose_dir,
                    stdin=subprocess.DEVNULL,
                )

                # Step 4: Copy results out of container
                subprocess.run(
                    ["docker", "cp", f"{container_name}:/workspace/test-results/.", str(results_dir)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    stdin=subprocess.DEVNULL,
                )

                # Read captured output
                output_file = results_dir / "output.txt"
                if output_file.exists():
                    try:
                        terminal_output = output_file.read_text()
                    except OSError as e:
                        logger.warning(f"Failed to read output file: {e}")
                        terminal_output = exec_result.stdout
                else:
                    terminal_output = exec_result.stdout

                # Read structured result files
                result_files_content = _read_result_files(results_dir)
                combined_output = terminal_output
                if result_files_content:
                    combined_output += f"\n\n=== RESULT FILES ===\n{result_files_content}"

                return DockerRunResult(
                    exit_code=exec_result.returncode,
                    stdout=combined_output,
                    stderr=exec_result.stderr,
                    success=exec_result.returncode == 0,
                )

            except subprocess.TimeoutExpired:
                logger.warning(f"Command timeout after {self.timeout}s")
                return DockerRunResult(
                    exit_code=-1,
                    stdout="",
                    stderr=f"Timeout after {self.timeout}s",
                    success=False,
                )
            except Exception as e:
                logger.error(f"Error running with compose: {e}")
                return DockerRunResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    success=False,
                )
            finally:
                # Step 5: Clean up compose services
                logger.info(f"Cleaning up compose services for {project_name}...")
                try:
                    subprocess.run(
                        ["docker", "compose", "-f", str(compose_path), "-p", project_name, "down", "-v", "--remove-orphans"],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        cwd=compose_dir,
                        stdin=subprocess.DEVNULL,
                    )
                except Exception as e:
                    logger.warning(f"Failed to clean up compose: {e}")


def _read_result_files(results_dir: Path) -> str:
    """Read JUnit XML and JSON result files from the results directory."""
    import glob as glob_module

    contents = []
    files_found: list[str] = []

    # Look for TEST-*.xml files (JUnit format from Gradle/Maven)
    for xml_file in glob_module.glob(str(results_dir / "TEST-*.xml")):
        files_found.append(xml_file)
        try:
            with open(xml_file) as f:
                content = f.read()
                contents.append(f"<!-- FILE: {xml_file} -->\n{content}")
        except OSError as e:
            logger.warning(f"Failed to read result file {xml_file}: {e}")
            contents.append(f"<!-- FILE: {xml_file} ERROR: {e} -->")

    # Look for any other XML files that might be JUnit format
    for xml_file in glob_module.glob(str(results_dir / "*.xml")):
        if xml_file not in files_found:
            files_found.append(xml_file)
            try:
                with open(xml_file) as f:
                    content = f.read()
                    if "<testsuite" in content or "<testsuites" in content:
                        contents.append(f"<!-- FILE: {xml_file} -->\n{content}")
            except OSError as e:
                logger.warning(f"Failed to read result file {xml_file}: {e}")

    # Look for JSON result files (Jest/Vitest)
    for json_file in glob_module.glob(str(results_dir / "*-results.json")):
        files_found.append(json_file)
        try:
            with open(json_file) as f:
                content = f.read()
                contents.append(f"// FILE: {json_file}\n{content}")
        except OSError as e:
            logger.warning(f"Failed to read result file {json_file}: {e}")
            contents.append(f"// FILE: {json_file} ERROR: {e}")

    # Also look for output.json (Jest default)
    for json_file in glob_module.glob(str(results_dir / "output.json")):
        if json_file not in files_found:
            files_found.append(json_file)
            try:
                with open(json_file) as f:
                    content = f.read()
                    contents.append(f"// FILE: {json_file}\n{content}")
            except OSError as e:
                logger.warning(f"Failed to read result file {json_file}: {e}")

    return "\n".join(contents) if contents else ""
