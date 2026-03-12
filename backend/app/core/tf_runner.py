import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from redis.asyncio import Redis

from app.config import settings

_LOG_CHANNEL_PREFIX = "operation:"
_LOG_CHANNEL_SUFFIX = ":logs"


def log_channel(operation_id: str) -> str:
    """Return the Redis Pub/Sub channel name for a given operation."""
    return f"{_LOG_CHANNEL_PREFIX}{operation_id}{_LOG_CHANNEL_SUFFIX}"


@dataclass
class RunResult:
    return_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.return_code == 0


class TerraformRunner:
    """Executes Terraform CLI commands as async subprocesses.

    Credentials are injected exclusively through TF_VAR_* environment
    variables — they never appear in the generated HCL.

    When ``operation_id`` is supplied the runner publishes every stdout/
    stderr line to a Redis Pub/Sub channel so the WebSocket endpoint can
    stream it to the frontend in real-time.
    """

    def __init__(
        self,
        work_dir: Path,
        operation_id: str | None = None,
    ) -> None:
        self.work_dir = work_dir
        self.operation_id = operation_id
        self._tf = settings.terraform_binary

    def _build_env(self) -> dict[str, str]:
        """Build a subprocess environment with TF_VAR_* credential injection."""
        env = os.environ.copy()

        # VCD credentials
        env["TF_VAR_vcd_url"] = settings.vcd_url
        env["TF_VAR_vcd_user"] = settings.vcd_user
        env["TF_VAR_vcd_password"] = settings.vcd_password

        # Disable interactive prompts and colour codes for machine-readable output
        env["TF_INPUT"] = "false"
        env["TF_IN_AUTOMATION"] = "1"

        return env

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    async def _publish(self, line: str) -> None:
        """Publish a single line to the operation's Redis Pub/Sub channel."""
        if not self.operation_id:
            return
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.publish(log_channel(self.operation_id), line)
        finally:
            await redis.aclose()

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        label: str,
        collected: list[str],
    ) -> None:
        """Read an asyncio stream line-by-line, publish each line."""
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            collected.append(line)
            await self._publish(f"[{label}] {line}")

    async def _exec(self, *args: str) -> RunResult:
        """Run the terraform binary with the given arguments.

        If ``operation_id`` was provided, stdout and stderr are streamed
        line-by-line to Redis Pub/Sub.  A final ``__EXIT:{code}`` sentinel
        is published so WebSocket consumers know the process has ended.
        """
        proc = await asyncio.create_subprocess_exec(
            self._tf,
            *args,
            cwd=str(self.work_dir),
            env=self._build_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        await asyncio.gather(
            self._read_stream(proc.stdout, "stdout", stdout_lines),
            self._read_stream(proc.stderr, "stderr", stderr_lines),
        )
        await proc.wait()

        code = proc.returncode or 0
        await self._publish(f"__EXIT:{code}")

        return RunResult(
            return_code=code,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
        )

    # ------------------------------------------------------------------
    # Public Terraform commands
    # ------------------------------------------------------------------

    async def init(self) -> RunResult:
        """Run ``terraform init``."""
        return await self._exec("init", "-no-color")

    async def plan(self) -> RunResult:
        """Run ``terraform plan`` and save the binary plan file."""
        return await self._exec("plan", "-no-color", "-out=plan.bin")

    async def apply(self) -> RunResult:
        """Run ``terraform apply`` using a previously saved plan."""
        return await self._exec("apply", "-no-color", "plan.bin")

    async def destroy(self) -> RunResult:
        """Run ``terraform destroy -auto-approve``."""
        return await self._exec("destroy", "-no-color", "-auto-approve")
