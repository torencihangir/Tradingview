from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime
import pytz
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = "signals.json"
ANALIZ_FILE = "analiz.json"

def escape_markdown(text):
    # Sadece özel karakterlerden bazılarını kaçır
    escape_chars = r"*_[~`>|{}"
    return re.sub(r"([{}])".format(re.escape(escape_chars)), r"\\\1", text)

def send_telegram_message(message):
    # Mesajı Markdown formatına uygun şekilde kaçar
    escaped_message = escape_markdown(message)

    # Mesajı 4096 karakterlik parçalara böl
    for i in range(0, len(escaped_message), 4096):
        chunk = escaped_message[i:i+4096]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown"
        }
        try:
            r = requests.post(url, json=data, timeout=5)
            print(">>> Telegram yanıtı:", r.status_code, r.text, flush=True)
        except Exception as e:
            print("Telegram'a mesaj gönderilemedi:", e, flush=True)

@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        print(">>> /signal endpoint tetiklendi")
        if request.is_json:
            data = request.get_json()
        else:
            raw = request.data.decode("utf-8")
            match = re.match(r"(.*?) \((.*?)\) - (.*)", raw)
            if match:
                symbol, exchange, signal = match.groups()
                data = {
                    "symbol": symbol.strip(),
                    "exchange": exchange.strip(),
                    "signal": signal.strip()
                }
            else:
                data = {"symbol": "Bilinmiyor", "exchange": "Bilinmiyor", "signal": raw.strip()}

        # Zaman damgası ekle
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

        symbol = data.get("symbol") or "Bilinmiyor"
        exchange = data.get("exchange") or "Bilinmiyor"
        signal = data.get("signal") or "Bilinmiyor"

        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        message = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange_display})\n📍 _{signal}_"
        send_telegram_message(message)

        return "ok", 200
    except Exception as e:
        return str(e), 500

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    message = request.json.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id", "")

    if text.startswith("/ozet"):
        print(">>> /ozet komutu alındı")
        keyword = text[6:].strip().lower() if len(text) > 6 else None

        # Anahtar kelime kontrolü ekliyoruz
        if keyword in ["bats", "nasdaq", "bist_dly", "binance"]:
            print(f">>> /ozet komutu için anahtar kelime: {keyword}")
            summary = generate_summary(keyword)
        else:
            summary = generate_summary()  # Varsayılan tüm sinyaller için özet

        send_telegram_message(summary)

    elif text.startswith("/analiz"):
        print(">>> /analiz komutu alındı")
        tickers_input = text[8:].strip()
        tickers = [ticker.strip() for ticker in tickers_input.split(",")]
        if not tickers:
            send_telegram_message("Lütfen bir veya daha fazla hisse kodu belirtin. Örnek: /analiz AAPL,MSFT,AMD")
        else:
            response = generate_analiz_response(tickers)
            send_telegram_message(response)

    return "ok", 200

@app.route("/clear_signals", methods=["POST"])
def clear_signals_endpoint():
    try:
        clear_signals()  # signals.json dosyasını temizler
        return "signals.json dosyası temizlendi!", 200
    except Exception as e:
        return str(e), 500

def parse_signal_line(line):
    try:
        return json.loads(line)
    except:
        return None

def load_analiz_json():
    try:
        with open(ANALIZ_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print("analiz.json dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError:
        print("analiz.json dosyası geçerli bir JSON formatında değil.")
        return {}

def generate_summary(keyword=None):
    if not os.path.exists(SIGNALS_FILE):
        return "📊 Henüz hiç sinyal kaydedilmedi."

    with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    summary = {
        "güçlü": set(),
        "kairi_-30": set(),
        "kairi_-20": set(),
        "mükemmel_alış": set(),
        "alış_sayımı": set(),
        "mükemmel_satış": set(),
        "satış_sayımı": set(),
        "matisay_-25": set()  # Yeni kategori
    }

    parsed_lines = [parse_signal_line(line) for line in lines]
    parsed_lines = [s for s in parsed_lines if s]

    # Dinamik mesaj oluşturma (boş kategorileri kaldır)
    categories = {
        "📊 GÜÇLÜ EŞLEŞEN SİNYALLER:\n\n": summary["güçlü"],
        "🔴 KAIRI ≤ -30:\n": summary["kairi_-30"],
        "🟠 KAIRI ≤ -20:\n": summary["kairi_-20"],
        "🟢 Mükemmel Alış:\n": summary["mükemmel_alış"],
        "📈 Alış Sayımı Tamamlananlar:\n": summary["alış_sayımı"],
        "🔵 Mükemmel Satış:\n": summary["mükemmel_satış"],
        "📉 Satış Sayımı Tamamlananlar:\n": summary["satış_sayımı"],
        "🟣 Matisay < -25:\n": summary["matisay_-25"]
    }

    msg = ""
    for title, items in categories.items():
        if items:  # Eğer kategori boş değilse ekle
            msg += title + "\n" + "\n".join(items) + "\n\n"

    return msg.strip()

def clear_signals():
    if os.path.exists(SIGNALS_FILE):
        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            f.write("")
        print("📁 signals.json dosyası temizlendi!")

def clear_signals_daily():
    already_cleared = False
    while True:
        now = datetime.now(pytz.timezone("Europe/Istanbul"))
        if now.hour == 23 and now.minute == 59:
            if not already_cleared:
                try:
                    clear_signals()
                    already_cleared = True
                except Exception as e:
                    print("signals.json temizlenirken hata:", e)
        else:
            already_cleared = False
        time.sleep(30)

threading.Thread(target=clear_signals_daily, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
