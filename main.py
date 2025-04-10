
from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime
import pytz

app = Flask(__name__)

BOT_TOKEN = "7760965138:AAEv82WCEfYPt8EJUhGli8n-EdOlsIViHdE"
CHAT_ID = "5686330513"
SIGNALS_FILE = "signals.json"

def send_telegram_message(message):
    print(">>> Telegram'a gönderilecek mesaj:\n", message, flush=True)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
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

