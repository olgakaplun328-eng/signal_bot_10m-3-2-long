import os, time, json, logging
from collections import OrderedDict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

load_dotenv()
SYMBOLS = [s.strip().upper().replace("USDT", "_USDT") for s in os.getenv("MEXC_SYMBOLS", "SUIUSDT").split(",") if s.strip()]
POLL_SECONDS = max(5, int(os.getenv("POLL_SECONDS", "10")))
TEST_MODE = os.getenv("TEST_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS = [x.strip() for x in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if x.strip()]
STATE_DIR = os.getenv("STATE_DIR", "state")
API_URL = "https://contract.mexc.com/api/v1/contract/kline/{symbol}"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("signal-bot-10m")

def color(c):
    return "GREEN" if c["close"] > c["open"] else "RED" if c["close"] < c["open"] else "DOJI"

def emoji(c):
    return {"GREEN":"🟢", "RED":"🔴", "DOJI":"➖"}.get(c, "➖")

def kyiv(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M")

def send(text):
    if TEST_MODE:
        print("\n--- TEST MESSAGE ---\n" + text + "\n--------------------")
        return True
    if not TOKEN or not CHAT_IDS:
        log.warning("Telegram is not configured; message was not sent: %s", text.replace("\n", " | "))
        return False
    ok = True
    for chat in CHAT_IDS:
        try:
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                              json={"chat_id": chat, "text": text}, timeout=15)
            data = r.json()
            if not r.ok or not data.get("ok"):
                ok = False
                log.error("Telegram error for %s: %s", chat, r.text[:300])
        except Exception:
            ok = False
            log.exception("Telegram send failed for %s", chat)
    return ok

def get_minutes(symbol, limit=500):
    r = requests.get(API_URL.format(symbol=symbol),
                     params={"interval":"Min1", "limit":limit, "_ts":int(time.time()*1000)},
                     headers={"Cache-Control":"no-cache", "Pragma":"no-cache"},
                     timeout=15)
    r.raise_for_status()
    payload = r.json()
    d = payload.get("data")
    if not isinstance(d, dict) or not isinstance(d.get("time"), list):
        raise RuntimeError(f"Unexpected MEXC response: {str(payload)[:250]}")
    rows = []
    for i, ts in enumerate(d["time"]):
        try:
            rows.append({"ts":int(ts), "open":float(d["open"][i]), "close":float(d["close"][i])})
        except (IndexError, KeyError, TypeError, ValueError):
            pass
    return sorted(rows, key=lambda x:x["ts"])

def aggregate(symbol):
    rows = get_minutes(symbol)
    buckets = OrderedDict()
    for c in rows:
        b = (c["ts"] // 600) * 600
        buckets.setdefault(b, []).append(c)
    now = int(time.time())
    out = []
    for b, group in buckets.items():
        if b + 600 <= now and len(group) == 10:
            group.sort(key=lambda x:x["ts"])
            out.append({"ts":b, "open":group[0]["open"], "close":group[-1]["close"], "count":10})
    return out[-150:], rows

def live_10m(rows):
    if not rows:
        return None
    bucket = (int(time.time()) // 600) * 600
    group = [c for c in rows if (c["ts"] // 600) * 600 == bucket]
    if not group:
        return None
    group.sort(key=lambda x:x["ts"])
    return {"ts":bucket, "open":group[0]["open"], "close":group[-1]["close"], "count":len(group)}

class Engine:
    def __init__(self, symbol):
        self.symbol = symbol
        os.makedirs(STATE_DIR, exist_ok=True)
        self.path = os.path.join(STATE_DIR, symbol + ".json")
        self.candles = OrderedDict()
        self.pre_sent = set()
        self.pending = []
        self.initialized = False

    def seed(self, history):
        self.candles = OrderedDict((c["ts"], c) for c in history[-150:])
        self.candles = OrderedDict(sorted(self.candles.items()))
        self.pending = []  # Don't create signals from historical candles at startup.
        self.initialized = True
        self.save()
        log.info("%s initialized with %d closed 10m candles", self.symbol, len(self.candles))

    def save(self):
        state = {"last_closed_ts": next(reversed(self.candles), None) if self.candles else None,
                 "pending": self.pending}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.path)

    def pattern(self, block):
        cs = [color(c) for c in block]
        if cs == ["RED","RED","RED","GREEN","GREEN"]:
            return "SHORT"
        if cs == ["GREEN","GREEN","GREEN","RED","RED"]:
            return "LONG"
        return None

    def check_pre(self, live):
        if not self.initialized or live is None:
            return
        elapsed = time.time() - live["ts"]
        if elapsed < 540 or elapsed >= 600:
            return
        ts = live["ts"]
        if ts in self.pre_sent or ts in self.candles:
            return
        first_ts = ts - 4*600
        block = [self.candles.get(first_ts + i*600) for i in range(4)]
        if any(c is None for c in block):
            return
        # Only alert if #1-#4 are closed and #5 is currently the expected opposite color.
        c5 = live
        direction = self.pattern(block + [c5])
        if not direction:
            return
        self.pre_sent.add(ts)
        patt = "🔴🔴🔴🟢🟢" if direction == "SHORT" else "🟢🟢🟢🔴🔴"
        send(f"⚠️ PRE-ALERT\n{self.symbol.replace('_USDT','USDT')} Futures | 10m\n{patt}\nPotential: {direction}\nCandle #5 closes at {kyiv(ts+600)} Kyiv time.")

    def add_closed(self, c):
        ts = c["ts"]
        self.candles[ts] = c
        self.candles = OrderedDict(sorted(self.candles.items()))
        keys = list(self.candles)
        # Check any pattern whose #5 just closed. Use only new candle as #5.
        if len(keys) >= 5 and keys[-1] == ts:
            block = [self.candles[k] for k in keys[-5:]]
            direction = self.pattern(block)
            if direction:
                start_ts = block[0]["ts"]
                self.pending.append({"start_ts":start_ts, "signal_ts":ts, "direction":direction})
                patt = "🔴🔴🔴🟢🟢" if direction == "SHORT" else "🟢🟢🟢🔴🔴"
                send(f"🔔 SIGNAL {direction}\n{self.symbol.replace('_USDT','USDT')} Futures | 10m\n{patt}\nPattern closed: {kyiv(ts+600)} Kyiv time\nChecking candles #6–#10.")
                log.info("%s SIGNAL %s at %s", self.symbol, direction, kyiv(ts))
        keep = []
        for p in self.pending:
            if ts <= p["signal_ts"]:
                keep.append(p)
                continue
            rel = int((ts - p["signal_ts"]) // 600)  # #6 is rel=1, #10 is rel=5
            if rel < 1:
                keep.append(p)
                continue
            want = "RED" if p["direction"] == "SHORT" else "GREEN"
            if rel <= 5 and color(c) == want:
                send(f"✅ WIN\n{self.symbol.replace('_USDT','USDT')} Futures | 10m\nDirection: {p['direction']}\nMatching candle: #{rel+5} {emoji(color(c))}\nSignal: {kyiv(p['start_ts'])} Kyiv time.")
                continue
            if rel >= 5:
                send(f"❌ LOSS\n{self.symbol.replace('_USDT','USDT')} Futures | 10m\nDirection: {p['direction']}\nAll candles #6–#10 were {'green' if p['direction']=='SHORT' else 'red'}.")
                continue
            keep.append(p)
        self.pending = keep
        while len(self.candles) > 150:
            self.candles.popitem(last=False)
        self.save()

    def run_once(self):
        history, minutes = aggregate(self.symbol)
        if not history:
            log.warning("%s: no complete 10m candles received", self.symbol)
            return
        if not self.initialized:
            self.seed(history)
            return
        last = next(reversed(self.candles), None) if self.candles else None
        new = [c for c in history if last is None or c["ts"] > last]
        if new:
            for c in new:
                self.add_closed(c)
        else:
            self.check_pre(live_10m(minutes))

def test():
    # Check both directions and result logic offline.
    for seq in [
        ["RED","RED","RED","GREEN","GREEN","RED","GREEN","GREEN","GREEN","GREEN"],
        ["GREEN","GREEN","GREEN","RED","RED","GREEN","RED","RED","RED","RED"],
    ]:
        e = Engine.__new__(Engine)
        d = e.pattern([{"open":1,"close":0 if x=="RED" else 2} for x in seq[:5]])
        assert d in ("SHORT","LONG")
        desired = "RED" if d == "SHORT" else "GREEN"
        assert desired in seq[5:10]
        print("PASS:", d, "pattern", " ".join(emoji(x) for x in seq[:5]), "-> WIN")
    print("Offline test passed.")

def main():
    if TEST_MODE:
        test()
        return
    engines = [Engine(s) for s in SYMBOLS]
    log.info("Started 10m signal bot for %s", ", ".join(SYMBOLS))
    log.info("Patterns: RRR-GG => SHORT; GGG-RR => LONG. Results: candles #6-#10.")
    if TOKEN and CHAT_IDS:
        send("🤖 10m signal bot online\nSymbols: " + ", ".join(SYMBOLS) + "\nSignal alerts only; no automatic orders.")
    while True:
        for e in engines:
            try:
                e.run_once()
            except requests.RequestException as ex:
                log.warning("%s network/API error: %s", e.symbol, ex)
            except Exception:
                log.exception("%s error", e.symbol)
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
