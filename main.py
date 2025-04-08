
from flask import Flask, request
import requests
import os
import json
import openai
import yfinance as yf
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOK")
LOG_FILE = "signals.json"

openai.api_key = OPENAI_API_KEY

def log_signal(data):
    data["timestamp"] = datetime.now().isoformat()
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []
    logs.append(data)
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "UNKNOWN")
    signal_text = data.get("signal", "Sinyal Yok")
    exchange = data.get("exchange", "Borsa Bilinmiyor")
    log_signal(data)
    msg = f"🚨 Sinyal Geldi!\n📈 {symbol} ({exchange})\n💬 {signal_text}"

    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=3
        )
        print(f"Telegram yanıtı: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

    return "OK", 200

@app.route("/")
def home():
    return "Webhook aktif", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
