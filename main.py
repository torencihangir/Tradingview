# -*- coding: utf-8 -*-
from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime
import pytz
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# DOSYA YOLLARI
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")

# --- Helper Functions ---

def escape_markdown_v2(text):
    """
    Telegram MarkdownV2 için *yalnızca* potansiyel olarak sorunlu metin parçalarını
    (örn. hisse senedi sembolleri, borsa adları, serbest metin sinyalleri, hata mesajları)
    güvenli hale getirmek için kullanılır. TÜM özel karakterleri kaçırır.
    """
    # Telegram'ın rezerv ettiği TÜM karakterleri kaçırır: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([{}])".format(re.escape(escape_chars)), r"\\\1", str(text))

# *** ÖNEMLİ: Bu fonksiyon ARTIK ESCAPE YAPMIYOR ***
def send_telegram_message(message_text):
    """
    Mesajı Telegram'a gönderir, MarkdownV2 kullanır.
    Mesajın ZATEN doğru formatta ve escape edilmiş olması gerekir.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Mesajı 4096 karakterlik parçalara böl
    for i in range(0, len(message_text), 4096):
        chunk = message_text[i:i+4096]
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            r = requests.post(url, json=data, timeout=20)
            r.raise_for_status()
            response_json = r.json()
            if response_json.get("ok"):
                print(f"✅ Mesaj parçası başarıyla gönderildi (Chat ID: {CHAT_ID})")
            else:
                print(f"❌ Telegram API hatası: {response_json.get('description')}")
                print(f"❌ Hatalı Chunk (gönderilen): {chunk[:200]}...") # Gönderilmeye çalışılan chunk'ı logla
        except requests.exceptions.Timeout:
            print(f"❌ Telegram API isteği zaman aşımına uğradı (URL: {url})")
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi: {e}")
            print(f"❌ Gönderilemeyen mesaj parçası (orijinal): {chunk[:200]}...")
        except json.JSONDecodeError:
             print(f"❌ Telegram API'den geçerli JSON yanıtı alınamadı. Yanıt: {r.text}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")
            print(f"❌ Hata detayı (Tip): {type(e)}")


def parse_signal_line(line):
    try: return json.loads(line)
    except json.JSONDecodeError: print(f"⚠️ JSON parse hatası (atlandı): {line.strip()}"); return None

def load_json_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as file: return json.load(file)
    except FileNotFoundError: print(f"Uyarı: '{filepath}' dosyası bulunamadı."); return {}
    except json.JSONDecodeError: print(f"Hata: '{filepath}' dosyası geçerli bir JSON formatında değil."); return {}
    except Exception as e: print(f"Beklenmedik Hata ('{filepath}' okuma): {e}"); return {}

# --- Flask Routes ---

@app.route("/signal", methods=["POST"])
def receive_signal():
    print(f"[{datetime.now()}] >>> /signal endpoint tetiklendi")
    try:
        # ... (Veri alma kısmı aynı) ...
        if request.is_json: data = request.get_json()
        elif request.content_type == 'text/plain':
            raw_text = request.data.decode("utf-8").strip()
            parts = raw_text.split(None, 2); symbol = "Bilinmiyor"; exchange = "Bilinmiyor"; signal_msg = raw_text
            match_exchange = re.match(r"^(.*?)\s+\((.*?)\)\s*-\s*(.*)$", raw_text)
            if match_exchange: symbol, exchange, signal_msg = match_exchange.groups()
            elif len(parts) >= 2: symbol = parts[0]; signal_msg = " ".join(parts[1:])
            elif len(parts) == 1: signal_msg = parts[0]
            data = {"symbol": symbol.strip(), "exchange": exchange.strip(), "signal": signal_msg.strip()}
        else: return "Unsupported Media Type", 415
        # ... (Timestamp ekleme aynı) ...
        data["timestamp_utc"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try: tz_istanbul = pytz.timezone("Europe/Istanbul"); data["timestamp_tr"] = datetime.now(tz_istanbul).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as tz_err: print(f"Yerel zaman alınırken hata: {tz_err}"); data["timestamp_tr"] = "Hata"
        # ... (Dosyaya yazma aynı) ...
        try:
            with open(SIGNALS_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except IOError as e:
             print(f"❌ Sinyal dosyasına yazılamadı ({SIGNALS_FILE}): {e}")
             # Hata mesajını escape et ve gönder
             send_telegram_message(f"⚠️ *UYARI:* Sinyal dosyasına yazılamadı\\! Hata: `{escape_markdown_v2(str(e))}`")

        # --- Mesaj Oluşturma (Düzeltilmiş Escaping) ---
        # Sadece değişken içerikleri escape et
        symbol_esc = escape_markdown_v2(data.get("symbol", "Bilinmiyor"))
        exchange_raw = data.get("exchange", "Bilinmiyor")
        signal_msg_esc = escape_markdown_v2(data.get("signal", "İçerik Yok"))
        timestamp_tr_raw = data.get("timestamp_tr", "N/A") # Zamanı escape etmeye gerek yok (genelde)
        # Zaman içindeki '-' veya '.' sorun çıkarırsa escape edilebilir:
        # timestamp_tr_esc = escape_markdown_v2(timestamp_tr_raw)

        # Borsa adını güzelleştir ve sadece sonucu escape et
        exchange_display = exchange_raw.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        exchange_display_escaped = escape_markdown_v2(exchange_display)

        # Mesajı oluştururken literal karakterleri manuel escape et (\)
        # Örneğin parantezleri: \( ve \)
        message = f"📡 *Yeni Sinyal Geldi*\n\n" \
                  f"🪙 *Sembol:* `{symbol_esc}`\n" \
                  f"🏦 *Borsa:* {exchange_display_escaped}\n" \
                  f"💬 *Sinyal:* _{signal_msg_esc}_\n" \
                  f"⏰ *Zaman \\(TR\\):* {timestamp_tr_raw}" # TR zamanı için parantezler manuel escape edildi

        send_telegram_message(message)
        return "ok", 200
    # ... (Hata yakalama aynı, içindeki escape'ler doğru) ...
    except json.JSONDecodeError as e: print(f"❌ /signal JSON parse hatası: {e}"); print(f"Gelen Ham Veri: {request.data}"); return f"Bad Request: Invalid JSON - {e}", 400
    except Exception as e:
        print(f"❌ /signal endpoint genel hatası: {e}"); print(f"❌ Hata Tipi: {type(e)}")
        try: error_message = f"❌ `/signal` endpointinde kritik hata oluştu\\!\n*Hata:* `{escape_markdown_v2(str(e))}`"; send_telegram_message(error_message)
        except Exception as telegram_err: print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return f"Internal Server Error: {e}", 500


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    # ... (Webhook başlangıcı ve kontroller aynı) ...
    print(f"[{datetime.now()}] >>> /telegram endpoint tetiklendi")
    update = request.json; #...
    message = update.get("message") or update.get("channel_post"); #...
    text = message.get("text", "").strip(); chat_id = message.get("chat", {}).get("id"); #...
    if str(chat_id) != CHAT_ID: return "ok", 200
    if not text: return "ok", 200
    # ... (Loglama aynı) ...
    print(f">>> Mesaj alındı ... '{text}'")

    response_message = None
    try:
        if text.startswith("/ozet"):
            print(">>> /ozet komutu işleniyor...")
            keyword = text[6:].strip().lower() if len(text) > 6 else None
            allowed_keywords = ["bats", "nasdaq", "bist_dly", "binance", "bist"]
            if keyword and keyword not in allowed_keywords:
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords])
                 # keyword'ü escape et, literal '.' manuel escape
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{escape_markdown_v2(keyword)}`\\.\nİzin verilenler: {allowed_str}"
            else:
                # generate_summary içinde escape yapılıyor
                response_message = generate_summary(keyword)

        elif text.startswith("/analiz"):
            print(">>> /analiz komutu işleniyor...")
            tickers_input = text[8:].strip()
            tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
            if not tickers:
                # Literal '.' ve parantezler manuel escape
                response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\\. Örnek: `/analiz AAPL,MSFT,AMD`"
            else:
                # generate_analiz_response içinde escape yapılıyor
                response_message = generate_analiz_response(tickers)

        elif text.startswith("/bist_analiz"):
            print(">>> /bist_analiz komutu işleniyor...")
            tickers_input = text[13:].strip()
            tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
            if not tickers:
                 # Literal '.' ve parantezler manuel escape
                response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\\. Örnek: `/bist_analiz MIATK,THYAO`"
            else:
                # generate_bist_analiz_response içinde escape yapılıyor (düzeltildi)
                response_message = generate_bist_analiz_response(tickers)

        elif text.startswith("/temizle"):
            print(">>> /temizle komutu işleniyor (Manuel)...")
            clear_signals()
            # Dosya yolunu escape et, literal '.' manuel escape
            response_message = f"✅ `{escape_markdown_v2(SIGNALS_FILE)}` dosyası manuel olarak temizlendi\\."

        # ... (Diğer komutlar veya bilinmeyen komut durumu) ...

        if response_message:
            send_telegram_message(response_message) # Direkt gönder
        else:
             print("İşlenecek komut bulunamadı veya yanıt oluşturulmadı.")

    # ... (Hata yakalama aynı, içindeki escape'ler doğru) ...
    except Exception as e:
        print(f"❌ /telegram endpoint komut işleme hatası: {e}"); print(f"❌ Hata Tipi: {type(e)}")
        try: error_text = f"Komut işlenirken bir hata oluştu: `{escape_markdown_v2(str(e))}`"; send_telegram_message(f"⚙️ *HATA* ⚙️\n{error_text}")
        except Exception as telegram_err: print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")

    return "ok", 200


@app.route("/clear_signals", methods=["POST"])
def clear_signals_endpoint():
    print(f"[{datetime.now()}] >>> /clear_signals endpoint tetiklendi (HTTP POST)")
    try:
        clear_signals()
        # Dosya yolunu escape et, literal '.' ve parantezler manuel escape
        send_telegram_message(f"📁 `{escape_markdown_v2(SIGNALS_FILE)}` dosyası HTTP isteği ile temizlendi\\.")
        return f"{SIGNALS_FILE} dosyası temizlendi!", 200
    except Exception as e:
        print(f"❌ Manuel sinyal temizleme hatası (HTTP): {e}")
        # Dosya yolu, hata mesajı escape ediliyor, literal '.' ve parantezler manuel escape
        send_telegram_message(f"❌ `{escape_markdown_v2(SIGNALS_FILE)}` temizlenirken hata oluştu \\(HTTP\\): `{escape_markdown_v2(str(e))}`")
        return str(e), 500

# --- Analiz ve Özet Fonksiyonları ---

def generate_analiz_response(tickers):
    """analiz.json dosyasından veri çekerek basit analiz yanıtı oluşturur."""
    analiz_verileri = load_json_file(ANALIZ_FILE)
    analiz_listesi = []
    if not analiz_verileri:
         # Dosya yolunu escape et, literal parantezler ve '.' manuel escape
         return f"⚠️ Analiz verileri \\(`{escape_markdown_v2(ANALIZ_FILE)}`\\) yüklenemedi veya boş\\."

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        analiz = analiz_verileri.get(ticker_upper)
        ticker_esc = escape_markdown_v2(ticker_upper) # Ticker'ı escape et
        if analiz:
            puan_raw = analiz.get("puan", 0)
            detaylar_list = analiz.get("detaylar", [])
            # Detayları escape et
            detaylar_str = "\n".join([f"\\- {escape_markdown_v2(d)}" for d in detaylar_list]) if detaylar_list else "_Detay bulunamadı_"
            # Yorumu escape et
            yorum = escape_markdown_v2(analiz.get("yorum", "_Yorum bulunamadı_"))
            analiz_listesi.append({
                "ticker": ticker_esc, "puan": puan_raw,
                # Puanı ` içinde gösterdiğimiz için escape etmeye gerek yok
                "puan_str": str(puan_raw),
                "detaylar": detaylar_str, "yorum": yorum
            })
        else:
             # Dosya yolunu escape et, literal parantezler ve '.' manuel escape
            analiz_listesi.append({
                "ticker": ticker_esc, "puan": None, "puan_str": "N/A", "detaylar": None,
                "yorum": f"❌ `{ticker_esc}` için analiz bulunamadı \\(`{escape_markdown_v2(ANALIZ_FILE)}`\\)\\."
            })

    analiz_listesi.sort(key=lambda x: (x["puan"] is not None, x["puan"]), reverse=True)
    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            # Literal parantezleri manuel escape et
            response_lines.append(
                f"📊 *{analiz['ticker']}* Analiz \\(Puan: `{analiz['puan_str']}`\\):\n"
                f"_{analiz['detaylar']}_\n\n" # Detaylar zaten başında \- ile escape edilmişti
                f"*{analiz['yorum']}*"
            )
        else:
            response_lines.append(analiz["yorum"]) # Hata mesajı zaten doğru formatta
    return "\n\n---\n\n".join(response_lines)


def format_number_in_string(text):
    """ Metin içindeki '12345.0' -> '12345' yapar. """
    return re.sub(r'(\d+)\.0(?!\d)', r'\1', text)

# *** generate_bist_analiz_response: Yorumlar escape EDİLMİYOR, literal karakterler manuel escape ***
def generate_bist_analiz_response(tickers):
    """
    analiz_sonuclari.json'dan veri çeker, emoji ekler, .0'ı kaldırır.
    Yorum metinlerini escape ETMEZ, sadece literal özel karakterleri manuel kaçırır.
    """
    all_analiz_data = load_json_file(ANALIZ_SONUCLARI_FILE)
    response_lines = []

    if not all_analiz_data:
         # Dosya yolu escape, literal parantez/nokta manuel escape
         return f"⚠️ Detaylı analiz verileri \\(`{escape_markdown_v2(ANALIZ_SONUCLARI_FILE)}`\\) yüklenemedi veya boş\\."

    emoji_map = {
        "PEG oranı": "🧠", "F/K oranı": "📈", "Net Borç/FAVÖK": "🏦",
        "Net dönem karı artışı": "🔹", "Dönen Varlıklar Artışı": "🔄",
        "Duran Varlıklar Artışı": "🏗️", "Toplam Varlıklar Artışı": "🏛️",
        "Finansal Borç Azalışı": "📉", "Net Borç Azalışı": "✅",
        "Özkaynak Artışı": "💪"
    }
    default_emoji = "🔹"

    # Hangi karakterlerin yorum içinde manuel escape edilmesi gerektiğini tanımla
    # Bunlar: ( ) < > . - = % + ! # _ * ` [ ] ~
    # Not: _ ve * yorum içinde italik/bold istenmiyorsa escape edilmeli.
    # ` code istenmiyorsa escape edilmeli.
    # [ ] link istenmiyorsa escape edilmeli.
    # Şimdilik sadece parantez, nokta, tire, eşittir, yüzde, artı, ünlem, diyez'i escape edelim.
    # Diğerleri ( _ * ` [ ] ~ ) yorumlarda kullanılmıyor gibi görünüyor.
    chars_to_escape_in_comment = r"()<>.-=%+!#"
    def escape_comment_literals(comment_text):
        return re.sub(r"([{}])".format(re.escape(chars_to_escape_in_comment)), r"\\\1", comment_text)

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        analiz_data = all_analiz_data.get(ticker_upper)
        ticker_esc = escape_markdown_v2(ticker_upper) # Sembol her zaman escape edilmeli

        if analiz_data:
            score_raw = analiz_data.get("score", "N/A")
            display_score = str(score_raw) # Escape etme, ` içinde
            try:
                score_float = float(score_raw); display_score = str(int(score_float)) if score_float.is_integer() else str(score_float)
            except (ValueError, TypeError): pass

            classification_raw = analiz_data.get("classification", "Belirtilmemiş")
            classification_esc = escape_markdown_v2(classification_raw) # Sınıflandırma metnini escape et
            classification_emoji = "🏆"
            comments_raw = analiz_data.get("comments", [])

            # Yorumları formatla (emoji + sayı formatlama + LİTERAL KAÇIRMA)
            formatted_comments_list = []
            if comments_raw:
                for comment in comments_raw:
                    if not comment: continue
                    prefix_emoji = default_emoji
                    for key, emoji in emoji_map.items():
                        if comment.strip().startswith(key): prefix_emoji = emoji; break

                    formatted_num_comment = format_number_in_string(comment)
                    # Yorum içindeki literal ( ) . - = % + ! # karakterlerini kaçır
                    final_comment_text = escape_comment_literals(formatted_num_comment)
                    formatted_comments_list.append(f"{prefix_emoji} {final_comment_text}")

                formatted_comments = "\n".join(formatted_comments_list)
            else:
                formatted_comments = "_Yorum bulunamadı_" # İtalik için _ korunmalı

            # Mesajı oluştur
            response_lines.append(
                f"📊 *{ticker_esc}* Detaylı Analiz:\n\n"
                f"📈 *Puan:* `{display_score}`\n"
                f"{classification_emoji} *Sınıflandırma:* {classification_esc}\n\n"
                f"📝 *Öne Çıkanlar:*\n{formatted_comments}" # Yorumlar artık manuel escape edilmiş
            )
        else:
             # Hata mesajı zaten doğru formatta (önceki adımdan)
            response_lines.append(f"❌ `{ticker_esc}` için detaylı analiz bulunamadı \\(`{escape_markdown_v2(ANALIZ_SONUCLARI_FILE)}`\\)\\.")

    return "\n\n---\n\n".join(response_lines)


def generate_summary(keyword=None):
    """signals.json dosyasını okuyarak sinyal özeti oluşturur."""
    if not os.path.exists(SIGNALS_FILE): return "📊 Henüz hiç sinyal kaydedilmedi\\."
    lines = []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f: lines = f.readlines()
    except IOError as e:
        # Hata mesajını/yolunu escape et, literal parantez/nokta manuel escape
        return f"⚠️ Sinyal dosyası \\(`{escape_markdown_v2(SIGNALS_FILE)}`\\) okunurken bir hata oluştu: `{escape_markdown_v2(str(e))}`"
    if not lines: return "📊 Sinyal dosyasında kayıtlı veri bulunamadı\\."

    summary = {
        "güçlü": set(), "kairi_-30": set(), "kairi_-20": set(),
        "matisay_-25": set(), "mükemmel_alış": set(), "alış_sayımı": set(),
        "mükemmel_satış": set(), "satış_sayımı": set(),
    }
    parsed_signals = [parse_signal_line(line) for line in lines if line.strip()]
    parsed_signals = [s for s in parsed_signals if s]

    keyword_map = {"bist": "bist_dly", "nasdaq": "bats", "binance": "binance"}
    active_filter = None
    if keyword:
        keyword_lower = keyword.lower()
        active_filter = keyword_map.get(keyword_lower, keyword_lower)
        filtered_signals = [s for s in parsed_signals if active_filter in s.get("exchange", "").lower()]
        if not filtered_signals:
             # keyword escape, literal nokta manuel escape
             return f"📊 `{escape_markdown_v2(keyword)}` filtresi için sinyal bulunamadı\\."
        parsed_signals = filtered_signals

    processed_symbols_for_strong = set()

    for signal_data in parsed_signals:
        symbol = signal_data.get("symbol", "Bilinmiyor")
        exchange = signal_data.get("exchange", "Bilinmiyor")
        signal_text = signal_data.get("signal", "")
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        base_key = f"{symbol} ({exchange_display})" # Escape edilmemiş anahtar (set için)
        # Görüntülenecek anahtar: sembol ve borsa escape, parantezler manuel escape
        display_key = f"{escape_markdown_v2(symbol)} \\({escape_markdown_v2(exchange_display)}\\)"
        signal_lower = signal_text.lower()

        def format_value(val_type, val):
            # Değer ` içinde olduğu için sadece val_type escape edilmeli (gerekirse)
            # Ama KAIRI ve Matisay sabit, escape gerektirmez. `-` işareti ` içinde korunur.
            return f"{val_type} `{val}`"

        # KAIRI / Matisay işlemleri...
        try: # Hata yakalamayı genişlet
            if "kairi" in signal_lower:
                kairi_match = re.search(r"kairi\s*([-+]?\d*\.?\d+)", signal_lower)
                if kairi_match:
                    kairi_value = round(float(kairi_match.group(1)), 2)
                    kairi_str = format_value("KAIRI", kairi_value)
                    kairi_entry = f"{display_key}: {kairi_str}" # display_key kullan
                    if kairi_value <= -30: summary["kairi_-30"].add(kairi_entry)
                    elif kairi_value <= -20: summary["kairi_-20"].add(kairi_entry)
                    if base_key not in processed_symbols_for_strong:
                        for other in parsed_signals:
                            if other.get("symbol") == symbol and other.get("exchange") == exchange and re.search(r"(mükemmel alış|alış sayımı)", other.get("signal", "").lower()):
                                # Literal '&' ve '-' manuel escape
                                strong_entry = f"✅ {display_key} \\- {kairi_str} \\& Alış Sinyali"
                                summary["güçlü"].add(strong_entry); processed_symbols_for_strong.add(base_key); break
            elif "matisay" in signal_lower:
                matisay_match = re.search(r"matisay\s*([-+]?\d*\.?\d+)", signal_lower)
                if matisay_match:
                    matisay_value = round(float(matisay_match.group(1)), 2)
                    if matisay_value < -25:
                        matisay_str = format_value("Matisay", matisay_value)
                        matisay_entry = f"{display_key}: {matisay_str}" # display_key kullan
                        summary["matisay_-25"].add(matisay_entry)
            elif re.search(r"mükemmel alış", signal_lower):
                 summary["mükemmel_alış"].add(display_key) # display_key kullan
                 if base_key not in processed_symbols_for_strong:
                     for other in parsed_signals:
                         if other.get("symbol") == symbol and other.get("exchange") == exchange and "kairi" in other.get("signal", "").lower():
                             kairi_match_rev = re.search(r"kairi\s*([-+]?\d*\.?\d+)", other.get("signal", "").lower())
                             if kairi_match_rev:
                                kairi_val_rev = round(float(kairi_match_rev.group(1)), 2)
                                if kairi_val_rev <= -20:
                                    kairi_rev_str = format_value("KAIRI", kairi_val_rev)
                                    # Literal '&' ve '-' manuel escape
                                    strong_entry = f"✅ {display_key} \\- Alış Sinyali \\& {kairi_rev_str}"
                                    summary["güçlü"].add(strong_entry); processed_symbols_for_strong.add(base_key); break
            elif re.search(r"alış sayımı", signal_lower):
                summary["alış_sayımı"].add(display_key) # display_key kullan
                if base_key not in processed_symbols_for_strong:
                     for other in parsed_signals:
                         if other.get("symbol") == symbol and other.get("exchange") == exchange and "kairi" in other.get("signal", "").lower():
                             kairi_match_rev = re.search(r"kairi\s*([-+]?\d*\.?\d+)", other.get("signal", "").lower())
                             if kairi_match_rev:
                                kairi_val_rev = round(float(kairi_match_rev.group(1)), 2)
                                if kairi_val_rev <= -20:
                                    kairi_rev_str = format_value("KAIRI", kairi_val_rev)
                                    # Literal '&' ve '-' manuel escape
                                    strong_entry = f"✅ {display_key} \\- Alış Sayımı \\& {kairi_rev_str}"
                                    summary["güçlü"].add(strong_entry); processed_symbols_for_strong.add(base_key); break
            elif re.search(r"mükemmel satış", signal_lower): summary["mükemmel_satış"].add(display_key) # display_key kullan
            elif re.search(r"satış sayımı", signal_lower): summary["satış_sayımı"].add(display_key) # display_key kullan
        except (ValueError, TypeError) as parse_err:
            print(f"Sinyal özeti parse hatası ({base_key}): {parse_err} - Sinyal: {signal_text[:50]}...")
        except Exception as e:
            print(f"Sinyal özeti genel hata ({base_key}): {e}")


    # Özeti oluştur (Manuel escaping ile)
    msg_parts = []
    # keyword escape, literal parantez/nokta manuel escape
    filter_title = f" \\(`{escape_markdown_v2(keyword)}` Filtresi\\)" if keyword else ""
    msg_parts.append(f"📊 *Sinyal Özeti*{filter_title}")

    # Başlıklardaki özel karakterleri manuel escape et
    category_map = {
        "güçlü": "✅ *GÜÇLÜ EŞLEŞENLER \\(Alış \\& KAIRI ≤ \\-20\\)*",
        "kairi_-30": "🔴 *KAIRI ≤ \\-30*",
        "kairi_-20": "🟠 *\\-30 < KAIRI ≤ \\-20*",
        "matisay_-25": "🟣 *Matisay < \\-25*",
        "mükemmel_alış": "🟢 *Mükemmel Alış*",
        "alış_sayımı": "📈 *Alış Sayımı Tamamlananlar*",
        "mükemmel_satış": "🔵 *Mükemmel Satış*",
        "satış_sayımı": "📉 *Satış Sayımı Tamamlananlar*"
    }
    has_content = False
    for key, title in category_map.items():
        if summary[key]:
            has_content = True
            # Liste elemanları zaten display_key ile escape edildi. Baştaki '-' escape edilmeli.
            sorted_items = sorted(list(summary[key]))
            msg_parts.append(f"{title}:\n" + "\n".join(f"\\- {item}" for item in sorted_items))

    if not has_content:
        filter_text = f" `{escape_markdown_v2(keyword)}` filtresi ile" if keyword else ""
        # literal nokta manuel escape
        return f"📊 Gösterilecek uygun sinyal bulunamadı{filter_text}\\."

    final_summary = "\n\n".join(msg_parts)
    #print("Oluşturulan Özet Başlangıcı:", final_summary[:300] + "...") # Loglama için geçici kapat
    return final_summary


# --- Arka Plan Görevleri ---

def clear_signals():
    try:
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f: f.write("")
            print(f"✅ {SIGNALS_FILE} dosyası başarıyla temizlendi!")
        else: print(f"ℹ️ {SIGNALS_FILE} dosyası bulunamadı, temizleme işlemi atlandı.")
    except IOError as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken G/Ç hatası: {e}")
        # Hata mesajı/yol escape, literal parantez/nokta manuel escape
        send_telegram_message(f"⚠️ *Otomatik Temizlik Hatası:* `{escape_markdown_v2(SIGNALS_FILE)}` temizlenemedi \\- G/Ç Hatası: `{escape_markdown_v2(str(e))}`")
    except Exception as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken beklenmedik hata: {e}")
        # Hata mesajı/yol escape, literal parantez/nokta manuel escape
        send_telegram_message(f"⚠️ *Otomatik Temizlik Hatası \\(Genel\\):* `{escape_markdown_v2(SIGNALS_FILE)}` temizlenemedi \\- Hata: `{escape_markdown_v2(str(e))}`")

def clear_signals_daily():
    print("🕒 Günlük sinyal temizleme görevi başlatılıyor...")
    already_cleared_today = False; target_hour, target_minute = 23, 59; check_interval_seconds = 30
    while True:
        try:
            tz_istanbul = pytz.timezone("Europe/Istanbul"); now = datetime.now(tz_istanbul)
            if now.hour == target_hour and now.minute == target_minute:
                if not already_cleared_today:
                    print(f"⏰ Zamanı geldi ({now.strftime('%Y-%m-%d %H:%M:%S %Z')}), {SIGNALS_FILE} temizleniyor...")
                    clear_signals()
                    try:
                         # Zaman ve dosya yolu escape, literal parantez/nokta manuel escape
                         timestamp_str = escape_markdown_v2(now.strftime('%Y-%m-%d %H:%M')) # İçindeki '-' escape edilecek
                         send_telegram_message(f"🧹 Günlük otomatik temizlik yapıldı \\({timestamp_str}\\)\\. `{escape_markdown_v2(SIGNALS_FILE)}` sıfırlandı\\.")
                    except Exception as tel_err: print(f"❌ Temizlik bildirimi gönderilemedi: {tel_err}")
                    already_cleared_today = True; time.sleep(check_interval_seconds * 2 + 5); continue
            elif already_cleared_today: already_cleared_today = False
            time.sleep(check_interval_seconds)
        except pytz.UnknownTimeZoneError: print("❌ Hata: 'Europe/Istanbul' saat dilimi bulunamadı."); time.sleep(check_interval_seconds)
        except Exception as e:
            print(f"❌ clear_signals_daily döngüsünde hata: {e}"); print(f"❌ Hata Tipi: {type(e)}")
            try:
                 # Hata mesajı escape, literal parantez/nokta manuel escape
                send_telegram_message(f"⚠️ *Kritik Hata:* Günlük temizlik görevinde sorun oluştu\\! Hata: `{escape_markdown_v2(str(e))}`")
            except Exception as tel_err: print(f"❌ Kritik hata bildirimi gönderilemedi: {tel_err}")
            time.sleep(60)

# --- Uygulama Başlatma ---
if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID: print("❌ HATA: BOT_TOKEN veya CHAT_ID ayarlanmamış!"); exit(1)
    print("-" * 30); print("🚀 Flask Uygulaması Başlatılıyor..."); #... (Diğer printler aynı) ...
    print(f"🔧 Bot Token: ...{BOT_TOKEN[-6:]}")
    print(f"🔧 Chat ID: {CHAT_ID}")
    print(f"🔧 Sinyal Dosyası: {SIGNALS_FILE}")
    print(f"🔧 Analiz Dosyası (Basit): {ANALIZ_FILE}")
    print(f"🔧 Analiz Dosyası (Detaylı): {ANALIZ_SONUCLARI_FILE}")
    print("-" * 30)
    daily_clear_thread = threading.Thread(target=clear_signals_daily, daemon=True); daily_clear_thread.start()
    try: app.run(host="0.0.0.0", port=5000, debug=False)
    except Exception as run_err: print(f"❌ Flask uygulaması başlatılırken hata: {run_err}")
