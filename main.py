# -*- coding: utf-8 -*-
from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime, timedelta # timedelta artık sadece clear_signals_daily için kullanılmıyordu, isterseniz kaldırılabilir ama zararı yok.
import pytz # Zaman dilimi için
from dotenv import load_dotenv
import traceback # Hata ayıklama için
import math # Analiz sıralaması için

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# --- Global Değişkenler ve Ayarlar ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")
try:
    TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Istanbul"))
except pytz.exceptions.UnknownTimeZoneError:
    print(f"❌ Uyarı: .env TIMEZONE '{os.getenv('TIMEZONE')}' geçersiz. 'Europe/Istanbul' kullanılacak.")
    TIMEZONE = pytz.timezone("Europe/Istanbul")

# Bellekte verileri tutmak için
signals_data = {}
analiz_data = {}
bist_analiz_data = {}
last_signal_time = {}

# Eşzamanlılık için Kilitler
signals_lock = threading.Lock()
analiz_lock = threading.Lock()
bist_analiz_lock = threading.Lock()

# --- Yardımcı Fonksiyonlar ---

def escape_markdown_v2(text):
    """Telegram MarkdownV2 için özel karakterleri kaçırır."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    text = text.replace('\\', '\\\\')
    for char in escape_chars: text = text.replace(char, f'\\{char}')
    return text

def send_telegram_message(message):
    """Telegram'a mesaj gönderir (MarkdownV2)."""
    if not BOT_TOKEN or not CHAT_ID: print("❌ Hata: BOT_TOKEN veya CHAT_ID ayarlanmamış."); return
    escaped_message = message
    max_length = 4096
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": chunk, "parse_mode": "MarkdownV2"}
        try:
            r = requests.post(url, json=data, timeout=30)
            r.raise_for_status(); print(f"✅ Telegram yanıtı: {r.status_code}"); time.sleep(0.5)
        except requests.exceptions.Timeout: print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {r.text}"); print(f"❌ Mesaj: {chunk[:100]}...")
        except requests.exceptions.RequestException as e: print(f"❌ Telegram RequestException: {e}")
        except Exception as e: print(f"❌ Telegram gönderim hatası: {e}"); print(traceback.format_exc())

def load_json_file(filepath):
    """Genel JSON dosyası yükleme."""
    try:
        if not filepath: print("❌ Hata: Geçersiz dosya yolu."); return None
        if not os.path.exists(filepath): print(f"⚠️ {filepath} bulunamadı."); return {}
        if os.path.getsize(filepath) == 0: print(f"⚠️ {filepath} boş."); return {}
        with open(filepath, "r", encoding="utf-8") as file: data = json.load(file)
        print(f"✅ {filepath} yüklendi."); return data
    except Exception as e:
        print(f"❌ Hata ({filepath} okuma): {e}")
        if isinstance(e, json.JSONDecodeError):
            try:
                with open(filepath, "r", encoding="utf-8") as f_err: print(f"Dosya başı: {f_err.read(200)}...")
            except Exception: pass
        print(traceback.format_exc()); return {}

def save_json_file(filepath, data):
    """Genel JSON dosyası kaydetme."""
    try:
        if not filepath: print("❌ Hata: Geçersiz dosya yolu."); return False
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory): os.makedirs(directory); print(f"ℹ️ Dizin oluşturuldu: {directory}")
        with open(filepath, "w", encoding="utf-8") as file: json.dump(data, file, ensure_ascii=False, indent=4)
        print(f"✅ Veri kaydedildi: {filepath}"); return True
    except Exception as e: print(f"❌ Hata ({filepath} yazma): {e}"); print(traceback.format_exc()); return False

def load_signals():
    """signals.json yükler."""
    global signals_data, last_signal_time
    print(f"🔄 Sinyal verileri: {SIGNALS_FILE}")
    with signals_lock:
        loaded_data = load_json_file(SIGNALS_FILE)
        if loaded_data is not None:
            signals_data = loaded_data; last_signal_time = {}
            for borsa, signal_list in signals_data.items():
                if signal_list:
                    try:
                        latest_signal = max(signal_list, key=lambda s: datetime.strptime(s.get('time', '1970-01-01 00:00:00 +0000')[:19], "%Y-%m-%d %H:%M:%S"))
                        last_signal_time[borsa] = latest_signal.get('time')
                    except Exception as dt_err: print(f"⚠️ {borsa} son sinyal zamanı hatası: {dt_err}")
            print(f"✅ Sinyaller yüklendi: {list(signals_data.keys())}")
        else: print("❌ Sinyal okuma hatası."); signals_data = signals_data or {}

