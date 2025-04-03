from flask import Flask, request
import requests
import os
import json
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")
LOG_FILE = "signals.json"

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
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
    )
    return "OK", 200

@app.route("/")
def home():
    return "Webhook çalışıyor!", 200

@app.route("/ozet", methods=["GET", "POST"])
def ozet():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    sinyaller = defaultdict(list)

    for log in logs:
        symbol = log.get("symbol", "")
        signal_text = log.get("signal", "").upper()
        exchange = log.get("exchange", "Bilinmiyor")
        sinyaller[symbol].append({"signal": signal_text, "exchange": exchange})

    uygunlar = []

    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        kairi_val = None
        exchange = "Bilinmiyor"

        for entry in entries:
            signal_text = entry["signal"]
            if "KAIRI" in signal_text:
                try:
                    val = float(signal_text.split("KAIRI")[1].split()[0])
                    if val <= -20:
                        has_kairi = True
                        kairi_val = val
                        exchange = entry["exchange"]
                except:
                    continue

            if "MÜKEMMEL ALIŞ" in signal_text or "ALIŞ SAYIMI" in signal_text:
                has_alis = True
                exchange = entry["exchange"]

        if has_kairi and has_alis:
            uygunlar.append(f"✅ {symbol} ({exchange}) - KAIRI: {kairi_val} ve Alış sinyali birlikte geldi")

    ozet_msg = "📊 <b>GÜÇLÜ EŞLEŞEN SİNYALLER:</b>\n\n"
    if uygunlar:
        ozet_msg += "\n".join(uygunlar)
    else:
        ozet_msg += "Bugün eşleşen sinyal bulunamadı."

    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID,
            "text": ozet_msg,
            "parse_mode": "HTML"
        }
    )
    return "Ozet gönderildi", 200

@app.route("/telegram", methods=["POST"])
def telegram_update():
    update = request.get_json()
    if update and "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip().lower()

        if text.startswith("/ozet"):
            ozet_msg = ozet_komutu_guncel()  # direkt çağırmak yerine fonksiyonu kullanırsan böyle yazılabilir
            requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                params={
                    "chat_id": chat_id,
                    "text": ozet_msg,
                    "parse_mode": "HTML"
                }
            )
    return "OK", 200
