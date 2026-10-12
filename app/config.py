from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    db_host: str = Field("localhost", alias="DB_HOST")
    db_port: int = Field(5432, alias="DB_PORT")
    db_user: str = Field("payments", alias="DB_USER")
    db_password: str = Field("payments", alias="DB_PASSWORD")
    db_name: str = Field("payments", alias="DB_NAME")

    # RabbitMQ
    rabbit_url: str = Field("amqp://guest:guest@localhost:5672/", alias="RABBIT_URL")

    # API
    api_key: str = Field("super-secret-api-key", alias="API_KEY")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def sync_database_url(self) -> str:
        # используется Alembic'ом
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()