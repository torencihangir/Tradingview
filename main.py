
from flask import Flask, request
import requests
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

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
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol", "UNKNOWN")
        signal_text = data.get("signal", "No signal")
        exchange = data.get("exchange", "Unknown Exchange")
        log_signal(data)

        msg = f"🚨 Signal Received!\n📈 {symbol} ({exchange})\n💬 {signal_text}"
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                params={"chat_id": CHAT_ID, "text": msg},
                timeout=3
            )
            print("Telegram message sent.")
        except Exception:
            print("Telegram sending error.")

        return "OK", 200
    except Exception:
        print("General signal error.")
        return "Internal Server Error", 500

@app.route("/ozet", methods=["GET"])
def ozet():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    sinyaller = defaultdict(list)
    for log in logs:
        symbol = log.get("symbol", log.get("ticker", ""))
        signal = log.get("signal", log.get("message", "")).upper()
        exchange = log.get("exchange", log.get("source", ""))
        sinyaller[symbol].append({"signal": signal, "exchange": exchange})

    güçlü_sinyaller = []

    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        kairi_val = None
        exchange = "Unknown"

        for entry in entries:
            signal_text = entry["signal"]
            exchange = entry["exchange"]

            if "KAIRI" in signal_text:
                try:
                    val = float(signal_text.split("KAIRI")[1].split()[0])
                    kairi_val = val
                    if val <= -20:
                        has_kairi = True
                except:
                    continue
            if "ALIŞ SAYIMI" in signal_text or "MÜKEMMEL ALIŞ" in signal_text:
                has_alis = True

        if has_kairi and has_alis:
            güçlü_sinyaller.append(f"✅ {symbol} ({exchange})")

    if güçlü_sinyaller:
        msg = "📊 GÜÇLÜ EŞLEŞEN HİSSELER:\n\n"
        msg += "\n".join(güçlü_sinyaller[:10])
        msg += "\n\n🔁 Hem KAIRI ≤ -20 hem de Alış sinyali geldi."
    else:
        msg = "📊 Bugün güçlü eşleşen sinyal bulunamadı."

    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=3
        )
    except:
        print("Telegram gönderim hatası.")
    return "Ozet gönderildi", 200

@app.route("/")
def home():
    return "Webhook aktif", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
