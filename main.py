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
import logging # Logging zaten vardı, kullanmaya devam edelim

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# Logging yapılandırması (Mevcut haliyle kalıyor)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# .env dosyasından değerleri al (Mevcut haliyle kalıyor)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = "C:\\Users\\Administrator\\Desktop\\tradingview-telegram-bot\\signals.json"
NASDAQ_ANALIZ_FILE = "analiz.json"
# --- YENİ --- BIST analiz dosyasının adını ekleyelim
BIST_ANALYSIS_FILE = "analiz_sonuclari.json"

# escape_markdown_v2 fonksiyonu (Mevcut haliyle kalıyor)
def escape_markdown_v2(text):
    """Telegram MarkdownV2 için özel karakterleri (nokta ve ünlem dahil) kaçırır."""
    if text is None:
        return ""
    # Nokta '.' ve Ünlem '!' karakterlerini de escape listesine ekleyelim.
    escape_chars = r'_*[]()~`>#+-=|{}.!' # <- '.' ve '!' eklendi
    text_str = str(text)
    # Regex kullanarak belirtilen karakterleri bul ve önüne \ ekle
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text_str)

# send_telegram_message fonksiyonu (Mevcut haliyle kalıyor - mesaj bölme dahil)
def send_telegram_message(chat_id_to_send, message):
    """Belirtilen chat_id'ye mesaj gönderir."""
    if not chat_id_to_send:
        logging.error("Mesaj göndermek için chat_id belirtilmedi.")
        return

    def split_message(msg, max_len=4096):
        chunks = []
        current_chunk = ""
        if msg is None: # Eğer mesaj None ise boş liste döndür
             return chunks
        for line in str(msg).split('\n'): # Mesajın str olduğundan emin ol
            if len(current_chunk) + len(line) + 1 > max_len or len(line) > max_len:
                if current_chunk:
                    chunks.append(current_chunk)
                if len(line) > max_len:
                     for i in range(0, len(line), max_len):
                         chunks.append(line[i:i+max_len])
                     current_chunk = "" # Satır bölündüğü için chunk'ı sıfırla
                else:
                    current_chunk = line
            else:
                if current_chunk:
                    current_chunk += "\n" + line
                else:
                    current_chunk = line
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    # Escape işlemini yapmadan önce loglama (debug için yararlı olabilir)
    # logging.info(f"Original message to {chat_id_to_send}:\n{message}")

    escaped_message = escape_markdown_v2(message)
    message_chunks = split_message(escaped_message, 4090)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i, chunk in enumerate(message_chunks):
        # Gönderilen chunk'ı loglama (debug için yararlı olabilir)
        # logging.info(f"Sending chunk {i+1}/{len(message_chunks)} to {chat_id_to_send}:\n{chunk}")
        data = {
            "chat_id": chat_id_to_send,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            r = requests.post(url, json=data, timeout=10)
            # Sadece hata durumunda loglama yapalım
            if r.status_code != 200:
                 logging.error(f"Telegram API Hata Yanıtı (Chunk {i+1}): {r.status_code} - {r.text}")
            r.raise_for_status()
            logging.info(f"Telegram yanıtı ({chat_id_to_send}): {r.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Telegram'a mesaj gönderilemedi ({chat_id_to_send}): {e}\nProblematic Chunk:\n{chunk[:200]}...") # Hatalı chunk'ın başını logla
            # Hata durumunda diğer chunk'ları göndermeyi durdurabiliriz.
            break
        except Exception as e:
             logging.error(f"Mesaj gönderirken beklenmedik hata ({chat_id_to_send}): {e}\nProblematic Chunk:\n{chunk[:200]}...", exc_info=True)
             break
        time.sleep(0.3) # Rate limit için küçük bekleme


# /signal endpoint (Mevcut haliyle kalıyor)
@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        logging.info(">>> /signal endpoint tetiklendi")
        if request.is_json:
            data = request.get_json()
        else:
            # TradingView'dan gelen düz metin alert'lerini parse etme (Mevcut mantık)
            raw = request.data.decode("utf-8")
            match = re.match(r"(.*?) \((.*?)\) - (.*)", raw)
            if match:
                symbol, exchange, signal = match.groups()
                data = {
                    "symbol": symbol.strip(),
                    "exchange": exchange.strip(),
                    "signal": signal.strip()
                }
            else: # Eğer parse edilemezse
                data = {"symbol": "Bilinmiyor", "exchange": "Bilinmiyor", "signal": raw.strip()}
                logging.warning(f"Parse edilemeyen sinyal: {raw.strip()}")

        # Dinamik yerleştirme (Mevcut mantık)
        signal = data.get("signal", "")
        signal = re.sub(r"{{plot\(\"matisay trend direction\"\)}}", "-25", signal)
        data["signal"] = signal

        # Zaman damgası ekle (Mevcut mantık)
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            logging.error(f"Sinyal dosyasına yazılamadı ({SIGNALS_FILE}): {e}")
            # Opsiyonel: Hata durumunda sinyali yine de göndermeye çalışabiliriz

        symbol = data.get("symbol", "Bilinmiyor")
        exchange = data.get("exchange", "Bilinmiyor")
        signal = data.get("signal", "Bilinmiyor")

        # Mesaj gönderimi (Mevcut mantık - Global CHAT_ID kullanıyor)
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ").upper()
        # Yıldızları ve alt çizgileri escape etmeye gerek yok, mesaj formatlaması MarkdownV2 ile uyumlu olmalı
        message_text = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange_display})\n📍 _{signal}_"
        send_telegram_message(CHAT_ID, message_text)

        return "ok", 200
    except Exception as e:
        logging.error(f"/signal hatası: {e}", exc_info=True)
        return str(e), 500

