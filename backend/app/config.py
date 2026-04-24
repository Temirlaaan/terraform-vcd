from pydantic_settings import BaseSettings


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

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
