
from flask import Flask, request
import json
import requests
import os
from datetime import datetime

app = Flask(__name__)

BOT_TOKEN = "7760965138:AAH4ZdrJjnXJ36UWZUh1f0-VWL-FyUBgh54"
CHAT_ID = "5686330513"

SIGNALS_FILE = "signals.json"

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

@app.route("/signal", methods=["POST"])
def receive_signal():
    data = request.json
    data["timestamp"] = datetime.utcnow().isoformat()
    with open(SIGNALS_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    signal = data.get("signal")

    message = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange})\n📍 _{signal}_"
    send_telegram_message(message)

    return "ok", 200

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    message = request.json["message"]
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text.startswith("/ozet"):
        summary = generate_summary()
        send_telegram_message(summary)

    return "ok", 200

def parse_signal_line(line):
    try:
        return json.loads(line)
    except:
        return None

def generate_summary():
    if not os.path.exists(SIGNALS_FILE):
        return "📊 Henüz hiç sinyal kaydedilmedi."

    with open(SIGNALS_FILE, "r") as f:
        lines = f.readlines()

    summary = {
        "güçlü": [],
        "kairi_-30": [],
        "kairi_-20": [],
        "mükemmel_alış": [],
        "alış_sayımı": [],
        "mükemmel_satış": [],
        "satış_sayımı": [],
        "matisay": []
    }

    for line in lines:
        signal_data = parse_signal_line(line)
        if not signal_data:
            continue

        symbol = signal_data.get("symbol", "")
        exchange = signal_data.get("exchange", "")
        signal = signal_data.get("signal", "").lower()
        key = f"{symbol} ({exchange})"

        if "kairi" in signal:
            try:
                kairi_value = float(signal.split("kairi")[1].split("seviyesinde")[0].strip())
                if kairi_value <= -30:
                    summary["kairi_-30"].append(f"{key}: {kairi_value}")
                elif kairi_value <= -20:
                    summary["kairi_-20"].append(f"{key}: {kairi_value}")

                # Güçlü eşleşme kontrolü
                for other_line in lines:
                    other = parse_signal_line(other_line)
                    if other and other.get("symbol") == symbol and (
                        "mükemmel alış" in other.get("signal", "").lower() or
                        "alış sayımı" in other.get("signal", "").lower()
                    ):
                        summary["güçlü"].append(f"✅ {key} - KAIRI: {kairi_value} ve Alış sinyali birlikte geldi")
                        break
            except:
                continue

        elif "mükemmel alış" in signal:
            summary["mükemmel_alış"].append(key)
        elif "alış sayımı" in signal:
            summary["alış_sayımı"].append(key)
        elif "mükemmel satış" in signal:
            summary["mükemmel_satış"].append(key)
        elif "satış sayımı" in signal:
            summary["satış_sayımı"].append(key)
        elif "fib0" in signal:
            summary["matisay"].append(key)

    msg = "📊 GÜÇLÜ EŞLEŞEN SİNYALLER:\n\n"
    msg += "\n".join(summary["güçlü"]) or "Yok"

    msg += "\n\n🔴 KAIRI ≤ -30:\n" + ("\n".join(summary["kairi_-30"]) or "Yok")
    msg += "\n\n🟠 KAIRI ≤ -20:\n" + ("\n".join(summary["kairi_-20"]) or "Yok")
    msg += "\n\n🟢 Mükemmel Alış:\n" + ("\n".join(summary["mükemmel_alış"]) or "Yok")
    msg += "\n\n📈 Alış Sayımı Tamamlananlar:\n" + ("\n".join(summary["alış_sayımı"]) or "Yok")
    msg += "\n\n🔵 Mükemmel Satış:\n" + ("\n".join(summary["mükemmel_satış"]) or "Yok")
    msg += "\n\n📉 Satış Sayımı Tamamlananlar:\n" + ("\n".join(summary["satış_sayımı"]) or "Yok")
    msg += "\n\n🟤 Matisay Fib0:\n" + ("\n".join(summary["matisay"]) or "Yok")

    return msg
