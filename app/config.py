"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with secrets kept out of source control."""

    digitalocean_model_access_key: SecretStr | None = None
    digitalocean_model_id: str | None = None
    digitalocean_inference_base_url: str = "https://inference.do-ai.run"
    inference_timeout_seconds: float = 45.0
    google_pubsub_verification_token: SecretStr | None = None
    google_sheet_webhook_token: SecretStr | None = None
    google_access_token: SecretStr | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_client_secret_json: SecretStr | None = None
    google_refresh_token: SecretStr | None = None
    google_spreadsheet_id: str | None = None
    google_gmail_user_id: str = "me"
    google_venues_sheet: str = "Venues"
    google_quotes_sheet: str = "Quotes"
    google_system_sheet: str = "System"
    google_allowed_emails: str = ""
    google_primary_email: str = ""
    auto_send: bool = False
    control_center_username: str = "raph"
    control_center_password: SecretStr | None = None
    control_center_session_ttl_hours: int = 168
    allow_unauthenticated_local: bool = False
    app_env: str = "local"
    database_url: str = "sqlite:///data/wedding.db"
    spaces_bucket: str = ""
    spaces_region: str = "sfo2"
    spaces_endpoint_url: str = ""
    spaces_access_key_id: SecretStr | None = None
    spaces_secret_access_key: SecretStr | None = None
    spaces_presigned_url_seconds: int = 600
    spaces_max_attachment_bytes: int = 26_214_400

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def inference_configured(self) -> bool:
        """Return whether both required inference settings are present."""
        return bool(self.digitalocean_model_access_key and self.digitalocean_model_id)

    @property
    def google_configured(self) -> bool:
        """Return whether the first Google REST integration can run."""
        refresh_configured = bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_refresh_token
        )
        return bool(
            self.google_spreadsheet_id
            and (self.google_access_token or refresh_configured)
        )

    @property
    def google_allowed_email_set(self) -> set[str]:
        """Return normalized Gmail accounts explicitly approved by the owner."""
        return {
            email.strip().casefold()
            for email in self.google_allowed_emails.split(",")
            if email.strip()
        }

    @property
    def spaces_configured(self) -> bool:
        """Return whether private attachment storage can be used."""
        return bool(
            self.spaces_bucket
            and self.spaces_region
            and self.spaces_access_key_id
            and self.spaces_secret_access_key
        )

    @property
    def resolved_spaces_endpoint_url(self) -> str:
        """Return the configured endpoint or the standard regional endpoint."""
        return self.spaces_endpoint_url or (
            f"https://{self.spaces_region}.digitaloceanspaces.com"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings object for the application process."""
    return Settings()
