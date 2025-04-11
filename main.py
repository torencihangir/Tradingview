from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime
import pytz
from threading import Lock
from flask-wtf.csrf import CSRFProtect

app = Flask(__name__)
csrf = CSRFProtect(app)

BOT_TOKEN = "7760965138:AAEv82WCEfYPt8EJUhGli8n-EdOlsIViHdE"
CHAT_ID = "5686330513"
SIGNALS_FILE = r"C:\Users\Administrator\Desktop\tradingview-telegram-bot\signals.json"

# Kilit, dosya erişim çakışmalarını önlemek için kullanılıyor
lock = Lock()

def send_telegram_message(message):
    # Mesajı 4096 karakterlik parçalara böl
    for i in range(0, len(message), 4096):
        chunk = message[i:i+4096]
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
        summary = generate_summary(keyword if keyword else "")
        send_telegram_message(summary)

    return "ok", 200

@app.route("/clear_signals", methods=["POST"])
@csrf.exempt  # CSRF korumasını devre dışı bırak
def clear_signals_endpoint():
    try:
        print(">>> /clear_signals endpoint tetiklendi")
        print(f"Headers: {request.headers}")  # Debug headers
        print(f"Data: {request.data}")  # Debug data
        clear_signals()
        return "Sinyaller başarıyla temizlendi!", 200
    except Exception as e:
        print(f"Hata: {e}")
        return f"Hata: {e}", 500

def clear_signals():
    with lock:  # Kilit kullanımı
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                f.write("")
            print("📁 signals.json dosyası temizlendi!")
        else:
            print("📁 signals.json dosyası bulunamadı!")

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
    app.run(host="0.0.0.0", port=5000)  # Port 5000 açık olacak şekilde
