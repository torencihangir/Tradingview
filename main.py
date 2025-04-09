
from flask import Flask, request
import json
import requests
import os
import re
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
    data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

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
        exchange_filter = text[6:].strip().lower() if len(text) > 6 else None
        summary = generate_summary(exchange_filter)
        send_telegram_message(summary)

    return "ok", 200

def parse_signal_line(line):
    try:
        return json.loads(line)
    except:
        return None

def generate_summary(exchange_filter=None):
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
        "matisay": set()
    }

    parsed_lines = [parse_signal_line(line) for line in lines]
    parsed_lines = [s for s in parsed_lines if s]

    for signal_data in parsed_lines:
        symbol = signal_data.get("symbol", "")
        exchange = signal_data.get("exchange", "")
        signal = signal_data.get("signal", "")
        key = f"{symbol} ({exchange})"

        if exchange_filter and exchange_filter not in exchange.lower():
            continue

        signal_lower = signal.lower()

        if "kairi" in signal_lower:
            try:
                kairi_value = float(re.findall(r"[-+]?[0-9]*\.?[0-9]+", signal_lower)[0])
                if kairi_value <= -30:
                    summary["kairi_-30"].add(f"{key}: {kairi_value}")
                elif kairi_value <= -20:
                    summary["kairi_-20"].add(f"{key}: {kairi_value}")

                for other in parsed_lines:
                    if (
                        other.get("symbol") == symbol and
                        re.search(r"(mükemmel alış|alış sayımı)", other.get("signal", ""), re.IGNORECASE)
                    ):
                        summary["güçlü"].add(f"✅ {key} - KAIRI: {kairi_value} ve Alış sinyali birlikte geldi")
                        break
            except:
                continue

        elif re.search(r"mükemmel alış", signal, re.IGNORECASE):
            summary["mükemmel_alış"].add(key)
        elif re.search(r"alış sayımı", signal, re.IGNORECASE):
            summary["alış_sayımı"].add(key)
        elif re.search(r"mükemmel satış", signal, re.IGNORECASE):
            summary["mükemmel_satış"].add(key)
        elif re.search(r"satış sayımı", signal, re.IGNORECASE):
            summary["satış_sayımı"].add(key)
        elif "fib0" in signal_lower:
            summary["matisay"].add(key)

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
