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
            requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                params={"chat_id": CHAT_ID, "text": msg},
                timeout=3
            )
            print("Telegram message sent.")
        except Exception:
            print("Telegram sending error.")

        return "OK", 200
    except Exception as e:
        print("General signal error:", e)
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
        signal = log.get("signal", log.get("message", ""))
        exchange = log.get("exchange", log.get("source", ""))
        sinyaller[symbol].append({"signal": signal.lower(), "exchange": exchange})

    guclu = []
    sadece_kairi = []
    sadece_alis = []

    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        exchange = ""

        for entry in entries:
            signal_text = entry["signal"]
            exchange = entry["exchange"]

            if "kairi" in signal_text:
                try:
                    val = float(signal_text.split("kairi")[1].split()[0])
                    if val <= -20:
                        has_kairi = True
                except:
                    continue

            if "alış" in signal_text:
                has_alis = True

        if has_kairi and has_alis:
            guclu.append(f"✅ {symbol} ({exchange})")
        elif has_kairi:
            sadece_kairi.append(f"• {symbol} ({exchange})")
        elif has_alis:
            sadece_alis.append(f"• {symbol} ({exchange})")

    msg = ""
    if guclu:
        msg += "📊 GÜÇLÜ EŞLEŞEN HİSSELER (KAIRI -20 ve Alış)\n\n"
        msg += "\n".join(guclu[:10]) + "\n\n🔁 Hem KAIRI ≤ -20 hem de Alış sinyali geldi.\n\n"
    else:
        msg += "📊 Bugün güçlü eşleşen sinyal bulunamadı.\n\n"

    if sadece_kairi:
        msg += "💬 KAIRI -20 Gelenler:\n" + "\n".join(sadece_kairi[:10]) + "\n\n"
    if sadece_alis:
        msg += "💬 Alış Gelenler:\n" + "\n".join(sadece_alis[:10]) + "\n"

    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=3
        )
    except:
        print("Telegram gönderim hatası.")

    return "Ozet gönderildi", 200

@app.route("/telegram", methods=["POST"])
def telegram_update():
    update = request.get_json()
    print(">>> TELEGRAM POST VERİSİ:", update)

    if update and "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip().lower()

        if text.startswith("/ozet"):
            try:
                requests.get("http://localhost:10000/ozet", timeout=3)
            except Exception:
                print("Local /ozet çağrısı başarısız oldu.")
    return "OK", 200

@app.route("/")
def home():
    return "Webhook aktif", 200

@app.route("/debug")
def debug():
    return "Debug OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
