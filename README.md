# Telegram signal bot — 10m

## Rules
- `#1 🔴 #2 🔴 #3 🔴 #4 🟢 #5 🟢` → PRE-ALERT in the last minute of #5, then SIGNAL SHORT after #5 closes.
- `#1 🟢 #2 🟢 #3 🟢 #4 🔴 #5 🔴` → PRE-ALERT in the last minute of #5, then SIGNAL LONG after #5 closes.
- SHORT: WIN if at least one of candles #6–#10 closes red; LOSS if all five are green.
- LONG: WIN if at least one of candles #6–#10 closes green; LOSS if all five are red.
- Candle color uses close vs open. Doji (close == open) does not match a pattern or count as a win.

## Windows setup
1. Install Python 3.10+ and tick “Add Python to PATH”.
2. Unzip this folder.
3. Run `run_windows.bat`. On first run it creates `.env` and opens it in Notepad.
4. Create a bot with Telegram `@BotFather`; paste the token into `TELEGRAM_BOT_TOKEN`.
5. Set `TELEGRAM_CHAT_ID`. Send a message to your bot first. Use your numeric Telegram chat ID; for a group, add the bot to the group and use the group ID.
6. Save `.env`, then run `run_windows.bat` again.

## Market and timeframe
- Default symbol is SUIUSDT. Configure `MEXC_SYMBOLS=SUIUSDT` or comma-separated symbols.
- Uses MEXC USDT-M futures 1-minute public candles and aggregates complete 10-minute candles.
- Make sure each selected contract exists on MEXC Futures.

## Offline test
Set `TEST_MODE=true` in `.env` and run `python bot.py`. This tests both pattern directions without contacting the exchange or sending Telegram messages.

## Notes
- Alerts only; no orders are placed.
- The computer must remain online while the bot runs.
- On startup, historical candles are loaded as reference; old signals are not sent retroactively.
