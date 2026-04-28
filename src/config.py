from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Polymarket
    polymarket_api_url: str = "https://clob.polymarket.com"
    polymarket_private_key: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Arbitrage
    min_profit_percent: float = 1.0
    max_stake_usd: float = 100.0
    scan_interval_seconds: int = 30

    # Bookmakers
    fonbet_base_url: str = "https://www.fonbet.ru"
    winline_base_url: str = "https://www.winline.ru"
    onebet_base_url: str = "https://1xbet.com"

    # Matching
    fuzzy_match_threshold: int = 70

    # Auto-betting
    auto_bet_enabled: bool = False
    dry_run: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
