from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://tf_user:password@postgres:5432/terraform_dashboard"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # CORS — comma-separated list of allowed origins (no wildcard in production)
    cors_origins: str = "http://localhost:5173"

    # SSL verification for outgoing HTTPS requests (VCD, Keycloak, etc.)
    verify_ssl: bool = True

    # Authentication — set to true to disable Keycloak auth (for testing only!)
    auth_disabled: bool = False

    # Deployment environment — "dev" allows AUTH_DISABLED on localhost; "prod"
    # refuses AUTH_DISABLED unconditionally (startup panic). Defaults to dev.
    tf_env: str = "dev"

    # Hostname the dashboard is reachable at — used by AUTH_DISABLED guardrail
    # and CORS validation.
    dashboard_hostname: str = "localhost"

    # Keycloak
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = "terraform-dashboard"
    keycloak_client_secret: str = ""

    # VCD — CloudAPI (used by the dashboard for metadata)
    vcd_url: str = ""
    vcd_api_token: str = ""
    vcd_api_version: str = "38.0"
    vcd_org: str = "System"

    # VCD — Terraform provider credentials (used by tf_runner / base.tf.j2)
    vcd_user: str = ""
    vcd_password: str = ""

    # Secondary VCD — a second cloud we can read metadata from and deploy
    # into, for cloud-to-cloud migration. Leave SECONDARY_VCD_URL empty to
    # disable every second-cloud feature.
    secondary_vcd_url: str = ""
    secondary_vcd_api_token: str = ""
    secondary_vcd_api_version: str = "38.0"
    secondary_vcd_org: str = "System"
    secondary_vcd_user: str = ""
    secondary_vcd_password: str = ""
    # Shown in the UI so operators can tell the two clouds apart.
    secondary_vcd_label: str = "Secondary VCD"

    # NSX-T
    nsxt_url: str = ""
    nsxt_user: str = ""
    nsxt_password: str = ""

    # vSphere
    vsphere_url: str = ""
    vsphere_user: str = ""
    vsphere_password: str = ""

    # Terraform
    terraform_binary: str = "/usr/local/bin/terraform"
    tf_state_backend: str = "pg"
    tf_workspace_base: str = "/tmp/tf-workspaces"

    # Workspace cleanup — delete workspace directories after completion
    workspace_cleanup_enabled: bool = True

    # Phase 4: daily drift sync
    drift_sync_enabled: bool = True
    drift_sync_cron: str = "0 3 * * *"  # 03:00 daily
    drift_sync_timezone: str = "Asia/Almaty"
    drift_sync_lock_ttl: int = 1800  # 30 minutes, safety if job crashes

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    def cloud_credentials(self, cloud: str = "primary") -> dict[str, str]:
        """Provider credentials for a named cloud.

        Single source of truth for "which VCD are we talking to" — used by
        tf_runner to build TF_VAR_* and by VCDClient for metadata.

        Raises:
            ValueError: unknown cloud, or the secondary cloud is not configured.
        """
        if cloud == "primary":
            return {
                "url": self.vcd_url,
                "user": self.vcd_user,
                "password": self.vcd_password,
                "org": self.vcd_org,
                "api_token": self.vcd_api_token,
                "api_version": self.vcd_api_version,
                "label": "Primary VCD",
            }
        if cloud == "secondary":
            if not self.secondary_vcd_url:
                raise ValueError(
                    "Secondary VCD is not configured — set SECONDARY_VCD_URL."
                )
            return {
                "url": self.secondary_vcd_url,
                "user": self.secondary_vcd_user,
                "password": self.secondary_vcd_password,
                "org": self.secondary_vcd_org,
                "api_token": self.secondary_vcd_api_token,
                "api_version": self.secondary_vcd_api_version,
                "label": self.secondary_vcd_label,
            }
        raise ValueError(f"Unknown cloud {cloud!r}. Expected 'primary' or 'secondary'.")

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list.

        Rejects wildcards / null / wildcard subdomains — explicit origins only.
        Empty list when input is malformed (caller decides what to do).
        """
        out: list[str] = []
        for raw in self.cors_origins.split(","):
            o = raw.strip()
            if not o:
                continue
            if o in ("*", "null") or o.startswith("*.") or "*" in o:
                raise ValueError(
                    f"CORS origin {o!r} is wildcard/null — refused. "
                    "List explicit https URLs in CORS_ORIGINS."
                )
            if not (o.startswith("http://") or o.startswith("https://")):
                raise ValueError(
                    f"CORS origin {o!r} must start with http:// or https://"
                )
            out.append(o)
        return out

    @field_validator("tf_env")
    @classmethod
    def _check_env(cls, v: str) -> str:
        if v not in ("dev", "prod"):
            raise ValueError("TF_ENV must be 'dev' or 'prod'")
        return v

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
