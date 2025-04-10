
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

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    message = request.json.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id", "")

    if text.startswith("/ozet"):
        print(">>> /ozet komutu alındı")
        keyword = text[6:].strip().lower() if len(text) > 6 else None
        summary = generate_summary(keyword if keyword else "")
        send_telegram_message(summary)

    return "ok", 200

# --- aşağıdaki fonksiyonlar değişmeden aynı şekilde devam eder ---
def parse_signal_line(line):
    try:
        return json.loads(line)
    except:
        return None

def generate_summary(keyword=None):
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

        if keyword:
            keyword_map = {
                "bist": "bist_dly",
                "nasdaq": "bats"
            }
            mapped = keyword_map.get(keyword, keyword)
            keyword = mapped

            combined = f"{symbol} {exchange} {signal}".lower()
            if keyword not in combined:
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

def clear_signals_daily():
    already_cleared = False
    while True:
        now = datetime.now(pytz.timezone("Europe/Istanbul"))
        if now.hour == 23 and now.minute == 59:
            if not already_cleared:
                try:
                    if os.path.exists(SIGNALS_FILE):
                        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                            f.write("")
                        print("📁 signals.json dosyası temizlendi (Türkiye saatiyle 23:59)")
                    already_cleared = True
                except Exception as e:
                    print("signals.json temizlenirken hata:", e)
        else:
            already_cleared = False
        time.sleep(30)

threading.Thread(target=clear_signals_daily, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
