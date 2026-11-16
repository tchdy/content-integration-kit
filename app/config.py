"""Runtime configuration, read once from environment variables.

Every setting has a safe local default so `uvicorn app.main:app` works with no
setup. Production values are set in the hosting platform (see render.yaml).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # Public URL of this app. Render sets RENDER_EXTERNAL_URL automatically.
    base_url: str = field(
        default_factory=lambda: (
            os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000"
        ).rstrip("/")
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(ROOT / "data"))))
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", "dev-only-change-me"))
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "dev-webhook-secret"))
    # Max age of a signed webhook before it is rejected as a possible replay.
    webhook_tolerance_seconds: int = field(default_factory=lambda: int(os.getenv("WEBHOOK_TOLERANCE_SECONDS", "300")))
    # SAML identity provider. Defaults to mocksaml.com, a free public test IdP.
    idp_metadata_url: str = field(default_factory=lambda: os.getenv("IDP_METADATA_URL", "https://mocksaml.com/api/saml/metadata"))
    # Optional local metadata file; takes precedence over the URL (used by tests / air-gapped setups).
    idp_metadata_file: str | None = field(default_factory=lambda: os.getenv("IDP_METADATA_FILE"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kit.db"

    @property
    def sp_entity_id(self) -> str:
        return f"{self.base_url}/saml/metadata"

    @property
    def acs_url(self) -> str:
        return f"{self.base_url}/saml/acs"


def get_settings() -> Settings:
    return Settings()
