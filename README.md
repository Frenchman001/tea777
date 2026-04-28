# 🎯 Polymarket Arbitrage Bot

Бот для поиска арбитражных возможностей между **Polymarket** и букмекерскими конторами (**Fonbet**, **Winline**, **1xBet**).

## Архитектура

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Polymarket    │     │   Arbitrage  │     │  Telegram Bot   │
│   Gamma API     │────▶│    Engine    │────▶│    Alerts +     │
│  (sports mkts)  │     │              │     │   Management    │
└─────────────────┘     │  ┌────────┐  │     └─────────────────┘
                        │  │Matcher │  │
┌─────────────────┐     │  │(fuzzy) │  │     ┌─────────────────┐
│  Bookmakers     │     │  └────────┘  │     │   Auto-Betting  │
│  Fonbet         │────▶│              │────▶│  Polymarket     │
│  Winline        │     │  ┌────────┐  │     │  CLOB API       │
│  1xBet          │     │  │ Calc   │  │     └─────────────────┘
└─────────────────┘     │  └────────┘  │
                        └──────────────┘
```

## Как это работает

1. **Сбор данных** — параллельно получаем котировки с Polymarket и коэффициенты с БК
2. **Матчинг** — сопоставляем события с помощью fuzzy matching (rapidfuzz)
3. **Расчёт арбитража** — ищем расхождения: если `1/odds_PM + 1/odds_BK < 1`, есть арбитраж
4. **Алерты** — отправляем найденные возможности в Telegram с расчётом оптимальных ставок
5. **Автоставки** — при включении автоматически размещает ставки на Polymarket через CLOB API

## Быстрый старт

### 1. Установка

```bash
# Клонировать репо
git clone https://github.com/Frenchman001/tea777.git
cd tea777

# Создать виртуальное окружение
python3.11 -m venv .venv
source .venv/bin/activate

# Установить зависимости
pip install -e ".[dev]"
```

### 2. Настройка

```bash
# Скопировать конфиг
cp .env.example .env

# Отредактировать .env — заполнить:
# - TELEGRAM_BOT_TOKEN (получить у @BotFather)
# - TELEGRAM_CHAT_ID (получить у @userinfobot)
# - POLYMARKET_PRIVATE_KEY (для автоставок)
```

### 3. Запуск

```bash
# Запуск сканера
python -m src.main

# Или с явными параметрами
MIN_PROFIT_PERCENT=0.5 SCAN_INTERVAL_SECONDS=60 python -m src.main
```

### 4. Тесты

```bash
pytest tests/ -v
```

## Конфигурация

| Переменная | Описание | По умолчанию |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота | — |
| `TELEGRAM_CHAT_ID` | ID чата для алертов | — |
| `MIN_PROFIT_PERCENT` | Мин. профит для алерта (%) | 1.0 |
| `MAX_STAKE_USD` | Макс. ставка ($) | 100.0 |
| `SCAN_INTERVAL_SECONDS` | Интервал сканирования (сек) | 30 |
| `AUTO_BET_ENABLED` | Включить автоставки | false |
| `DRY_RUN` | Режим тестирования (без реальных ставок) | true |
| `POLYMARKET_PRIVATE_KEY` | Приватный ключ для Polymarket | — |
| `FUZZY_MATCH_THRESHOLD` | Порог fuzzy matching (0-100) | 70 |

## Структура проекта

```
src/
├── main.py              # Точка входа, основной цикл
├── config.py            # Настройки (pydantic-settings)
├── models/
│   └── events.py        # Модели данных (SportEvent, Odds, Arbitrage)
├── polymarket/
│   └── client.py        # Клиент Polymarket Gamma/CLOB API
├── bookmakers/
│   ├── base.py          # Базовый класс парсера
│   ├── fonbet.py        # Парсер Fonbet
│   ├── winline.py       # Парсер Winline
│   └── onebet.py        # Парсер 1xBet
├── arbitrage/
│   ├── engine.py        # Арбитражный движок
│   └── matcher.py       # Event matcher (fuzzy matching)
├── telegram_bot/
│   └── bot.py           # Telegram бот (алерты, управление)
└── betting/
    └── auto_bet.py      # Автоматическое размещение ставок
```

## Формула арбитража

Для двух исходов с коэффициентами `odds_A` (Polymarket) и `odds_B` (БК):

```
margin = 1/odds_A + 1/odds_B

Если margin < 1.0:
  profit% = (1/margin - 1) × 100
  stake_A = budget × (1/odds_A) / margin
  stake_B = budget × (1/odds_B) / margin
```

## Безопасность

- Приватные ключи хранятся только в `.env` (не коммитятся)
- `DRY_RUN=true` по умолчанию — бот не размещает реальные ставки
- Все HTTP-запросы с таймаутами и обработкой ошибок
- Логи ротируются (10 MB, 7 дней)

## TODO / Roadmap

- [ ] Добавить поддержку live-ставок
- [ ] Расширить матчинг (поддержка русских названий команд)
- [ ] Добавить WebSocket для real-time данных с Polymarket
- [ ] Dashboard с историей арбитражей
- [ ] Интеграция с дополнительными БК (Bet365, Pinnacle)
- [ ] Мониторинг здоровья парсеров
