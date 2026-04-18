from pydantic import Field
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
    central_db_windows_auth: bool = False

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
    ad_admin_groups: str = "InsideLLM-Admin"  # CRUD role; comma-separated
    ad_view_groups: str = "InsideLLM-View"  # GET-only role; comma-separated
    ad_approver_groups: str = "InsideLLM-Approve"  # change approval role; comma-separated

    # OIDC (when admin_auth_mode = "oidc")
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    # OIDC group GUIDs (Azure AD object IDs) mapped to each RBAC role.
    # Stored as comma-separated strings (docker-compose join); parsed via properties below.
    oidc_view_group_ids: str = ""
    oidc_admin_group_ids: str = ""
    oidc_approver_group_ids: str = ""

    # Break-glass local account (always-on; password == LITELLM_MASTER_KEY).
    # Read from the plain LITELLM_MASTER_KEY env var (no GOVERNANCE_HUB_ prefix).
    litellm_master_key: str = Field(default="", validation_alias="LITELLM_MASTER_KEY")

    # Keycloak — local SSO provider with sync to central DB (Phase 2).
    # Enabled only when the local keycloak container is deployed.
    keycloak_sync_enable: bool = False
    keycloak_url: str = "http://keycloak:8080/keycloak"  # in-container base
    keycloak_realm: str = "insidellm"
    keycloak_admin_client_id: str = "admin-cli"
    keycloak_admin_user: str = "insidellm-admin"
    keycloak_admin_password: str = Field(default="", validation_alias="KEYCLOAK_ADMIN_PASSWORD")
    keycloak_sync_schedule: str = "*/15 * * * *"  # every 15 min
    keycloak_sync_page_size: int = 500
    keycloak_http_timeout_seconds: float = 10.0

    # Chat (Mattermost embed)
    chat_enable: bool = False
    chat_team_name: str = "insidellm"
    chat_default_channel: str = "general"

    model_config = {"env_prefix": "GOVERNANCE_HUB_", "populate_by_name": True}

    @property
    def supervisor_email_list(self) -> list[str]:
        return [e.strip() for e in self.supervisor_emails.split(",") if e.strip()]

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [v.strip() for v in value.split(",") if v.strip()]

    @property
    def ad_view_group_list(self) -> list[str]:
        return self._split_csv(self.ad_view_groups)

    @property
    def ad_admin_group_list(self) -> list[str]:
        return self._split_csv(self.ad_admin_groups)

    @property
    def ad_approver_group_list(self) -> list[str]:
        return self._split_csv(self.ad_approver_groups)

    @property
    def oidc_view_group_id_list(self) -> list[str]:
        return self._split_csv(self.oidc_view_group_ids)

    @property
    def oidc_admin_group_id_list(self) -> list[str]:
        return self._split_csv(self.oidc_admin_group_ids)

    @property
    def oidc_approver_group_id_list(self) -> list[str]:
        return self._split_csv(self.oidc_approver_group_ids)

    @property
    def central_db_url(self) -> str:
        if not self.central_db_host:
            return ""
        if self.central_db_type == "postgresql":
            return f"postgresql+asyncpg://{self.central_db_user}:{self.central_db_password}@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
        elif self.central_db_type == "mariadb":
            return f"mysql+aiomysql://{self.central_db_user}:{self.central_db_password}@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
        elif self.central_db_type == "mssql":
            if self.central_db_windows_auth:
                return f"mssql+pymssql://@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
            return f"mssql+pymssql://{self.central_db_user}:{self.central_db_password}@{self.central_db_host}:{self.central_db_port}/{self.central_db_name}"
        return ""


settings = Settings()