def save_signals():
    """signals.json kaydeder."""
    print(f"💾 Sinyal verileri: {SIGNALS_FILE}")
    with signals_lock:
        if not save_json_file(SIGNALS_FILE, signals_data): print(f"❌ Sinyal kaydetme hatası: {SIGNALS_FILE}")

def load_analiz_data():
    """analiz.json yükler."""
    global analiz_data
    print(f"🔄 Analiz verileri: {ANALIZ_FILE}")
    with analiz_lock:
        loaded_data = load_json_file(ANALIZ_FILE)
        if loaded_data is not None: analiz_data = loaded_data; print(f"✅ Analiz yüklendi: {len(analiz_data)} kayıt.")
        else: print("❌ Analiz okuma hatası."); analiz_data = analiz_data or {}

def load_bist_analiz_data():
    """analiz_sonuclari.json yükler."""
    global bist_analiz_data
    print(f"🔄 BIST Analiz verileri: {ANALIZ_SONUCLARI_FILE}")
    with bist_analiz_lock:
        loaded_data = load_json_file(ANALIZ_SONUCLARI_FILE)
        if loaded_data is not None: bist_analiz_data = loaded_data; print(f"✅ BIST Analiz yüklendi: {len(bist_analiz_data)} kayıt.")
        else: print("❌ BIST Analiz okuma hatası."); bist_analiz_data = bist_analiz_data or {}

