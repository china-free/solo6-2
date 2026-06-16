from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Lab Instrument Reservation & Audit System"
    DATABASE_URL: str = "sqlite:///./lab_reservation.db"

    DEFAULT_GRACE_PERIOD_MINUTES: int = 15
    DEFAULT_NO_SHOW_THRESHOLD_MINUTES: int = 30
    DEFAULT_MAX_RESERVATION_HOURS: int = 8

    class Config:
        env_file = ".env"


settings = Settings()
