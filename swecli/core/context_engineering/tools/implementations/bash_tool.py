"""Tool for executing bash commands safely."""

import platform
import re
import select
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from swecli.models.config import AppConfig
from swecli.models.operation import BashResult, Operation
from swecli.core.context_engineering.tools.implementations.base import BaseTool


# Safe commands that are generally allowed
SAFE_COMMANDS = [
    "ls", "cat", "head", "tail", "grep", "find", "wc",
    "echo", "pwd", "which", "whoami",
    "git", "pytest", "python", "python3", "pip",
    "node", "npm", "npx", "yarn",
    "docker", "kubectl",
    "make", "cmake",
]

# Dangerous patterns that should be blocked
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",  # Delete root
    r"sudo",  # Privileged execution
    r"chmod\s+-R\s+777",  # Permissive permissions
    r":\(\)\{\s*:\|\:&\s*\};:",  # Fork bomb
    r"mv\s+/",  # Move root directories
    r">\s*/dev/sd[a-z]",  # Write to disk directly
    r"dd\s+if=.*of=/dev",  # Disk operations
    r"curl.*\|\s*bash",  # Download and execute
    r"wget.*\|\s*bash",  # Download and execute
]

# Commands that commonly require y/n confirmation (safe scaffolding tools)
INTERACTIVE_COMMANDS = [
    r"\bnpx\b",  # npx create-*, npx degit, etc.
    r"\bnpm\s+init\b",  # npm init
    r"\byarn\s+create\b",  # yarn create
    r"\bng\s+new\b",  # Angular CLI
    r"\bvue\s+create\b",  # Vue CLI
    r"\bcreate-react-app\b",  # CRA
    r"\bnext\s+create\b",  # Next.js
    r"\bvite\s+create\b",  # Vite
    r"\bpnpm\s+create\b",  # pnpm create
]

# Timeout configuration for activity-based timeout
# Only timeout if command produces no output for IDLE_TIMEOUT seconds
IDLE_TIMEOUT = 60  # Timeout after 60 seconds of no output
MAX_TIMEOUT = 600  # Absolute max runtime: 10 minutes (safety cap)