def parse_signal_line(line):
    """Gelen alert mesajını ayrıştırır."""
    # (Kod aynı - Kendi formatınıza göre düzenlemeyi unutmayın!)
    line = line.strip();
    if not line: return None
    data = {"raw": line, "borsa": "unknown", "symbol": "N/A", "type": "INFO", "source": "Belirtilmemiş",
            "kairi_value": None, "matisay_value": None, "alis_sinyali_flag": False,
            "mukemmel_alis_flag": False, "alis_sayimi_tamam_flag": False,
            "mukemmel_satis_flag": False, "satis_sayimi_tamam_flag": False}
    borsa_match = re.match(r"^(\w+)[:\s]+", line, re.IGNORECASE)
    if borsa_match:
        borsa_raw = borsa_match.group(1).lower()
        borsa_map = {"bist": "bist", "xu100": "bist", "nasdaq": "nasdaq", "ndx": "nasdaq",
                     "binance": "binance", "crypto": "binance", "bats": "bats", "us": "bats"}
        data["borsa"] = borsa_map.get(borsa_raw, borsa_raw)
        line = line[len(borsa_match.group(0)):].strip()
    symbol_match = re.search(r"\b([A-Z0-9\./-]{2,})\b", line)
    if symbol_match: data["symbol"] = symbol_match.group(1).upper()
    if re.search(r"\b(AL|ALIM|LONG|BUY)\b", line, re.IGNORECASE): data["type"] = "BUY"
    elif re.search(r"\b(SAT|SATIM|SHORT|SELL)\b", line, re.IGNORECASE): data["type"] = "SELL"
    data["time"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z")
    # YENİ ALANLAR
    try:
        kairi_match = re.search(r"KAIRI:?([-\d\.]+)", line, re.IGNORECASE)
        if kairi_match: data["kairi_value"] = float(kairi_match.group(1))
        matisay_match = re.search(r"Matisay:?([-\d\.]+)", line, re.IGNORECASE)
        if matisay_match: data["matisay_value"] = float(matisay_match.group(1))
        line_lower = line.lower()
        if "alış sinyali" in line_lower or "guclualis" in line_lower: data["alis_sinyali_flag"] = True
        if "mükemmel alış" in line_lower or "mukemmelalis" in line_lower: data["mukemmel_alis_flag"] = True
        if "alış sayımı tamam" in line_lower or "alissayimtamam" in line_lower: data["alis_sayimi_tamam_flag"] = True
        if "mükemmel satış" in line_lower or "mukemmelsatis" in line_lower: data["mukemmel_satis_flag"] = True
        if "satış sayımı tamam" in line_lower or "satissayimtamam" in line_lower: data["satis_sayimi_tamam_flag"] = True
    except ValueError: print(f"⚠️ Sayısal değer ayrıştırılamadı: {line}")
    except Exception as e: print(f"❌ Flag/Değer ayrıştırma hatası: {e} - Satır: {line}")
    if data["borsa"] == "unknown" or data["symbol"] == "N/A": print(f"❌ Ayrıştırma başarısız: {data}"); return None
    print(f"ℹ️ Ayrıştırılan: {data}"); return data

def clear_signals():
    """Bellekteki ve dosyalardaki tüm verileri temizler."""
    # (Kod aynı)
    global signals_data, analiz_data, bist_analiz_data, last_signal_time
    print("🧹 Tüm veriler temizleniyor...")
    success = True
    with signals_lock: signals_data, last_signal_time = {}, {}; success &= save_json_file(SIGNALS_FILE, {})
    with analiz_lock: analiz_data = {}; success &= (not os.path.exists(ANALIZ_FILE) or save_json_file(ANALIZ_FILE, {}))
    with bist_analiz_lock: bist_analiz_data = {}; success &= (not os.path.exists(ANALIZ_SONUCLARI_FILE) or save_json_file(ANALIZ_SONUCLARI_FILE, {}))
    print("✅ Temizlik sonucu:", "Başarılı" if success else "Hatalı")
    return success

# ----- clear_signals_daily FONKSİYONU KALDIRILDI -----

# --- Çekirdek Fonksiyonlar (Komut Yanıtları) ---

def generate_summary(target_borsa=None):
    """İstenen formata göre sinyal özeti oluşturur."""
    # (Kod aynı)
    with signals_lock:
        relevant_signals = []
        if target_borsa:
            target_borsa_lower = target_borsa.lower()
            if target_borsa_lower in ["bist_dly", "bist"]: relevant_signals.extend(signals_data.get("bist", []))
            elif target_borsa_lower in signals_data: relevant_signals = signals_data.get(target_borsa_lower, [])
        else:
            for signal_list in signals_data.values(): relevant_signals.extend(signal_list)
        if not relevant_signals:
            return f"ℹ️ `{escape_markdown_v2(target_borsa.upper() if target_borsa else 'Tüm Borsalar')}` için kayıtlı sinyal yok\\."
        # Kategoriler
        guclu_eslesen, kairi_neg30, kairi_neg20, matisay_neg25, mukemmel_alis, alis_sayim, mukemmel_satis, satis_sayim = [],[],[],[],[],[],[],[]
        for signal in relevant_signals:
            symbol, borsa = signal.get("symbol", "N/A"), signal.get("borsa", "?").upper()
            kairi_val, matisay_val = signal.get("kairi_value"), signal.get("matisay_value")
            alis_sinyali, muk_alis, alis_say, muk_satis, satis_say = signal.get("alis_sinyali_flag", False), signal.get("mukemmel_alis_flag", False), signal.get("alis_sayimi_tamam_flag", False), signal.get("mukemmel_satis_flag", False), signal.get("satis_sayimi_tamam_flag", False)
            kairi_num, matisay_num = None, None
            try: kairi_num = float(kairi_val) if kairi_val is not None else None
            except (ValueError, TypeError): pass
            try: matisay_num = float(matisay_val) if matisay_val is not None else None
            except (ValueError, TypeError): pass
            # Kategori ekleme
            esc_sym, esc_borsa = escape_markdown_v2(symbol), escape_markdown_v2(borsa)
            if alis_sinyali and kairi_num is not None: guclu_eslesen.append(f"✅ `{esc_sym}` \\({esc_borsa}\\) \\- KAIRI: {escape_markdown_v2(f'{kairi_num:.2f}')} & Alış Sinyali")
            if kairi_num is not None:
                 esc_kairi = escape_markdown_v2(f"{kairi_num:.2f}")
                 if kairi_num <= -30: kairi_neg30.append(f"`{esc_sym}` \\({esc_borsa}\\): KAIRI {esc_kairi}")
                 elif kairi_num <= -20: kairi_neg20.append(f"`{esc_sym}` \\({esc_borsa}\\): KAIRI {esc_kairi}")
            if matisay_num is not None and matisay_num < -25: matisay_neg25.append(f"`{esc_sym}` \\({esc_borsa}\\): Matisay {escape_markdown_v2(f'{matisay_num:.2f}')}")
            if muk_alis: mukemmel_alis.append(f"`{esc_sym}` \\({esc_borsa}\\)")
            if alis_say: alis_sayim.append(f"`{esc_sym}` \\({esc_borsa}\\)")
            if muk_satis: mukemmel_satis.append(f"`{esc_sym}` \\({esc_borsa}\\)")
            if satis_say: satis_sayim.append(f"`{esc_sym}` \\({esc_borsa}\\)")
        # Çıktı oluşturma
        response_parts = []
        def add_section(title, items):
            if items: response_parts.append(f"{title}\n" + "\n".join(items))
        add_section("*📊 GÜÇLÜ EŞLEŞEN SİNYALLER:*", guclu_eslesen)
        add_section("*🔴 KAIRI ≤ \\-30:*", kairi_neg30)
        add_section("*🟠 KAIRI ≤ \\-20 \\(ama > \\-30\\):*", kairi_neg20)
        add_section("*🟣 Matisay < \\-25:*", matisay_neg25)
        add_section("*🟢 Mükemmel Alış:*", mukemmel_alis)
        add_section("*📈 Alış Sayımı Tamamlananlar:*", alis_sayim)
        add_section("*🔵 Mükemmel Satış:*", mukemmel_satis)
        add_section("*📉 Satış Sayımı Tamamlananlar:*", satis_sayim)
        if not response_parts: return f"ℹ️ `{escape_markdown_v2(target_borsa.upper() if target_borsa else 'Tüm Borsalar')}` için özetlenecek özel sinyal yok\\."
        return "\n\n".join(response_parts)

def generate_analiz_response(tickers):
    """analiz.json'dan veri çeker, formatlar ve sıralar."""
    # (Kod aynı)
    with analiz_lock:
        if not analiz_data: return f"⚠️ Genel Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_FILE))}`) yüklenemedi\\."
        results, not_found = [], []
        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper(); data = analiz_data.get(ticker)
            if data:
                try: puan_val = float(data.get("puan", -math.inf))
                except (ValueError, TypeError): puan_val = -math.inf
                results.append({"ticker": ticker, "puan": puan_val, "data": data})
            else: not_found.append(ticker)
        results.sort(key=lambda x: x["puan"], reverse=True)
        response_lines = []
        for result in results:
            data, ticker = result["data"], result["ticker"]
            symbol, puan_str = escape_markdown_v2(ticker), escape_markdown_v2(data.get("puan", "N/A"))
            yorum = escape_markdown_v2(data.get("yorum", "_Yorum yok_"))
            detaylar_list = data.get("detaylar", [])
            formatted_detaylar = "\n".join([escape_markdown_v2(d) for d in detaylar_list]) if detaylar_list else "_Detay yok\\._"
            response_lines.append(f"📊 *{symbol}* Analiz Sonuçları \\(Puan: {puan_str}\\):\n{formatted_detaylar}\n\n{yorum}")
        for nf_ticker in not_found: response_lines.append(f"❌ `{escape_markdown_v2(nf_ticker)}` analizi bulunamadı\\.")
        return "\n\n---\n\n".join(response_lines)

def generate_bist_analiz_response(tickers):
    """analiz_sonuclari.json'dan veri çeker, formatlar."""
    # (Kod aynı)
    with bist_analiz_lock:
        if not bist_analiz_data: return f"⚠️ Detaylı BIST Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_SONUCLARI_FILE))}`) yüklenemedi\\."
        response_lines = []
        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper(); data = bist_analiz_data.get(ticker)
            if data:
                symbol, score_str = escape_markdown_v2(ticker), escape_markdown_v2(data.get("score", "N/A"))
                classification = escape_markdown_v2(data.get("classification", "_Belirtilmemiş_"))
                comments = data.get("comments", [])
                formatted_comments = "\n".join([f"\\- {escape_markdown_v2(c)}" for c in comments if isinstance(c, str)]) if comments else "_Yorum yok\\._"
                response_lines.append(f"📊 *{symbol}* Detaylı Analiz:\n\n📈 *Puan:* {score_str}\n🏅 *Sınıflandırma:* {classification}\n\n📝 *Öne Çıkanlar:*\n{formatted_comments}")
            else: response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için detaylı BIST analizi bulunamadı\\.")
        return "\n\n---\n\n".join(response_lines)

# --- Flask Endpointleri ---
# (Bu kısımlar önceki versiyonla aynı, değişiklik yok)

@app.route("/", methods=["GET"])
def home():
    signal_counts = {b: len(s) for b, s in signals_data.items()}
    return f"Bot Aktif! Sinyaller: {escape_markdown_v2(str(signal_counts))}", 200

@app.route("/signal", methods=["POST"])
def receive_signal():
    signal_text = request.data.decode("utf-8")
    print(f"--- Gelen Sinyal Raw ---\n{signal_text}\n------------------------")
    if not signal_text.strip(): print("⚠️ Boş sinyal verisi."); return "Boş veri", 400
    processed_count, new_signal_details = 0, []
    for line in signal_text.strip().split('\n'):
        if not line.strip(): continue
        parsed_data = parse_signal_line(line)
        if parsed_data:
            borsa, symbol, signal_type, timestamp, source = parsed_data["borsa"].lower(), parsed_data["symbol"], parsed_data["type"], parsed_data["time"], parsed_data["source"]
            with signals_lock: signals_data.setdefault(borsa, []).append(parsed_data); last_signal_time[borsa] = timestamp
            icon = "🟢" if signal_type == "BUY" else ("🔴" if signal_type == "SELL" else "ℹ️")
            new_signal_details.append(f"{icon} *{escape_markdown_v2(borsa.upper())}* \\- `{escape_markdown_v2(symbol)}` *{escape_markdown_v2(signal_type)}* _(Kaynak: {escape_markdown_v2(source)})_ \\({escape_markdown_v2(timestamp)}\\)")
            processed_count += 1; print(f"✅ Sinyal işlendi: {parsed_data}")
        else: print(f"⚠️ Sinyal ayrıştırılamadı: {line}")
    if processed_count > 0:
        save_signals()
        if new_signal_details: send_telegram_message("🚨 *Yeni Sinyal(ler) Alındı:*\n\n" + "\n".join(new_signal_details))
        return f"{processed_count} sinyal işlendi.", 200
    else: send_telegram_message(f"⚠️ Geçersiz formatta sinyal:\n```\n{escape_markdown_v2(signal_text)}\n```"); return "Geçerli sinyal yok.", 400

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    webhook_start_time = time.time()
    try:
        update = request.json
        if not update: print("Boş JSON."); return "ok", 200
        message = update.get("message") or update.get("edited_message")
        if not message: update_type = next((k for k in update if k != 'update_id'), '?'); print(f"Desteklenmeyen '{update_type}'."); return "ok", 200
        text, chat_info, user_info = message.get("text", "").strip(), message.get("chat"), message.get("from")
        if not chat_info or not user_info: print("❌ Sohbet/kullanıcı eksik."); return "ok", 200
        chat_id, user_id, first_name, username = chat_info.get("id"), user_info.get("id"), user_info.get("first_name", ""), user_info.get("username", "N/A")
        if str(chat_id) != CHAT_ID: print(f"⚠️ Yetkisiz sohbet ID: {chat_id}"); return "ok", 200
        if not text: print("Boş mesaj."); return "ok", 200
        print(f">>> Mesaj (Chat:{chat_id}, User:{first_name}[{username}/{user_id}]): {text}")
        response_message, command_processed = None, False
        # Komut İşleme
        if text.lower().startswith("/ozet"):
            command_processed = True; print(">>> /ozet komutu...")
            parts = text.split(maxsplit=1); keyword = parts[1].lower() if len(parts) > 1 else None
            if keyword == "bist_dly": keyword = "bist"
            allowed = ["bist", "nasdaq", "bats", "binance"]
            if keyword and keyword not in allowed: response_message = f"⚠️ Geçersiz borsa: `{escape_markdown_v2(keyword)}`\\. İzin verilenler: {', '.join(f'`{k}`' for k in allowed)}\\."
            else: response_message = generate_summary(keyword)
        elif text.lower().startswith("/analiz"):
            command_processed = True; print(">>> /analiz komutu...")
            tickers_input = text[len("/analiz"):].strip()
            if not tickers_input: response_message = "Lütfen hisse kodu belirtin\\. Örn: `/analiz GOOGL`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers: response_message = "Geçerli hisse kodu yok\\. Örn: `/analiz GOOGL`"
                else: print(f"Analiz: {tickers}"); response_message = generate_analiz_response(tickers)
        elif text.lower().startswith("/bist_analiz"):
            command_processed = True; print(">>> /bist_analiz komutu...")
            tickers_input = text[len("/bist_analiz"):].strip()
            if not tickers_input: response_message = "Lütfen BIST kodu belirtin\\. Örn: `/bist_analiz EREGL`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers: response_message = "Geçerli BIST kodu yok\\. Örn: `/bist_analiz EREGL`"
                else: print(f"BIST Analiz: {tickers}"); response_message = generate_bist_analiz_response(tickers)
        elif text.lower().startswith("/clear_signals"):
             command_processed = True; print(">>> /clear_signals komutu...")
             if clear_signals(): response_message = "✅ Veriler temizlendi\\."
             else: response_message = "❌ Temizleme hatası\\."
        elif text.lower().startswith("/start") or text.lower().startswith("/help"):
            command_processed = True; print(">>> /start veya /help komutu...")
            response_message = ("👋 *Merhaba\\!* Komutlar:\n\n"
                                "• `/ozet`: Tüm özet\\.\n"
                                "• `/ozet [borsa]`: Belirli borsa \\(`bist`, `nasdaq`\\.\\.\\)\\.\n"
                                "• `/analiz [HİSSE,\\.\\.]`: Temel analiz \\(Örn: `/analiz AAPL`\\)\\.\n"
                                "• `/bist_analiz [HİSSE,\\.\\.]`: Detaylı BIST analizi \\(Örn: `/bist_analiz EREGL`\\)\\.\n"
                                "• `/clear_signals`: Verileri siler \\(Dikkat\\!\\)\\.\n"
                                "• `/help`: Bu yardım mesajı\\.")
        # Yanıt gönder
        if response_message: send_telegram_message(response_message)
        elif not command_processed: print(f"Bilinmeyen komut/metin: {text}")
        processing_time = time.time() - webhook_start_time
        print(f"<<< /telegram endpoint tamamlandı ({processing_time:.3f} saniye)")
        return "ok", 200
    except Exception as e:
        print(f"❌ /telegram endpoint hatası: {e}"); print(traceback.format_exc())
        try:
             if 'chat_id' in locals() and str(chat_id) == CHAT_ID: send_telegram_message("🤖 Kritik hata oluştu\\!")
        except Exception as inner_e: print(f"❌ Hata mesajı gönderilemedi: {inner_e}")
        return "Internal Server Error", 500

@app.route("/clear_signals_endpoint", methods=["POST"])
def clear_signals_endpoint():
    """Manuel temizlik için endpoint."""
    # GÜVENLİK KONTROLÜ EKLE!
    print(">>> /clear_signals_endpoint tetiklendi")
    if clear_signals(): send_telegram_message("🧹 Manuel temizlik yapıldı\\."); return "OK", 200
    else: send_telegram_message("❌ Manuel temizlik hatası\\!"); return "Hata", 500

# --- Uygulama Başlangıcı ---
if __name__ == "__main__":
    print("*"*50 + "\n🚀 Flask Sinyal/Analiz Botu Başlatılıyor...\n" + "*"*50)
    if not BOT_TOKEN or not CHAT_ID: print("❌ BOT_TOKEN veya CHAT_ID eksik!"); exit()
    # Artık Cleanup Time loglanmıyor
    print(f"🔧 Ayarlar: TZ='{TIMEZONE}'")
    print(f"📂 Dosyalar: Sinyal='{SIGNALS_FILE}', Analiz='{ANALIZ_FILE}', BIST='{ANALIZ_SONUCLARI_FILE}'")
    for fp in [SIGNALS_FILE, ANALIZ_FILE, ANALIZ_SONUCLARI_FILE]:
        if fp and not os.path.exists(fp): print(f"ℹ️ {fp} oluşturuluyor..."); save_json_file(fp, {})
        elif fp and os.path.exists(fp) and os.path.getsize(fp) == 0: print(f"ℹ️ {fp} boş, {{}} yazılıyor."); save_json_file(fp, {})
    print("\n--- Veri Yükleme ---"); load_signals(); load_analiz_data(); load_bist_analiz_data(); print("--- Yükleme Tamamlandı ---\n")

    # ----- Arka Plan Temizlik Görevi Başlatma Kodu KALDIRILDI -----
    # try:
    #     threading.Thread(target=clear_signals_daily, name="DailyCleanup", daemon=True).start()
    #     print("✅ Günlük otomatik temizlik görevi başlatıldı.")
    # except Exception as thread_err: print(f"❌ Temizlik thread hatası: {thread_err}")

    port = int(os.getenv("PORT", 5000)); debug = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t"); host = "0.0.0.0"
    print(f"\n🌍 Sunucu: http://{host}:{port} (Debug: {debug})"); print("🚦 Bot hazır.")
    if debug: print("⚠️ DİKKAT: Debug modu aktif!")
    app.run(host=host, port=port, debug=debug)
