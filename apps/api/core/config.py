from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # Anthropic
    anthropic_api_key: str

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # API
    api_secret_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    environment: str = "development"

    # Integrations
    chatwoot_base_url: str = ""
    chatwoot_api_token: str = ""
    zendesk_subdomain: str = ""
    zendesk_email: str = ""
    zendesk_api_token: str = ""
    shopify_api_key: str = ""
    shopify_api_secret: str = ""
    postmark_server_token: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
