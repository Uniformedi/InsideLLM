from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Platform
    platform_version: str = "dev"

    # Instance identity
    instance_id: str = ""
    instance_name: str = ""
    schema_version: int = 1

    # Local PostgreSQL (LiteLLM database)
    database_url: str = "postgresql+asyncpg://litellm:litellm@postgres:5432/litellm"

    # Central DB
    central_db_type: str = "postgresql"  # postgresql, mariadb, mssql
    central_db_host: str = ""
    central_db_port: int = 5432
    central_db_name: str = "insidellm_central"
    central_db_user: str = ""
    central_db_password: str = ""
    central_db_ssl: bool = True

    # Sync
    sync_schedule: str = "0 */6 * * *"
    sync_on_startup: bool = True

    # Change management
    supervisor_emails: str = ""  # comma-separated
    hub_secret: str = ""

    # AI Advisor
    litellm_url: str = "http://litellm:4000"
    litellm_api_key: str = ""
    advisor_model: str = "claude-sonnet"

    # Governance metadata
    industry: str = "general"
    governance_tier: str = "tier3"
    data_classification: str = "internal"

    # Framework & Compliance
    framework_path: str = "/app/framework/AI_Governance_Framework.md"
    compliance_check_schedule: str = "0 */6 * * *"

    # Tiered approval roles (comma-separated)
    tier1_roles: str = "executive,cto,cio,ai_ethics_officer"
    tier2_roles: str = "department_head,director,senior_manager"
    tier3_roles: str = "manager,team_lead"

    # Admin authentication (oidc / ldap / none)
    admin_auth_mode: str = "none"
    auth_secret: str = ""  # JWT signing key for session cookies

    # LDAP / Active Directory (when admin_auth_mode = "ldap")
    ad_domain: str = ""
    ad_admin_groups: str = "Domain Admins"  # comma-separated groups allowed access

    # OIDC (when admin_auth_mode = "oidc")
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    model_config = {"env_prefix": "GOVERNANCE_HUB_"}

    @property
    def supervisor_email_list(self) -> list[str]:
        return [e.strip() for e in self.supervisor_emails.split(",") if e.strip()]

    @property
    def central_db_url(self) -> str:
        if not self.central_db_host:
            return ""
        if self.central_db_type == "postgresql":
            return f"postgresql+asyncpg://{self.central_db_user}:{self.central_db_password}@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
        elif self.central_db_type == "mariadb":
            return f"mysql+aiomysql://{self.central_db_user}:{self.central_db_password}@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
        elif self.central_db_type == "mssql":
            return f"mssql+pymssql://{self.central_db_user}:{self.central_db_password}@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
        return ""


settings = Settings()
