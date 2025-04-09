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
        json.dump(logs, logs, indent=2)

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
        signal = log.get("signal", log.get("message", "")).lower()
        exchange = log.get("exchange", log.get("source", "")).upper()
        sinyaller[symbol].append({"signal": signal, "exchange": exchange})

    güçlü_sinyaller = []
    kairi30 = []
    kairi20 = []
    mükemmel_alis = []
    mükemmel_satis = []
    alis_sayimi = []
    satis_sayimi = []

    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        kairi_val = None
        exchange = "Unknown"

        for entry in entries:
            signal_text = entry["signal"]
            exchange = entry["exchange"]

            if "kairi" in signal_text:
                try:
                    val = float(signal_text.split("kairi")[1].split()[0])
                    kairi_val = val
                    if val <= -30:
                        kairi30.append(f"{symbol} ({exchange}): {val}")
                    elif val <= -20:
                        kairi20.append(f"{symbol} ({exchange}): {val}")
                    if val <= -20:
                        has_kairi = True
                except:
                    continue

            if "mükemmel alış" in signal_text or "alış sayımı" in signal_text:
                has_alis = True

            if "mükemmel alış" in signal_text:
                mükemmel_alis.append(f"{symbol} ({exchange})")
            if "mükemmel satış" in signal_text:
                mükemmel_satis.append(f"{symbol} ({exchange})")
            if "alış sayımı" in signal_text:
                alis_sayimi.append(f"{symbol} ({exchange})")
            if "satış sayımı" in signal_text:
                satis_sayimi.append(f"{symbol} ({exchange})")

        if has_kairi and has_alis:
            güçlü_sinyaller.append(f"✅ {symbol} ({exchange})")

    msg = ""

    if güçlü_sinyaller:
        msg += "📊 GÜÇLÜ EŞLEŞEN SİNYALLER:\n" + "\n".join(güçlü_sinyaller[:10]) + "\n\n"
    else:
        msg += "📊 GÜÇLÜ EŞLEŞEN SİNYAL BULUNAMADI.\n\n"

    if kairi30:
        msg += "🔴 KAIRI ≤ -30:\n" + "\n".join(kairi30[:10]) + "\n\n"
    if kairi20:
        msg += "🟠 KAIRI ≤ -20:\n" + "\n".join(kairi20[:10]) + "\n\n"
    if mükemmel_alis:
        msg += "🟢 Mükemmel Alış:\n" + "\n".join(mükemmel_alis[:10]) + "\n\n"
    if mükemmel_satis:
        msg += "🔵 Mükemmel Satış:\n" + "\n".join(mükemmel_satis[:10]) + "\n\n"
    if alis_sayimi:
        msg += "🟢 Alış Sayımı:\n" + "\n".join(alis_sayimi[:10]) + "\n\n"
    if satis_sayimi:
        msg += "🔵 Satış Sayımı:\n" + "\n".join(satis_sayimi[:10]) + "\n\n"

    if msg.strip() == "":
        msg = "Bugün sinyal kaydı bulunamadı."

    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=5
        )
    except:
        print("Telegram gönderim hatası.")
    return "Ozet gönderildi", 200

@app.route("/telegram", methods=["POST"])
def telegram_update():
    update = request.get_json()
    if update and "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        if text.lower().startswith("/ozet"):
            try:
                parts = text.split()
                if len(parts) > 1:
                    borsa = parts[1].upper()
                    filtered = []
                    try:
                        with open(LOG_FILE, "r") as f:
                            logs = json.load(f)
                        filtered = [x for x in logs if x.get("exchange", "").upper() == borsa]
                        with open(LOG_FILE, "w") as f:
                            json.dump(filtered, f, indent=2)
                    except:
                        pass
                requests.get("http://localhost:10000/ozet", timeout=3)
            except Exception:
                print("Local /ozet çağrısı başarısız oldu.")
    return "OK", 200

@app.route("/")
def home():
    return "Webhook aktif", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
