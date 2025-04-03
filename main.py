from flask import Flask, request
import requests
import os
import json
import openai
import yfinance as yf
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOK")
LOG_FILE = "signals.json"

openai.api_key = OPENAI_API_KEY


def log(msg):
    print("[LOG]", msg)


def get_filtered_symbols(exchange):
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        return []

    sinyaller = defaultdict(list)
    for log in logs:
        symbol = log.get("symbol", "")
        signal = log.get("signal", "").upper()
        exch = log.get("exchange", "")
        sinyaller[symbol].append({"signal": signal, "exchange": exch})

    uygunlar = []
    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        kairi_val = None
        exch = ""

        for entry in entries:
            signal = entry["signal"]
            exch = entry["exchange"]
            if exch.upper() != exchange.upper():
                continue
            if "KAIRI" in signal:
                try:
                    val = float(signal.split("KAIRI")[1].split()[0])
                    if val <= -20:
                        has_kairi = True
                        kairi_val = val
                except:
                    pass
            if "ALIŞ SAYIMI" in signal or "MÜKEMMEL ALIŞ" in signal:
                has_alis = True

        if has_kairi and has_alis:
            uygunlar.append(symbol.upper())

    return list(set(uygunlar))


def get_stock_metrics(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        return {
            "symbol": symbol,
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "eps": info.get("trailingEps"),
            "growth": info.get("revenueGrowth"),
            "de_ratio": info.get("debtToEquity"),
            "fcf": info.get("freeCashflow")
        }
    except:
        return None


def generate_gpt_ranking(top_metrics):
    content = """Sen bir finansal analiz uzmanısın. Aşağıdaki hisseler NASDAQ borsasından geliyor ve KAIRI -20 altında Alış sinyali aldılar. Temel verilere göre en cazipten en az cazibe doğru sırala ve nedenlerini kısaca yaz:

Değerlendirme Kuralları:
- PE < 25 iyi, 15 altısı çok iyi
- EPS pozitif ve artıyorsa tercih sebebi
- Büyüme %10'dan fazlaysa olumlu
- D/E < 1 sağlıklı
- FCF pozitifse iyi
- Forward PE < 20 cazip

Hisseler:
"""
    for m in top_metrics:
        content += f"\n{m['symbol']}: PE={m['pe']}, EPS={m['eps']}, Growth={m['growth']}, D/E={m['de_ratio']}, FCF={m['fcf']}, Forward PE={m['forward_pe']}"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Sen finansal analiz yapan bir uzmansın."},
                {"role": "user", "content": content}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"GPT yorum alınamadı: {e}"


@app.route("/analiz", methods=["GET"])
def analiz():
    borsa = request.args.get("borsa", "NASDAQ").upper()
    log(f"/analiz komutu geldi: {borsa}")

    uygun_hisseler = get_filtered_symbols(borsa)

    if not uygun_hisseler:
        msg = f"{borsa} borsasında KAIRI -20 altında ve Alış sinyali olan hisse yok."
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg}
        )
        return "No signal", 200

    top5 = uygun_hisseler[:5]
    kalanlar = uygun_hisseler[5:]

    # 1️⃣ İlk 5 için metrikleri yükle
    metrikler = []
    for s in top5:
        m = get_stock_metrics(s)
        if m:
            metrikler.append(m)

    # 2️⃣ GPT'ye yorumlat
    yorum = generate_gpt_ranking(metrikler)

    # 3️⃣ Mesajı hazırla
    mesaj = f"📊 <b>GPT Tavsiyesi – {borsa}:</b>\n\n"
    mesaj += yorum + "\n\n"
    if kalanlar:
        mesaj += "🗂 Diğer eşleşen hisseler: " + ", ".join(kalanlar)

    # 4️⃣ Telegrama gönder
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID,
            "text": mesaj,
            "parse_mode": "HTML"
        }
    )
    return "OK", 200


# ✅ Render'da portu tanımlıyoruz
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
