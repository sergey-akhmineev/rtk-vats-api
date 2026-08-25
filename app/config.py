from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    pbx_base_url: str = "https://p2.cloudpbx.rt.ru"
    pbx_username: str = "admin"
    pbx_password: str = ""
    pbx_domain: str = ""
    pbx_verify_ssl: bool = True

    api_key: str = ""

    # Браузерный вход через «Ростелеком Паспорт» (SSO). Требует playwright.
    browser_headless: bool = True
    browser_user_agent: str = ""
    browser_step_timeout: int = 90  # сколько секунд ждём смены экрана Паспорта
    browser_code_ttl: int = 300  # сколько держим страницу ввода SMS-кода открытой

    data_dir: str = "./data"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8010

    @property
    def webapi_url(self) -> str:
        return self.pbx_base_url.rstrip("/") + "/webapi"


@lru_cache
def get_settings() -> Settings:
    return Settings()
