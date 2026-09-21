import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

_LOG_CHANNEL_PREFIX = "operation:"
_LOG_CHANNEL_SUFFIX = ":logs"


def _provider_mirror_cli_config() -> Path | None:
    """Write a terraform CLI config pointing at the local provider mirror.

    Returns None when no mirror is configured, so terraform keeps talking to
    the registry. When one is set, providers resolve from disk only —
    ``direct`` is excluded for the same namespaces, so a host with no route
    to registry.terraform.io stops failing on ``init``.

    The file is rewritten each call: it is two lines, and this keeps it
    correct if the mirror path changes without a rebuild.
    """
    mirror = (settings.tf_provider_mirror_dir or "").strip()
    if not mirror:
        return None

    mirror_path = Path(mirror)
    if not mirror_path.is_dir():
        logger.warning(
            "TF_PROVIDER_MIRROR_DIR=%s does not exist — falling back to the registry",
            mirror,
        )
        return None

    rc_path = Path(settings.tf_workspace_base) / "terraform.rc"
    try:
        rc_path.parent.mkdir(parents=True, exist_ok=True)
        rc_path.write_text(
            "provider_installation {\n"
            "  filesystem_mirror {\n"
            f'    path    = "{mirror_path}"\n'
            '    include = ["registry.terraform.io/*/*"]\n'
            "  }\n"
            "  direct {\n"
            '    exclude = ["registry.terraform.io/*/*"]\n'
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("could not write %s: %s", rc_path, exc)
        return None
    return rc_path


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
        cloud: str = "primary",
        extra_tf_vars: dict[str, str] | None = None,
    ) -> None:
        """
        Args:
            cloud: which VCD this run targets — ``"primary"`` (default, the
                cloud configured via ``VCD_*``) or ``"secondary"`` (``SECONDARY_VCD_*``).
                Resolved eagerly so a misconfigured second cloud fails here
                rather than halfway through an apply.
            extra_tf_vars: additional ``TF_VAR_*`` values, by variable name
                without the prefix. IPsec pre-shared keys arrive this way:
                the resource requires them, the project forbids writing them
                into HCL, so they are passed per run and never persisted by
                this class.
        """
        self.work_dir = work_dir
        self.operation_id = operation_id
        self.cloud = cloud
        self._extra_tf_vars = dict(extra_tf_vars or {})
        self._creds = settings.cloud_credentials(cloud)
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

        # VCD credentials for the cloud this runner was built for
        env["TF_VAR_vcd_url"] = self._creds["url"].rstrip("/") + "/api"
        env["TF_VAR_vcd_user"] = self._creds["user"]
        env["TF_VAR_vcd_password"] = self._creds["password"]

        # S3/MinIO backend credentials
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"):
            val = os.environ.get(key)
            if val:
                env[key] = val

        # Egress proxy, when the host uses one. This env is an allowlist, so
        # without these terraform would try to reach the registry directly
        # and fail where curl on the same host succeeds.
        for key in (
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy",
        ):
            val = os.environ.get(key)
            if val:
                env[key] = val

        # Shared provider cache. Each operation gets its own workspace, so
        # without this every plan re-downloads the VCD provider and a
        # registry hiccup fails the run. The cache lives on the workspaces
        # volume, so it survives restarts and only the first run needs the
        # network.
        cache_dir = Path(settings.tf_workspace_base) / ".plugin-cache"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            env["TF_PLUGIN_CACHE_DIR"] = str(cache_dir)
        except OSError as exc:
            logger.warning("plugin cache unavailable at %s: %s", cache_dir, exc)

        # Caller-supplied variables (IPsec pre-shared keys). Applied after
        # the credentials above so a caller cannot accidentally override them.
        for name, value in self._extra_tf_vars.items():
            key = f"TF_VAR_{name}"
            if key in env:
                logger.warning("refusing to override %s from extra_tf_vars", key)
                continue
            env[key] = value

        # Local provider mirror, when the host cannot reach the registry.
        rc_file = _provider_mirror_cli_config()
        if rc_file:
            env["TF_CLI_CONFIG_FILE"] = str(rc_file)

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