# --- BIST ANALİZ İÇİN GEREKLİ YENİ FONKSİYONLAR ---

def load_bist_analysis_data():
    """analiz_sonuclari.json dosyasını yükler."""
    if not os.path.exists(BIST_ANALYSIS_FILE):
        logging.error(f"BIST Analiz dosyası bulunamadı: {BIST_ANALYSIS_FILE}")
        return None
    try:
        with open(BIST_ANALYSIS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logging.info(f"{BIST_ANALYSIS_FILE} başarıyla yüklendi.")
            return data
    except json.JSONDecodeError:
        logging.error(f"Hata: {BIST_ANALYSIS_FILE} dosyasındaki JSON formatı bozuk.")
        return None
    except Exception as e:
        logging.error(f"{BIST_ANALYSIS_FILE} yüklenirken hata: {e}", exc_info=True)
        return None

def format_bist_stock_info(stock_data):
    """Tek bir BIST hissesinin verisini Telegram mesajı için formatlar."""
    if not stock_data or not isinstance(stock_data, dict):
        return "Hisse senedi verisi bulunamadı veya formatı geçersiz\\." # Escape edelim

    # Verileri al, None ise 'N/A' kullan
    symbol = stock_data.get('symbol', 'N/A')
    score = stock_data.get('score', 'N/A')
    classification = stock_data.get('classification', 'N/A')
    comments = stock_data.get('comments', [])

    # Mesajı oluştur (escape işlemi send_telegram_message içinde)
    message = f"📊 *BIST Analiz: {symbol}*\n\n"
    message += f"🔢 *Skor:* `{score}`\n"
    message += f"⭐ *Sınıflandırma:* _{classification}_\n\n"
    message += "📝 *Önemli Yorumlar:*\n"

    if comments and isinstance(comments, list):
        comment_limit = 7 # Daha fazla yorum varsa belirt
        for i, comment in enumerate(comments):
            if i >= comment_limit:
                message += f"  \\.\\.\\. _({len(comments) - comment_limit} yorum daha var)_\n"
                break

            comment_text = str(comment) # String olduğundan emin ol
            # Basitçe yorumu madde işaretiyle ekleyelim
            # Daha karmaşık ayrıştırma (Değer: vs.) yerine düz listeleme yapalım şimdilik
            # Bu, escape sorunlarını azaltabilir.
            message += f"  • {comment_text.strip()}\n"
    else:
        message += "  _Yorum bulunamadı\\._\n"

    # Genel Bakış
    message += f"\n💡 *Genel Bakış:* `{symbol}` hissesi _{classification}_ sınıfında ve `{score}` puan almış\\."

    return message

def generate_bist_ozet_response():
    """En yüksek skorlu BIST hisselerinin bir özetini oluşturur."""
    logging.info("BIST özeti oluşturuluyor...")
    bist_data = load_bist_analysis_data()

    if bist_data is None:
        return f"BIST analiz verileri ({BIST_ANALYSIS_FILE}) yüklenirken bir sorun oluştu\\."
    if not bist_data or not isinstance(bist_data, dict):
        return "BIST için analiz verisi bulunamadı veya formatı geçersiz\\."

    valid_stocks = []
    for symbol, data in bist_data.items():
        # Verinin dict olduğunu ve score'un sayısal olduğunu kontrol et
        if isinstance(data, dict) and isinstance(data.get('score'), (int, float)):
            valid_stocks.append(data)
        else:
            logging.warning(f"BIST özeti için geçersiz veri atlanıyor: {symbol} - Score: {data.get('score', 'Yok')}")

    if not valid_stocks:
        return "Sıralanacak geçerli BIST hisse verisi bulunamadı\\."

    try:
        # Skora göre sırala
        sorted_stocks = sorted(valid_stocks, key=lambda x: x['score'], reverse=True)

        top_n = 15 # Gösterilecek hisse sayısı
        message = f"🏆 *BIST Analiz Özeti (En Yüksek Skorlu {min(top_n, len(sorted_stocks))} Hisse):*\n\n"
        for stock in sorted_stocks[:top_n]:
            symbol = stock.get('symbol', 'N/A')
            score = stock.get('score', 'N/A')
            classification = stock.get('classification', 'N/A')
            # /bist_analiz komutuna yönlendirme
            message += f"• `{symbol}`: Skor `{score}` (_{classification}_) \\- /bist\\_analiz {symbol}\n" # _ escape edildi

        # Excellent sınıfındakiler
        excellent_stocks = [s for s in sorted_stocks if s.get('classification') == 'Excellent']
        if excellent_stocks:
            message += "\n⭐ *'Excellent' Sınıflandırılanlar:*\n"
            ex_symbols = [f"`{s.get('symbol', 'N/A')}`" for s in excellent_stocks]
            message += ", ".join(ex_symbols)
            if len(ex_symbols) > 20: # Çok fazlaysa sonuna ... ekle
                message += "\\.\\.\\."

        return message

    except Exception as e:
        logging.error(f"BIST özeti oluşturulurken hata: {e}", exc_info=True)
        return "BIST özeti oluşturulurken bir hata meydana geldi\\."


# --- NASDAQ ANALİZ FONKSİYONLARI (Mevcut haliyle kalıyor) ---

def load_nasdaq_analiz_json(): # Fonksiyon adını değiştirdim (önceki kodda load_analiz_json idi)
    """analiz.json dosyasını yükler (NASDAQ için)."""
    if not os.path.exists(NASDAQ_ANALIZ_FILE):
        logging.error(f"NASDAQ Analiz dosyası bulunamadı: {NASDAQ_ANALIZ_FILE}")
        return {} # Boş dict döndür
    try:
        with open(NASDAQ_ANALIZ_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        logging.error(f"Hata: {NASDAQ_ANALIZ_FILE} JSON formatı bozuk.")
        return {}
    except Exception as e:
        logging.error(f"{NASDAQ_ANALIZ_FILE} yüklenirken hata: {e}", exc_info=True)
        return {}

def generate_nasdaq_analiz_response(tickers): # Fonksiyon adını değiştirdim (önceki kodda generate_analiz_response idi)
    """Belirtilen NASDAQ hisseleri için analiz yanıtı oluşturur."""
    analiz_verileri = load_nasdaq_analiz_json()
    if not analiz_verileri:
         return f"NASDAQ analiz verileri ({NASDAQ_ANALIZ_FILE}) yüklenemedi veya boş\\."

    analiz_listesi = []
    for ticker in tickers:
        ticker_upper = ticker.upper()
        analiz = analiz_verileri.get(ticker_upper)
        if analiz and isinstance(analiz, dict):
            puan = analiz.get("puan", 0)
            detaylar_list = analiz.get("detaylar", [])
            # Detayları basit liste olarak formatla
            detaylar = "\n".join([f"• {str(d)}" for d in detaylar_list]) if detaylar_list else "_Detay bulunamadı\\._"
            yorum = analiz.get("yorum", "_Yorum bulunamadı\\._")
            analiz_listesi.append({
                "ticker": ticker_upper,
                "puan": puan,
                "detaylar": detaylar,
                "yorum": yorum
            })
        else:
            analiz_listesi.append({
                "ticker": ticker_upper,
                "puan": None,
                "detaylar": None,
                "yorum": f"❌ `{ticker_upper}` için NASDAQ analizi bulunamadı\\."
            })

    # Puanlara göre sıralama
    analiz_listesi.sort(key=lambda x: (x["puan"] is not None, x.get("puan", -1)), reverse=True)

    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            response_lines.append(
                f"📊 *NASDAQ Analiz: {analiz['ticker']}* (Puan: `{analiz['puan']}`)\n\n{analiz['detaylar']}\n\n💡 *Yorum:*\n_{analiz['yorum']}_"
            )
        else:
            response_lines.append(analiz["yorum"])

    return "\n\n---\n\n".join(response_lines) # Ayırıcı ekle

# --- TELEGRAM WEBHOOK (BIST Komutları Eklendi) ---

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    logging.info(">>> /telegram endpoint tetiklendi")
    update = request.json
    if not update:
        logging.warning("Boş JSON verisi alındı.")
        return "nok", 200

    message = update.get("message") or update.get("edited_message")
    if not message:
        logging.info("Mesaj içeriği bulunamadı.")
        return "ok", 200

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    user_info = message.get("from", {})
    username = user_info.get("username", "N/A")
    user_id = user_info.get("id", "N/A")

    logging.info(f"Gelen mesaj: ChatID={chat_id}, User={username}({user_id}), Text='{text}'")

    if not chat_id:
        logging.error("Chat ID alınamadı.")
        return "nok", 200

    # Mevcut Komutlar
    if text.startswith("/ozet"):
        logging.info(f">>> /ozet komutu alındı: {text}")
        keyword = text[len("/ozet"):].strip().lower()
        allowed_keywords = ["bats", "nasdaq", "bist", "bist_dly", "binance"]
        if keyword and keyword not in allowed_keywords:
             summary_text = f"Geçersiz anahtar kelime: `{keyword}`\\. Lütfen `bats`, `nasdaq`, `bist` veya `binance` kullanın ya da boş bırakın\\."
        else:
            summary_text = generate_summary(keyword if keyword else None) # None gönder eğer keyword boşsa
        send_telegram_message(chat_id, summary_text)

    elif text.startswith("/analiz"): # NASDAQ Analizi (Mevcut haliyle kalıyor)
        logging.info(f">>> /analiz (NASDAQ) komutu alındı: {text}")
        tickers_input = text[len("/analiz"):].strip()
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
        if not tickers:
            send_telegram_message(chat_id, "Lütfen bir veya daha fazla NASDAQ hisse kodu belirtin\\. Örnek: `/analiz AAPL,MSFT`")
        else:
            # generate_analiz_response yerine generate_nasdaq_analiz_response çağırılmalı
            response = generate_nasdaq_analiz_response(tickers)
            send_telegram_message(chat_id, response)

    # --- YENİ BIST KOMUTLARI ---
    elif text.startswith("/bist_analiz"): # BIST Detaylı Analiz
        logging.info(f">>> /bist_analiz komutu alındı: {text}")
        tickers_input = text[len("/bist_analiz"):].strip()
        # Tek hisse veya virgülle ayrılmış birden fazla hisse
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(',') if ticker.strip()]

        if not tickers:
            send_telegram_message(chat_id, "Lütfen bir veya daha fazla BIST hisse kodu belirtin\\. Örnek: `/bist_analiz MIATK,SELEC`")
        else:
            bist_data = load_bist_analysis_data() # BIST verisini yükle
            if bist_data is None:
                send_telegram_message(chat_id, f"BIST analiz verileri ({BIST_ANALYSIS_FILE}) yüklenirken bir sorun oluştu\\.")
            else:
                responses = []
                found_count = 0
                for ticker in tickers:
                    stock_info = bist_data.get(ticker) # Büyük/küçük harf duyarlı olabilir, JSON'a bağlı
                    if stock_info:
                        responses.append(format_bist_stock_info(stock_info))
                        found_count += 1
                    else:
                        responses.append(f"❌ `{ticker}` için BIST analizi bulunamadı\\.")

                if found_count > 0 and len(tickers) > 1 : # Birden fazla hisse istendi ve en az biri bulunduysa başlık ekle
                     full_response = f"*{len(tickers)} adet BIST hissesi için analiz sonuçları:*\n\n" + "\n\n---\n\n".join(responses)
                else:
                     full_response = "\n\n---\n\n".join(responses)

                send_telegram_message(chat_id, full_response)

    elif text.startswith("/bist_ozet"): # BIST Özet
        logging.info(f">>> /bist_ozet komutu alındı")
        response = generate_bist_ozet_response()
        send_telegram_message(chat_id, response)
    # --- YENİ BIST KOMUTLARI SONU ---

    elif text.startswith("/start"):
         # /start mesajına yeni komutları ekleyelim
         start_message = "Merhaba\\! TradingView sinyallerini ve analizlerini takip eden bota hoş geldiniz\\.\n\n" \
                         "*Kullanılabilir Komutlar:*\n" \
                         "`/ozet [bist|nasdaq|binance]` \\- Kaydedilen sinyallerin özetini gösterir\\.\n" \
                         "`/analiz <HisseKodları>` \\- Belirtilen NASDAQ hisselerinin analizini getirir \\(örn: `/analiz AAPL`\\)\\.\n" \
                         "`/bist_analiz <HisseKodları>` \\- Belirtilen BIST hisselerinin analizini getirir \\(örn: `/bist_analiz MIATK`\\)\\.\n" \
                         "`/bist_ozet` \\- En yüksek skorlu BIST hisselerinin özetini gösterir\\."
                         # Güvenlik nedeniyle /clear_signals'ı listelemiyoruz.
         send_telegram_message(chat_id, start_message)

    # Başka komutlar işlenmiyorsa burası çalışır (opsiyonel)
    # else:
    #     logging.info(f"İşlenmeyen komut/mesaj: {text}")

    return "ok", 200

# --- Diğer Fonksiyonlar (Mevcut halleriyle kalıyor) ---

# /clear_signals endpoint (Mevcut haliyle kalıyor)
@app.route("/clear_signals", methods=["POST"])
def clear_signals_endpoint():
    try:
        clear_signals()
        send_telegram_message(CHAT_ID, "📁 Sinyal dosyası (`signals.json`) temizlendi\\.") # Bilgilendirme
        return "📁 signals.json dosyası temizlendi!", 200
    except Exception as e:
        logging.error(f"/clear_signals hatası: {e}", exc_info=True)
        return str(e), 500

# parse_signal_line (Mevcut haliyle kalıyor)
def parse_signal_line(line):
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        # Çok fazla loglamamak için sadece uyarı seviyesinde tutabiliriz
        # logging.warning(f"Geçersiz JSON satırı atlanıyor: {line.strip()[:100]}...")
        return None
    except Exception as e:
        logging.error(f"Sinyal satırı parse edilirken hata: {e} - Satır: {line.strip()[:100]}...")
        return None

# generate_summary (Mevcut haliyle kalıyor - önceki iyileştirmeler dahil)
def generate_summary(keyword=None):
    logging.info(f"Sinyal özeti oluşturuluyor. Anahtar Kelime: {keyword}")
    if not os.path.exists(SIGNALS_FILE):
        return "📊 Henüz hiç sinyal kaydedilmedi\\."

    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logging.error(f"Sinyal dosyası ({SIGNALS_FILE}) okunurken hata: {e}", exc_info=True)
        return f"Sinyal dosyası okunurken bir hata oluştu: `{SIGNALS_FILE}`"

    summary = {
        "güçlü": set(), "kairi_-30": set(), "kairi_-20": set(),
        "mükemmel_alış": set(), "alış_sayımı": set(),
        "mükemmel_satış": set(), "satış_sayımı": set(), "matisay_-25": set()
    }
    parsed_lines = [parse_signal_line(line) for line in lines]
    parsed_lines = [s for s in parsed_lines if s and isinstance(s, dict)]

    keyword_map = {"bist": "bist_dly", "nasdaq": "bats", "binance": "binance"}
    if keyword:
        keyword_lower = keyword.lower()
        search_keyword = keyword_map.get(keyword_lower, keyword_lower)
        logging.info(f"Filtreleme anahtar kelimesi: {search_keyword}")
        filtered_lines = []
        for s in parsed_lines:
            exchange_lower = s.get("exchange", "").lower()
            # Tam eşleşme veya 'bist' için 'bist_dly' kontrolü
            if search_keyword == exchange_lower or \
               (keyword_lower == 'bist' and exchange_lower == 'bist_dly'):
                filtered_lines.append(s)
        parsed_lines = filtered_lines
        logging.info(f"Filtrelemeden sonra {len(parsed_lines)} sinyal kaldı.")

    processed_signals = 0
    for signal_data in parsed_lines:
        processed_signals += 1
        symbol = signal_data.get("symbol", "N/A")
        exchange = signal_data.get("exchange", "N/A")
        signal = signal_data.get("signal", "")
        timestamp_str = signal_data.get("timestamp", "")

        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ").upper()
        key = f"`{symbol}` ({exchange_display})"
        key_with_time = f"`{symbol}` ({exchange_display} \\- {timestamp_str})" if timestamp_str else key # Zamanı da ekleyebiliriz

        signal_lower = signal.lower()

        try:
            if "kairi" in signal_lower:
                kairi_match = re.search(r"([-+]?\d*\.?\d+)", signal) # Sayıyı bul
                if kairi_match:
                    kairi_value = round(float(kairi_match.group(1)), 2)
                    kairi_key = f"{key}: KAIRI `{kairi_value}`"
                    if kairi_value <= -30: summary["kairi_-30"].add(kairi_key)
                    elif kairi_value <= -20: summary["kairi_-20"].add(kairi_key)
            elif re.search(r"mükemmel alış", signal, re.IGNORECASE): summary["mükemmel_alış"].add(key)
            elif re.search(r"alış sayımı", signal, re.IGNORECASE): summary["alış_sayımı"].add(key)
            elif re.search(r"mükemmel satış", signal, re.IGNORECASE): summary["mükemmel_satış"].add(key)
            elif re.search(r"satış sayımı", signal, re.IGNORECASE): summary["satış_sayımı"].add(key)
            elif "matisay" in signal_lower:
                matisay_match = re.search(r"([-+]?\d*\.?\d+)", signal)
                if matisay_match:
                    matisay_value = round(float(matisay_match.group(1)), 2)
                    if matisay_value < -25: summary["matisay_-25"].add(f"{key}: Matisay `{matisay_value}`")
        except ValueError:
             logging.warning(f"Sinyal içinde sayı dönüştürme hatası ({key}): {signal}")
        except Exception as e:
             logging.error(f"Sinyal işlenirken genel hata ({key}): {e} - Sinyal: {signal}", exc_info=True)

    logging.info(f"Toplam {processed_signals} sinyal işlendi.")

    msg_parts = []
    title_keyword = f" ({keyword.upper()})" if keyword else ""
    msg_parts.append(f"📊 *Sinyal Özeti{title_keyword}*")

    cat_map = {
        "kairi_-30": "🔴 KAIRI ≤ \\-30", "kairi_-20": "🟠 KAIRI ≤ \\-20",
        "matisay_-25": "🟣 Matisay < \\-25", "mükemmel_alış": "🟢 Mükemmel Alış",
        "alış_sayımı": "📈 Alış Sayımı", "mükemmel_satış": "🔵 Mükemmel Satış",
        "satış_sayımı": "📉 Satış Sayımı"#, "güçlü": "✅ GÜÇLÜ EŞLEŞEN" # Güçlü eşleşme şimdilik kapalı
    }
    has_content = False
    for cat_key, cat_title in cat_map.items():
        items = sorted(list(summary[cat_key]))
        if items:
            has_content = True
            msg_parts.append(f"\n*{cat_title}* ({len(items)} adet):")
            item_limit = 20
            display_items = [f"• {item}" for item in items[:item_limit]]
            msg_parts.extend(display_items)
            if len(items) > item_limit:
                msg_parts.append(f"  \\.\\.\\. ve {len(items) - item_limit} tane daha")

    if not has_content:
        keyword_display = f" {keyword.upper()}" if keyword else ""
        # SONUNDA MANUEL \\. OLMAMALI! escape_markdown_v2 halledecek.
        return f"📊 Gösterilecek{keyword_display} sinyal bulunamadı."

    return "\n".join(msg_parts)

# clear_signals (Mevcut haliyle kalıyor)
def clear_signals():
    """signals.json dosyasının içeriğini temizler."""
    try:
        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            f.write("")
        logging.info(f"📁 {SIGNALS_FILE} dosyası başarıyla temizlendi!")
    except Exception as e:
        logging.error(f"📁 {SIGNALS_FILE} temizlenirken hata: {e}", exc_info=True)

# clear_signals_daily (Mevcut haliyle kalıyor)
def clear_signals_daily():
    """Her gün belirli bir saatte sinyal dosyasını temizler."""
    already_cleared_today = False
    target_hour, target_minute = 23, 59
    check_interval = 30
    istanbul_tz = pytz.timezone("Europe/Istanbul")

    while True:
        try:
            now_local = datetime.now(istanbul_tz)
            #logging.debug(f"Günlük temizleme kontrol: {now_local.strftime('%H:%M:%S')}")

            if now_local.hour == target_hour and now_local.minute >= target_minute and not already_cleared_today:
                 logging.info(f"Günlük sinyal temizleme zamanı ({target_hour}:{target_minute}). Temizleniyor...")
                 clear_signals()
                 already_cleared_today = True
            elif now_local.hour == 0 and now_local.minute < 5 and already_cleared_today:
                 logging.info("Yeni gün, günlük temizleme bayrağı sıfırlandı.")
                 already_cleared_today = False
        except Exception as e:
             logging.error(f"Günlük temizleme döngüsünde hata: {e}", exc_info=True)
        time.sleep(check_interval)

# Günlük temizleme thread'i (Mevcut haliyle kalıyor)
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
     clear_thread = threading.Thread(target=clear_signals_daily, daemon=True)
     clear_thread.start()
     logging.info("Günlük sinyal temizleme iş parçacığı başlatıldı.")

# Ana çalıştırma bloğu (Mevcut haliyle kalıyor)
if __name__ == "__main__":
    # Üretim için debug=False önerilir.
    app.run(host="0.0.0.0", port=5000, debug=False)
