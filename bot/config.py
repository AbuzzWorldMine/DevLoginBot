"""Настройки бота: читаются из переменных окружения и (необязательно) из файла .env."""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    token: str
    api_key: str
    host: str
    port: int
    db_path: str
    admin_password: str
    latest_version: str
    download_url: str

    @staticmethod
    def load() -> "Config":
        _load_dotenv(Path(".env"))
        token = os.environ.get("DISCORD_TOKEN", "").strip()
        api_key = os.environ.get("API_KEY", "").strip()
        if not token:
            raise SystemExit("DISCORD_TOKEN не задан (.env или переменные окружения).")
        if len(api_key) < 16:
            raise SystemExit("API_KEY не задан или слишком короткий (нужно минимум 16 символов).")
        return Config(
            token=token,
            api_key=api_key,
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
            db_path=os.environ.get("DB_PATH", "devlogin.db"),
            admin_password=os.environ.get("ADMIN_PASSWORD", "").strip(),
            latest_version=os.environ.get("LATEST_VERSION", "").strip(),
            download_url=os.environ.get("DOWNLOAD_URL", "").strip(),
        )
