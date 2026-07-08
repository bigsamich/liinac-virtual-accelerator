"""Runtime configuration, overridable via PIP2VA_* environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIP2VA_")

    redis_url: str = "redis://localhost:6379/0"
    backend: str = "auto"       # auto | numpy | cupy
    tick_hz: float = 20.0
    stream_maxlen: int = 100    # 5 s of 20 Hz history (DVR rewind buffer)
    macro_particles: int = 100_000


settings = Settings()
