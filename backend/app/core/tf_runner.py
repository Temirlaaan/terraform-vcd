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
        """Build a minimal subprocess environment with TF_VAR_* credential injection.

        Only passes through essential variables to prevent leaking secrets
        (DATABASE_URL, REDIS_URL, etc.) to terraform provider plugins.
        """
        env: dict[str, str] = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/root"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }

        # VCD credentials
        env["TF_VAR_vcd_url"] = settings.vcd_url.rstrip("/") + "/api"
        env["TF_VAR_vcd_user"] = settings.vcd_user
        env["TF_VAR_vcd_password"] = settings.vcd_password

        # S3/MinIO backend credentials
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"):
            val = os.environ.get(key)
            if val:
                env[key] = val

        # Disable interactive prompts and colour codes for machine-readable output
        env["TF_INPUT"] = "false"
        env["TF_IN_AUTOMATION"] = "1"

        return env

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        label: str,
        collected: list[str],
        redis: Redis | None,
        channel: str,
    ) -> None:
        """Read an asyncio stream line-by-line, publish each line.

        The line is redacted before both at-rest collection and pub/sub
        emission so live WS subscribers and the eventual Operation row
        see the same scrubbed text (H6-BE).
        """
        if stream is None:
            return
        from app.core.redact import redact  # local import to avoid cycle
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            line = redact(line) or ""
            collected.append(line)
            if redis:
                await redis.publish(channel, f"[{label}] {line}")

    async def _exec(self, *args: str, emit_exit: bool = True) -> RunResult:
        """Run the terraform binary with the given arguments.

        If ``operation_id`` was provided, stdout and stderr are streamed
        line-by-line to Redis Pub/Sub.  A single Redis connection is reused
        for all published lines.  A final ``__EXIT:{code}`` sentinel is
        published so WebSocket consumers know the process has ended.
        """
        redis: Redis | None = None
        channel = ""
        if self.operation_id:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            channel = log_channel(self.operation_id)

        try:
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
                self._read_stream(proc.stdout, "stdout", stdout_lines, redis, channel),
                self._read_stream(proc.stderr, "stderr", stderr_lines, redis, channel),
            )
            await proc.wait()

            code = proc.returncode or 0
            if redis and emit_exit:
                await redis.publish(channel, f"__EXIT:{code}")

            return RunResult(
                return_code=code,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
            )
        finally:
            if redis:
                await redis.aclose()

    # ------------------------------------------------------------------
    # Public Terraform commands
    # ------------------------------------------------------------------

    async def init(self) -> RunResult:
        """Run ``terraform init``. Does NOT emit __EXIT — caller chains plan/apply afterwards and only the final command should signal completion."""
        return await self._exec("init", "-no-color", emit_exit=False)

    async def plan(self, refresh: bool = True) -> RunResult:
        """Run ``terraform plan`` and save the binary plan file.

        ``refresh=False`` skips refresh phase — used by rollback to avoid
        VCD provider ENF errors on resources deleted externally between
        target version snapshot time and now.
        """
        args = ["plan", "-no-color", "-out=plan.bin"]
        if not refresh:
            args.append("-refresh=false")
        return await self._exec(*args)

    async def apply(self) -> RunResult:
        """Run ``terraform apply`` using a previously saved plan."""
        return await self._exec("apply", "-no-color", "plan.bin")

    async def destroy(self) -> RunResult:
        """Run ``terraform destroy -auto-approve``."""
        return await self._exec("destroy", "-no-color", "-auto-approve")

    async def plan_refresh_only(self, out: str = "plan.bin") -> RunResult:
        """Run ``terraform plan -refresh-only -detailed-exitcode``.

        Returns RunResult where ``return_code`` carries detailed-exitcode
        semantics: 0 = no drift, 1 = error, 2 = drift present. Callers must
        NOT treat exit 2 as failure.
        """
        return await self._exec(
            "plan",
            "-no-color",
            "-refresh-only",
            "-detailed-exitcode",
            f"-out={out}",
            emit_exit=False,
        )

    async def show_plan_json(self, plan_file: str = "plan.bin") -> RunResult:
        """Run ``terraform show -json <planfile>`` for parsing."""
        return await self._exec(
            "show", "-no-color", "-json", plan_file, emit_exit=False,
        )

    async def state_list(self) -> RunResult:
        """Run ``terraform state list``."""
        return await self._exec("state", "list", "-no-color", emit_exit=False)