class BashTool(BaseTool):
    """Tool for executing bash commands with safety checks."""

    @property
    def name(self) -> str:
        """Tool name."""
        return "execute_command"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Execute a bash command safely"

    def __init__(self, config: AppConfig, working_dir: Path):
        """Initialize bash tool.

        Args:
            config: Application configuration
            working_dir: Working directory for command execution
        """
        self.config = config
        self.working_dir = working_dir
        # Track background processes: {pid: {process, command, start_time, stdout_lines, stderr_lines}}
        self._background_processes = {}

    def _needs_auto_confirm(self, command: str) -> bool:
        """Check if command likely requires interactive confirmation.

        Args:
            command: The command string to check

        Returns:
            True if command matches known interactive patterns
        """
        for pattern in INTERACTIVE_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def execute(
        self,
        command: str,
        timeout: int = 30,
        capture_output: bool = True,
        working_dir: Optional[str] = None,
        env: Optional[dict] = None,
        background: bool = False,
        operation: Optional[Operation] = None,
        task_monitor: Optional[Any] = None,
        auto_confirm: bool = False,
        output_callback: Optional[Any] = None,
    ) -> BashResult:
        """Execute a bash command.

        Args:
            command: Command to execute
            timeout: Timeout in seconds
            capture_output: Whether to capture stdout/stderr
            working_dir: Working directory (defaults to self.working_dir)
            env: Environment variables
            background: Run in background (not implemented yet)
            operation: Operation object for tracking
            task_monitor: Optional TaskMonitor for interrupt support
            auto_confirm: Automatically confirm y/n prompts for interactive commands
            output_callback: Optional callback(line, is_stderr=False) for streaming output

        Returns:
            BashResult with execution details

        Raises:
            PermissionError: If command execution is not permitted
            ValueError: If command is dangerous
        """
        # Check if bash execution is enabled
        if not self.config.permissions.bash.enabled:
            error = "Bash execution is disabled in configuration"
            if operation:
                operation.mark_failed(error)
            return BashResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=error,
                duration=0.0,
                error=error,
                operation_id=operation.id if operation else None,
            )

        # Check if command is allowed
        if not self._is_command_allowed(command):
            error = f"Command not allowed: {command}"
            if operation:
                operation.mark_failed(error)
            return BashResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=error,
                duration=0.0,
                error=error,
                operation_id=operation.id if operation else None,
            )

        # Check for dangerous patterns
        if self._is_dangerous(command):
            error = f"Dangerous command blocked: {command}"
            if operation:
                operation.mark_failed(error)
            return BashResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=error,
                duration=0.0,
                error=error,
                operation_id=operation.id if operation else None,
            )

        # Resolve working directory
        work_dir = Path(working_dir) if working_dir else self.working_dir

        try:
            # Mark operation as executing
            if operation:
                operation.mark_executing()

            # Start timing
            start_time = time.time()

            # Handle background execution
            if background:
                # Use Popen for background execution
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    text=True,
                    bufsize=1,  # Line buffered for real-time streaming
                    cwd=str(work_dir),
                    env=env,
                )

                # Capture initial startup output (wait up to 2 seconds)
                stdout_lines = []
                stderr_lines = []

                if capture_output:
                    import time as time_module
                    timeout = 2.0  # Wait 2 seconds for startup output
                    start_capture = time_module.time()

                    while time_module.time() - start_capture < timeout:
                        # Check if there's data ready to read (non-blocking)
                        ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)

                        for stream in ready:
                            line = stream.readline()
                            if line:
                                if stream == process.stdout:
                                    stdout_lines.append(line)
                                else:
                                    stderr_lines.append(line)

                        # Stop if process died
                        if process.poll() is not None:
                            break

                    # Drain any remaining output after process exits
                    if process.poll() is not None:
                        # Read remaining data from pipes
                        remaining_stdout = process.stdout.read() if process.stdout else ""
                        remaining_stderr = process.stderr.read() if process.stderr else ""
                        if remaining_stdout:
                            stdout_lines.extend(remaining_stdout.splitlines(keepends=True))
                        if remaining_stderr:
                            stderr_lines.extend(remaining_stderr.splitlines(keepends=True))

                # Check if process exited during startup capture
                # If it failed quickly (non-zero exit), treat it as a synchronous failure
                exit_code = process.poll()
                if exit_code is not None and exit_code != 0:
                    # Process failed during startup - return actual result
                    duration = time.time() - start_time
                    stdout_text = "".join(stdout_lines).rstrip()
                    stderr_text = "".join(stderr_lines).rstrip()

                    # Send captured output through callback for streaming display
                    if output_callback:
                        for line in stdout_lines:
                            try:
                                output_callback(line.rstrip('\n'), is_stderr=False)
                            except Exception:
                                pass
                        for line in stderr_lines:
                            try:
                                output_callback(line.rstrip('\n'), is_stderr=True)
                            except Exception:
                                pass

                    if operation:
                        operation.mark_failed(f"Command failed with exit code {exit_code}")

                    return BashResult(
                        success=False,
                        command=command,
                        exit_code=exit_code,
                        stdout=stdout_text,
                        stderr=stderr_text,
                        duration=duration,
                        operation_id=operation.id if operation else None,
                    )

                # Store process info with captured output
                self._background_processes[process.pid] = {
                    "process": process,
                    "command": command,
                    "start_time": start_time,
                    "stdout_lines": stdout_lines,
                    "stderr_lines": stderr_lines,
                }

                # Mark operation as success (background process started)
                if operation:
                    operation.mark_success()

                return BashResult(
                    success=True,
                    command=command,
                    exit_code=0,  # Process started
                    stdout="",  # Background process started, output captured separately
                    stderr="",
                    duration=0.0,
                    operation_id=operation.id if operation else None,
                )

            # Auto-confirm interactive commands when requested
            use_stdin_confirm = False
            if auto_confirm and self._needs_auto_confirm(command):
                if platform.system() != "Windows":
                    # Unix: use yes | wrapper to handle multiple prompts
                    command = f"yes | {command}"
                else:
                    # Windows: will use stdin.write() approach
                    use_stdin_confirm = True

            # Regular synchronous execution with interrupt support
            process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE if use_stdin_confirm else None,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=True,
                bufsize=1,  # Line buffered for real-time streaming
                cwd=str(work_dir),
                env=env,
            )

            # Windows fallback: write y to stdin for interactive prompts
            if use_stdin_confirm and process.stdin:
                try:
                    # Send multiple y's for commands with multiple prompts
                    process.stdin.write("y\ny\ny\ny\ny\n")
                    process.stdin.flush()
                    process.stdin.close()
                except Exception:
                    pass

            # Poll process with interrupt checking and streaming output
            # Activity-based timeout: only timeout if no output for IDLE_TIMEOUT seconds
            stdout_lines = []
            stderr_lines = []
            poll_interval = 0.1  # Check every 100ms
            last_activity_time = start_time  # Track when we last received output

            while process.poll() is None:
                had_activity = False

                # Check for output to detect activity (for activity-based timeout)
                # Also stream output if callback is provided
                if capture_output:
                    # Use select to check if data is available (non-blocking)
                    try:
                        streams_to_check = []
                        if process.stdout:
                            streams_to_check.append(process.stdout)
                        if process.stderr:
                            streams_to_check.append(process.stderr)

                        if streams_to_check:
                            readable, _, _ = select.select(streams_to_check, [], [], 0)
                            for stream in readable:
                                line = stream.readline()
                                if line:
                                    had_activity = True  # Output received - reset idle timer
                                    is_stderr = (stream == process.stderr)
                                    line_text = line.rstrip('\n')
                                    if is_stderr:
                                        stderr_lines.append(line_text)
                                    else:
                                        stdout_lines.append(line_text)
                                    # Call the callback with the line if provided
                                    if output_callback:
                                        try:
                                            output_callback(line_text, is_stderr=is_stderr)
                                        except Exception:
                                            pass  # Don't let callback errors break execution
                    except (ValueError, OSError):
                        # Stream may be closed or invalid
                        pass

                # Reset activity timer if output was received
                if had_activity:
                    last_activity_time = time.time()

                # Check for interrupt
                if task_monitor is not None:
                    should_interrupt = False
                    if hasattr(task_monitor, "should_interrupt"):
                        should_interrupt = task_monitor.should_interrupt()
                    elif hasattr(task_monitor, "is_interrupted"):
                        should_interrupt = task_monitor.is_interrupted()

                    if should_interrupt:
                        # User pressed ESC - terminate the process
                        try:
                            process.terminate()
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()

                        duration = time.time() - start_time
                        error = "Command interrupted by user"
                        if operation:
                            operation.mark_failed(error)

                        return BashResult(
                            success=False,
                            command=command,
                            exit_code=-1,
                            stdout="\n".join(stdout_lines) if stdout_lines else "",
                            stderr=error,
                            duration=duration,
                            error=error,
                            operation_id=operation.id if operation else None,
                        )

                # Check activity-based timeout
                time.sleep(poll_interval)
                now = time.time()
                idle_time = now - last_activity_time
                total_time = now - start_time

                # Timeout if idle too long OR absolute max exceeded
                if idle_time >= IDLE_TIMEOUT or total_time >= MAX_TIMEOUT:
                    process.kill()
                    process.wait()
                    duration = time.time() - start_time

                    if total_time >= MAX_TIMEOUT:
                        error = f"Command exceeded maximum runtime of {MAX_TIMEOUT} seconds"
                    else:
                        error = f"Command timed out after {int(idle_time)} seconds of no output"

                    if operation:
                        operation.mark_failed(error)

                    return BashResult(
                        success=False,
                        command=command,
                        exit_code=-1,
                        stdout="\n".join(stdout_lines) if stdout_lines else "",
                        stderr="\n".join(stderr_lines) if stderr_lines else "",
                        duration=duration,
                        error=error,
                        operation_id=operation.id if operation else None,
                    )

            # Process finished - collect any remaining output
            if capture_output:
                # Use communicate() to reliably get all remaining output
                # This works even if the process exited before the poll loop ran
                remaining_stdout, remaining_stderr = process.communicate()

                if output_callback:
                    # Stream any remaining output through callback
                    if remaining_stdout:
                        for line in remaining_stdout.splitlines():
                            stdout_lines.append(line)
                            try:
                                output_callback(line, is_stderr=False)
                            except Exception:
                                pass
                    if remaining_stderr:
                        for line in remaining_stderr.splitlines():
                            stderr_lines.append(line)
                            try:
                                output_callback(line, is_stderr=True)
                            except Exception:
                                pass

                # Combine streamed lines with any remaining output
                stdout_text = "\n".join(stdout_lines) if stdout_lines else remaining_stdout or ""
                stderr_text = "\n".join(stderr_lines) if stderr_lines else remaining_stderr or ""
            else:
                stdout_text, stderr_text = "", ""

            # Calculate duration
            duration = time.time() - start_time

            # Check exit code
            success = process.returncode == 0

            # Mark operation status
            if operation:
                if success:
                    operation.mark_success()
                else:
                    operation.mark_failed(f"Command failed with exit code {process.returncode}")

            return BashResult(
                success=success,
                command=command,
                exit_code=process.returncode,
                stdout=stdout_text or "",
                stderr=stderr_text or "",
                duration=duration,
                operation_id=operation.id if operation else None,
            )

        except subprocess.TimeoutExpired as e:
            # Fallback timeout handler (shouldn't normally be reached with activity-based timeout)
            duration = time.time() - start_time
            error = f"Command timed out after {int(duration)} seconds"

            # Extract partial output from the exception
            partial_stdout = e.stdout if e.stdout else ""
            partial_stderr = e.stderr if e.stderr else ""

            if operation:
                operation.mark_failed(error)
            return BashResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout=partial_stdout,
                stderr=partial_stderr,
                duration=duration,
                error=error,
                operation_id=operation.id if operation else None,
            )

        except Exception as e:
            duration = time.time() - start_time
            error = f"Command execution failed: {str(e)}"
            if operation:
                operation.mark_failed(error)
            return BashResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=error,
                duration=duration,
                error=error,
                operation_id=operation.id if operation else None,
            )

    def _is_command_allowed(self, command: str) -> bool:
        """Check if command is in the allowed list.

        Args:
            command: Command to check

        Returns:
            True if command is allowed
        """
        # Get the base command (first word)
        base_command = command.strip().split()[0] if command.strip() else ""

        # Check if it's in safe commands
        if base_command in SAFE_COMMANDS:
            return True

        # Check against permission patterns
        return self.config.permissions.bash.is_allowed(command)

    def _is_dangerous(self, command: str) -> bool:
        """Check if command matches dangerous patterns.

        Args:
            command: Command to check

        Returns:
            True if command is dangerous
        """
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True

        # Check config deny patterns
        for pattern in self.config.permissions.bash.compiled_patterns:
            if pattern.match(command):
                return True

        return False

    def preview_command(self, command: str, working_dir: Optional[str] = None) -> str:
        """Generate a preview of the command execution.

        Args:
            command: Command to preview
            working_dir: Working directory

        Returns:
            Formatted preview string
        """
        work_dir = working_dir or str(self.working_dir)

        preview = f"Command: {command}\n"
        preview += f"Working Directory: {work_dir}\n"
        preview += f"Timeout: {self.config.bash_timeout}s\n"

        # Safety checks
        if not self._is_command_allowed(command):
            preview += "\n⚠️  WARNING: Command not in allowed list\n"

        if self._is_dangerous(command):
            preview += "\n❌ DANGER: Command matches dangerous pattern\n"

        return preview

    def list_processes(self) -> list[dict]:
        """List all tracked background processes.

        Returns:
            List of process info dicts with pid, command, status, runtime
        """
        processes = []
        for pid, info in list(self._background_processes.items()):
            process = info["process"]
            status = "running" if process.poll() is None else "finished"
            runtime = time.time() - info["start_time"]

            processes.append({
                "pid": pid,
                "command": info["command"],
                "status": status,
                "runtime": runtime,
                "exit_code": process.returncode if status == "finished" else None,
            })

        return processes

    def get_process_output(self, pid: int) -> dict:
        """Get output from a background process.

        Args:
            pid: Process ID

        Returns:
            Dict with stdout, stderr, status, exit_code
        """
        if pid not in self._background_processes:
            return {
                "success": False,
                "error": f"Process {pid} not found",
            }

        info = self._background_processes[pid]
        process = info["process"]

        # Just return what's already captured - don't try to read more
        # (readline() blocks on pipes for long-running servers)
        # Output was already captured at process start

        # Check if process finished
        return_code = process.poll()
        status = "running" if return_code is None else "finished"

        return {
            "success": True,
            "pid": pid,
            "command": info["command"],
            "status": status,
            "exit_code": return_code,
            "stdout": "".join(info["stdout_lines"]),  # Return all captured output
            "stderr": "".join(info["stderr_lines"]),
            "total_stdout": "".join(info["stdout_lines"]),
            "total_stderr": "".join(info["stderr_lines"]),
            "runtime": time.time() - info["start_time"],
        }

    def kill_process(self, pid: int, signal: int = 15) -> dict:
        """Kill a background process.

        Args:
            pid: Process ID
            signal: Signal to send (default: 15/SIGTERM)

        Returns:
            Dict with success status
        """
        if pid not in self._background_processes:
            return {
                "success": False,
                "error": f"Process {pid} not found",
            }

        info = self._background_processes[pid]
        process = info["process"]

        try:
            if signal == 9:
                process.kill()  # SIGKILL
            else:
                process.terminate()  # SIGTERM

            # Wait for process to finish
            process.wait(timeout=5)

            # Clean up
            del self._background_processes[pid]

            return {
                "success": True,
                "pid": pid,
                "message": f"Process {pid} terminated",
            }

        except subprocess.TimeoutExpired:
            # Force kill if terminate didn't work
            process.kill()
            del self._background_processes[pid]

            return {
                "success": True,
                "pid": pid,
                "message": f"Process {pid} force killed",
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to kill process {pid}: {str(e)}",
            }
