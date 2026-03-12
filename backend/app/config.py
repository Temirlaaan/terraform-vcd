from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://tf_user:password@postgres:5432/terraform_dashboard"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Keycloak
    keycloak_url: str = "https://sso-ttc.t-cloud.kz"
    keycloak_realm: str = "prod-v1"
    keycloak_client_id: str = "terraform-dashboard"
    keycloak_client_secret: str = ""

    # VCD
    vcd_url: str = "https://vcd-prod-01.t-cloud.kz/api"
    vcd_user: str = "terraform-svc"
    vcd_password: str = ""
    vcd_org: str = "System"

    # NSX-T
    nsxt_url: str = "https://nsxt-mgr.t-cloud.kz"
    nsxt_user: str = "admin"
    nsxt_password: str = ""

    # vSphere
    vsphere_url: str = "https://vcenter.t-cloud.kz"
    vsphere_user: str = "terraform-svc@vsphere.local"
    vsphere_password: str = ""

    # Terraform
    terraform_binary: str = "/usr/local/bin/terraform"
    tf_state_backend: str = "pg"
    tf_workspace_base: str = "/tmp/tf-workspaces"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
