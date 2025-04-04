from flask import Flask, request
import requests
import os
import json
import openai
import yfinance as yf
from datetime import datetime
from collections import defaultdict
import re

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOK")
LOG_FILE = "signals.json"

openai.api_key = OPENAI_API_KEY

@app.route("/analiz", methods=["GET"])
def analiz():
    borsa = request.args.get("borsa", "NASDAQ").upper()

    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

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
            if exch.upper() != borsa:
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

    if not uygunlar:
        msg = f"{borsa} borsasında KAIRI -20 altında ve Alış sinyali olan hisse yok."
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg}
        )
        return "No signal", 200

    top5 = uygunlar[:5]
    kalanlar = uygunlar[5:]

    metrikler = []
    for s in top5:
        try:
            info = yf.Ticker(s).info
            metrikler.append({
                "symbol": s,
                "pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "eps": info.get("trailingEps"),
                "growth": info.get("revenueGrowth"),
                "de_ratio": info.get("debtToEquity"),
                "fcf": info.get("freeCashflow")
            })
        except:
            continue

    prompt = f"""Sen bir finansal analiz uzmanısın. Aşağıdaki hisseler {borsa} borsasından geliyor ve KAIRI -20 altında Alış sinyali aldılar. Her hisseyi 10 üzerinden puanla ve kısa yorumla. Ayrıca her metrik için değeri alt alta olacak şekilde göster ve uygun olanlara emoji ekle.\n\nKurallar:\n- PE < 25 iyi, <15 çok iyi ✅\n- EPS pozitif ve artıyorsa 👍\n- Büyüme > %10 ise 📈\n- D/E < 1 sağlıklı 💪\n- FCF pozitifse 🟢\n- Forward PE < 20 cazip 💰\n\nFormat:\n🏆 <b>Sembol</b>\n✅ PE: 15\n👍 EPS: 3.2\n📈 Growth: 0.14\n💪 D/E: 0.6\n🟢 FCF: 1.2B\n💰 FPE: 17\n👉 Puan: 9/10 – kısa açıklama"""

    for m in metrikler:
        prompt += f"\n{m['symbol']}: PE={m['pe']}, EPS={m['eps']}, Growth={m['growth']}, D/E={m['de_ratio']}, FCF={m['fcf']}, FPE={m['forward_pe']}"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Sen finansal analiz yapan bir uzmansın."},
                {"role": "user", "content": prompt}
            ]
        )
        yorum = response.choices[0].message.content
    except Exception as e:
        yorum = f"GPT yorum alınamadı: {e}"

    # Yorumları sıralamak için puanları ayrıştır
    hisse_bloklari = re.split(r"(?:🔸|🔴|🟢)\s+<b>(\w+)</b>\\n", yorum)
    hisse_sirali = []
    for i in range(1, len(hisse_bloklari), 2):
        symbol = hisse_bloklari[i]
        detay = hisse_bloklari[i + 1]
        puan_match = re.search(r"Puan: (\d+)/10", detay)
        puan = int(puan_match.group(1)) if puan_match else 0
        hisse_sirali.append((puan, f"🔸 <b>{symbol}</b>\n" + detay.strip()))

    hisse_sirali.sort(reverse=True)

    mesaj = f"📊 <b>GPT Tavsiyesi – {borsa}:</b>\n\n"
    mesaj += "\n\n".join(h[1] for h in hisse_sirali)
    mesaj += "\n\n"
    if kalanlar:
        mesaj += "📂 Diğer eşleşen hisseler: " + ", ".join(kalanlar)

    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID,
            "text": mesaj,
            "parse_mode": "HTML"
        }
    )
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
