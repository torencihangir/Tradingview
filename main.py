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
import logging # Logging ekleyelim

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# Logging yapılandırması
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") # Belirli bir sohbete göndermek için, webhook'tan gelen chat_id'yi kullanmak daha esnek olabilir
SIGNALS_FILE = "C:\\Users\\Administrator\\Desktop\\tradingview-telegram-bot\\signals.json" # Tam yolu kullanmaya devam edebilirsiniz veya göreceli yol tercih edilebilir
NASDAQ_ANALIZ_FILE = "analiz.json"
BIST_ANALYSIS_FILE = "analiz_sonuclari.json" # BIST analiz dosyasının adı

def escape_markdown_v2(text):
    # Telegram MarkdownV2'de özel karakterleri kaçırmak gerekiyor
    # Nokta ve ünlem işaretini çıkaralım, genellikle metin içinde sorun yaratmazlar ve okunabilirliği artırır.
    escape_chars = r"\_*[]()~`>#+-=|{}"
    # Metnin tamamını değil, sadece karakterleri kaçırıyoruz
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text)) # Gelen verinin str olduğundan emin olalım

def send_telegram_message(chat_id_to_send, message):
    """Belirtilen chat_id'ye mesaj gönderir."""
    if not chat_id_to_send:
        logging.error("Mesaj göndermek için chat_id belirtilmedi.")
        return

    # Çok uzun mesajları bölmek için fonksiyon
    def split_message(msg, max_len=4096):
        chunks = []
        current_chunk = ""
        for line in msg.split('\n'):
            # Eğer mevcut chunk + yeni satır + satırın kendisi max_len'i aşarsa
            # veya sadece yeni satırın kendisi bile max_len'i aşarsa (çok nadir)
            if len(current_chunk) + len(line) + 1 > max_len or len(line) > max_len:
                if current_chunk: # Eğer chunk'ta bir şey varsa gönder
                    chunks.append(current_chunk)
                # Eğer satırın kendisi bile çok uzunsa, onu da böl (çok olası değil ama önlem)
                if len(line) > max_len:
                     for i in range(0, len(line), max_len):
                         chunks.append(line[i:i+max_len])
                else:
                    current_chunk = line # Yeni chunk bu satırla başlasın
            else:
                if current_chunk: # Chunk boş değilse araya newline ekle
                    current_chunk += "\n" + line
                else: # Chunk boşsa direkt satırı ekle
                    current_chunk = line
        if current_chunk: # Son kalan chunk'ı ekle
            chunks.append(current_chunk)
        return chunks

    escaped_message = escape_markdown_v2(message) # Mesajın tamamını başta escape et
    message_chunks = split_message(escaped_message, 4090) # Biraz pay bırakalım

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chunk in message_chunks:
        data = {
            "chat_id": chat_id_to_send,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            r = requests.post(url, json=data, timeout=10) # Timeout'u biraz artıralım
            r.raise_for_status() # HTTP hatalarını kontrol et
            logging.info(f"Telegram yanıtı ({chat_id_to_send}): {r.status_code} - {r.text[:100]}...") # Yanıtı kısaltarak loglayalım
        except requests.exceptions.RequestException as e:
            logging.error(f"Telegram'a mesaj gönderilemedi ({chat_id_to_send}): {e}")
        except Exception as e:
             logging.error(f"Mesaj gönderirken beklenmedik hata ({chat_id_to_send}): {e}")
        time.sleep(0.5) # Rate limiting'e takılmamak için küçük bir bekleme


@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        logging.info(">>> /signal endpoint tetiklendi")
        # ... (Mevcut signal kodunuz - değişiklik yok) ...
        # Sinyal mesajını göndermek için global CHAT_ID yerine
        # belirli bir ID kullanmak daha iyi olabilir veya webhook'tan alınabilir.
        # Şimdilik mevcut haliyle bırakıyorum:
        # ...
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        message_text = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange_display})\n📍 _{signal}_"
        send_telegram_message(CHAT_ID, message_text) # Global CHAT_ID'ye gönderiyor

        return "ok", 200
    except Exception as e:
        logging.error(f"/signal hatası: {e}", exc_info=True) # Hatanın detayını logla
        return str(e), 500

# --- BIST ANALİZ İÇİN YENİ FONKSİYONLAR ---

def load_bist_analysis_data():
    """analiz_sonuclari.json dosyasını yükler ve veriyi döndürür."""
    try:
        with open(BIST_ANALYSIS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logging.info(f"{BIST_ANALYSIS_FILE} başarıyla yüklendi.")
            return data
    except FileNotFoundError:
        logging.error(f"Hata: {BIST_ANALYSIS_FILE} dosyası bulunamadı.")
        return None
    except json.JSONDecodeError:
        logging.error(f"Hata: {BIST_ANALYSIS_FILE} dosyasındaki JSON formatı bozuk.")
        return None
    except Exception as e:
        logging.error(f"{BIST_ANALYSIS_FILE} yüklenirken beklenmedik bir hata oluştu: {e}", exc_info=True)
        return None

def format_bist_stock_info(stock_data):
    """Verilen BIST hisse senedi verisini Telegram mesajı için formatlar."""
    if not stock_data or not isinstance(stock_data, dict):
        return "Hisse senedi verisi bulunamadı veya formatı geçersiz."

    symbol = stock_data.get('symbol', 'N/A')
    score = stock_data.get('score', 'N/A')
    classification = stock_data.get('classification', 'N/A')
    comments = stock_data.get('comments', [])

    # Mesajı MarkdownV2 formatında oluşturalım (escape işlemi send_telegram_message içinde yapılacak)
    message = f"📊 *BIST Analiz: {symbol}*\n\n"
    message += f"🔢 *Skor:* `{score}`\n"
    message += f"⭐ *Sınıflandırma:* _{classification}_\n\n" # İtalik yapalım
    message += "📝 *Önemli Yorumlar:*\n"

    if comments:
        comment_limit = 7 # Gösterilecek maksimum yorum sayısı
        for i, comment in enumerate(comments):
            if i >= comment_limit:
                message += f"  \\.\\.\\. _({len(comments) - comment_limit} yorum daha var)_\n"
                break

            # Yorumları daha okunabilir yapalım
            comment_text = str(comment) # Yorumun string olduğundan emin ol
            value_part = ""

            # Değerleri ayıklamaya çalışalım
            deger_match = re.search(r"(Değer|Değerler):\s*(.*?)$", comment_text, re.IGNORECASE)
            if deger_match:
                comment_base = comment_text[:deger_match.start()].strip().rstrip('.')
                value_part = f": `{deger_match.group(2).strip()}`" # Değeri kod bloğuna al
                message += f"  • {comment_base}{value_part}\n"
            elif "geçerli bir sayı değil" in comment_text:
                 # "Finansal Borç Azalışı verileri geçerli bir sayı değil." gibi
                 base_part = comment_text.split(" verileri")[0]
                 message += f"  • {base_part}: `(Veri Yok/Hatalı)`\n"
            else:
                 # Diğer yorumlar olduğu gibi
                 message += f"  • {comment_text.strip()}\n"
    else:
        message += "  _Yorum bulunamadı\\._\n"

    # Basit bir genel yorum ekleyelim
    message += f"\n💡 *Genel Bakış:* `{symbol}` hissesi, analizde _{classification}_ olarak sınıflandırılmış ve `{score}` puan almıştır\\. "
    if classification == "Excellent":
        message += "Finansal göstergeleri genel olarak güçlü duruyor\\."
    elif classification == "Good":
        message += "Finansal göstergeleri genel olarak olumlu, bazı alanlar dikkat çekebilir\\."
    elif classification == "Average":
        message += "Finansal göstergeleri ortalama düzeyde seyrediyor\\."
    elif classification == "Poor":
        message += "Finansal göstergelerinde zayıflıklar mevcut, dikkatli olunmalı\\."
    else:
        message += "Detaylı yorumlar incelenmelidir\\."

    return message

def generate_bist_ozet_response():
    """En yüksek skorlu BIST hisselerinin bir özetini oluşturur."""
    logging.info("BIST özeti oluşturuluyor...")
    bist_data = load_bist_analysis_data()

    if bist_data is None:
         return f"Analiz verileri ({BIST_ANALYSIS_FILE}) yüklenirken bir sorun oluştu\\."
    if not bist_data:
        return "BIST için analiz verisi bulunamadı\\."

    try:
        # Hisseleri skora göre (yüksekten düşüğe) sırala
        # Sadece dict olan ve 'score' içerenleri al, score sayısal olmalı
        valid_stocks = []
        for symbol, data in bist_data.items():
            if isinstance(data, dict) and isinstance(data.get('score'), (int, float)):
                valid_stocks.append(data)
            else:
                logging.warning(f"BIST özeti için geçersiz veri: {symbol} - {data.get('score')}")

        sorted_stocks = sorted(
            valid_stocks,
            key=lambda x: x['score'], # Artık score'un sayısal olduğunu biliyoruz
            reverse=True
        )

        top_n = 15 # Gösterilecek hisse sayısı
        if not sorted_stocks:
            return "Sıralanacak geçerli BIST hisse senedi bulunamadı\\."

        message = f"🏆 *BIST Analiz Özeti (En Yüksek Skorlu {min(top_n, len(sorted_stocks))} Hisse):*\n\n"
        for stock in sorted_stocks[:top_n]:
            symbol = stock.get('symbol', 'N/A')
            score = stock.get('score', 'N/A')
            classification = stock.get('classification', 'N/A')
            # /bist_analiz komutuna yönlendirme (MarkdownV2 escape ile)
            # ÖNEMLİ: Komutları botfather ile tanımlamış olmalısınız.
            message += f"• `{symbol}`: Skor `{score}` (_{classification}_) \\- /bist\\_analiz {symbol}\n"

        # İsteğe bağlı: Sadece "Excellent" olanları da ekleyebilirsiniz
        excellent_stocks = [s for s in sorted_stocks if s.get('classification') == 'Excellent']
        if excellent_stocks:
             message += "\n⭐ *'Excellent' Sınıflandırılanlar:*\n"
             # Çok fazla ise hepsini listelemek yerine sayısını yazabiliriz
             if len(excellent_stocks) > 20:
                  message += f"Toplam {len(excellent_stocks)} adet 'Excellent' hisse bulundu\\. İlk birkaçı: "
                  ex_symbols = [f"`{s.get('symbol', 'N/A')}`" for s in excellent_stocks[:5]]
                  message += ", ".join(ex_symbols) + "\\.\\.\\."
             else:
                ex_symbols = [f"`{s.get('symbol', 'N/A')}`" for s in excellent_stocks]
                message += ", ".join(ex_symbols)

        return message

    except Exception as e:
        logging.error(f"BIST özeti oluşturulurken hata: {e}", exc_info=True)
        return "BIST özeti oluşturulurken bir hata meydana geldi\\."

# --- NASDAQ ANALİZ İÇİN MEVCUT FONKSİYONLAR (Güncellenmiş Hata Yönetimi ve Loglama) ---

def load_nasdaq_analiz_json():
    """analiz.json dosyasını yükler (NASDAQ için)."""
    try:
        with open(NASDAQ_ANALIZ_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            logging.info(f"{NASDAQ_ANALIZ_FILE} başarıyla yüklendi.")
            return data
    except FileNotFoundError:
        logging.error(f"Hata: {NASDAQ_ANALIZ_FILE} dosyası bulunamadı.")
        return {} # Boş dict döndürerek hatayı yukarıda yönetelim
    except json.JSONDecodeError:
        logging.error(f"Hata: {NASDAQ_ANALIZ_FILE} dosyası geçerli bir JSON formatında değil.")
        return {}
    except Exception as e:
        logging.error(f"{NASDAQ_ANALIZ_FILE} yüklenirken beklenmedik hata: {e}", exc_info=True)
        return {}

def generate_nasdaq_analiz_response(tickers):
    """Belirtilen NASDAQ hisseleri için analiz yanıtı oluşturur."""
    analiz_verileri = load_nasdaq_analiz_json()
    if not analiz_verileri: # Eğer yükleme başarısız olduysa
         return f"NASDAQ analiz verileri ({NASDAQ_ANALIZ_FILE}) yüklenemedi veya boş\\."

    analiz_listesi = []
    for ticker in tickers:
        ticker_upper = ticker.upper()
        analiz = analiz_verileri.get(ticker_upper)
        if analiz and isinstance(analiz, dict): # Verinin varlığını ve dict olduğunu kontrol et
            puan = analiz.get("puan", 0)
            # Detaylar listesi içindeki her öğeyi str yapıp birleştirelim
            detaylar_list = analiz.get("detaylar", [])
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

    # Puanlara göre büyükten küçüğe sıralama (None değerlerini en sona at)
    analiz_listesi.sort(key=lambda x: (x["puan"] is not None, x.get("puan", -1)), reverse=True)

    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            # /analiz komutunu tekrar eklemeye gerek yok, zaten içindeyiz.
            response_lines.append(
                f"📊 *NASDAQ Analiz: {analiz['ticker']}* (Puan: `{analiz['puan']}`)\n\n{analiz['detaylar']}\n\n💡 *Yorum:*\n_{analiz['yorum']}_"
            )
        else:
            response_lines.append(analiz["yorum"])

    # Çok fazla hisse varsa mesajı bölmek gerekebilir, send_telegram_message bunu yapacak.
    return "\n\n---\n\n".join(response_lines) # Hisseler arasına ayırıcı ekleyelim

# --- TELEGRAM WEBHOOK ---

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    logging.info(">>> /telegram endpoint tetiklendi")
    update = request.json
    if not update:
        logging.warning("Boş JSON verisi alındı.")
        return "nok", 200 # Hata vermemek için 'nok' döndürelim

    message = update.get("message") or update.get("edited_message") # Düzenlenen mesajları da yakala
    if not message:
        logging.info("Mesaj içeriği bulunamadı (callback_query vb. olabilir).")
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

    # Komutları işle
    if text.startswith("/ozet"):
        logging.info(f">>> /ozet komutu alındı: {text}")
        keyword = text[len("/ozet"):].strip().lower() # /ozet'ten sonrasını al
        # Anahtar kelime kontrolü
        allowed_keywords = ["bats", "nasdaq", "bist", "bist_dly", "binance"]
        if keyword and keyword not in allowed_keywords:
             summary_text = f"Geçersiz anahtar kelime: `{keyword}`\\. Lütfen `bats`, `nasdaq`, `bist` veya `binance` kullanın ya da boş bırakın\\."
        elif keyword:
             logging.info(f"/ozet için anahtar kelime: {keyword}")
             summary_text = generate_summary(keyword) # generate_summary güncellenmeli
        else:
             summary_text = generate_summary() # Varsayılan özet
        send_telegram_message(chat_id, summary_text)

    elif text.startswith("/analiz"): # NASDAQ Analizi
        logging.info(f">>> /analiz (NASDAQ) komutu alındı: {text}")
        tickers_input = text[len("/analiz"):].strip()
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
        if not tickers:
            send_telegram_message(chat_id, "Lütfen bir veya daha fazla NASDAQ hisse kodu belirtin\\. Örnek: `/analiz AAPL,MSFT`")
        else:
            response = generate_nasdaq_analiz_response(tickers)
            send_telegram_message(chat_id, response)

    elif text.startswith("/bist_analiz"): # BIST Analizi
        logging.info(f">>> /bist_analiz komutu alındı: {text}")
        tickers_input = text[len("/bist_analiz"):].strip()
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]

        if not tickers:
            send_telegram_message(chat_id, "Lütfen bir veya daha fazla BIST hisse kodu belirtin\\. Örnek: `/bist_analiz MIATK,SELEC`")
        else:
            bist_data = load_bist_analysis_data()
            if bist_data is None:
                send_telegram_message(chat_id, f"BIST analiz verileri ({BIST_ANALYSIS_FILE}) yüklenirken bir sorun oluştu\\.")
            else:
                responses = []
                for ticker in tickers:
                    stock_info = bist_data.get(ticker)
                    if stock_info:
                        responses.append(format_bist_stock_info(stock_info))
                    else:
                        responses.append(f"❌ `{ticker}` için BIST analizi bulunamadı\\.")
                # Hisseler arasına ayırıcı ekle
                full_response = "\n\n---\n\n".join(responses)
                send_telegram_message(chat_id, full_response)

    elif text.startswith("/bist_ozet"):
        logging.info(f">>> /bist_ozet komutu alındı")
        response = generate_bist_ozet_response()
        send_telegram_message(chat_id, response)

    # Diğer komutlar buraya eklenebilir
    elif text.startswith("/start"):
         start_message = "Merhaba\\! TradingView sinyallerini ve analizlerini takip eden bota hoş geldiniz\\.\n\n" \
                         "*Kullanılabilir Komutlar:*\n" \
                         "`/ozet [bist|nasdaq|binance]` \\- Kaydedilen sinyallerin özetini gösterir (isteğe bağlı filtreleme)\\.\n" \
                         "`/analiz <HisseKodları>` \\- Belirtilen NASDAQ hisselerinin analizini getirir (örn: `/analiz AAPL,TSLA`)\\.\n" \
                         "`/bist_analiz <HisseKodları>` \\- Belirtilen BIST hisselerinin analizini getirir (örn: `/bist_analiz MIATK,FROTO`)\\.\n" \
                         "`/bist_ozet` \\- En yüksek skorlu BIST hisselerinin özetini gösterir\\.\n" \
                         # `/clear_signals` komutunu buraya eklememek daha güvenli olabilir.
         send_telegram_message(chat_id, start_message)

    # Bilinmeyen komut veya mesaj için yanıt (isteğe bağlı)
    # else:
    #     logging.info(f"İşlenmeyen mesaj: {text}")
    #     send_telegram_message(chat_id, "Anlayamadım\\. Yardım için `/start` yazabilirsiniz\\.")

    return "ok", 200

# --- Diğer Fonksiyonlar (clear_signals vb.) ---

@app.route("/clear_signals", methods=["POST"])
def clear_signals_endpoint():
    # Bu endpoint'i dışarıya açık bırakmak riskli olabilir.
    # Belki bir şifre veya IP kontrolü eklemek iyi olabilir.
    # Örnek: if request.headers.get('X-Admin-Token') != 'GIZLI_TOKEN': return "Yetkisiz", 403
    try:
        clear_signals()
        send_telegram_message(CHAT_ID, "📁 Sinyal dosyası temizlendi\\.") # Bilgilendirme mesajı
        return "📁 signals.json dosyası temizlendi!", 200
    except Exception as e:
        logging.error(f"/clear_signals hatası: {e}", exc_info=True)
        return str(e), 500

def parse_signal_line(line):
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        logging.warning(f"Geçersiz JSON satırı: {line.strip()}")
        return None
    except Exception as e:
        logging.error(f"Sinyal satırı parse edilirken hata: {e} - Satır: {line.strip()}")
        return None

# generate_summary fonksiyonu güncellenmeli (loglama, hata yönetimi vb.)
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
        "güçlü": set(),
        "kairi_-30": set(),
        "kairi_-20": set(),
        "mükemmel_alış": set(),
        "alış_sayımı": set(),
        "mükemmel_satış": set(),
        "satış_sayımı": set(),
        "matisay_-25": set()
    }

    parsed_lines = [parse_signal_line(line) for line in lines]
    parsed_lines = [s for s in parsed_lines if s and isinstance(s, dict)] # None ve dict olmayanları filtrele

    # Anahtar kelimelere göre filtreleme yap
    keyword_map = {
        "bist": "bist_dly", # Kullanıcı 'bist' yazınca 'bist_dly' aransın
        "nasdaq": "bats",
        "binance": "binance"
        # 'bist_dly' direkt olarak da kullanılabilir
    }
    if keyword:
        keyword_lower = keyword.lower()
        # Eğer kullanıcı bist_dly yazdıysa onu da kabul et
        search_keyword = keyword_map.get(keyword_lower, keyword_lower)
        logging.info(f"Filtreleme anahtar kelimesi: {search_keyword}")
        filtered_lines = []
        for s in parsed_lines:
             exchange_lower = s.get("exchange", "").lower()
             if search_keyword in exchange_lower:
                  filtered_lines.append(s)
             # Özel durum: kullanıcı 'bist' yazdıysa ve exchange 'bist_dly' ise eşleştir
             elif keyword_lower == 'bist' and 'bist_dly' in exchange_lower:
                 filtered_lines.append(s)
        parsed_lines = filtered_lines
        logging.info(f"Filtrelemeden sonra {len(parsed_lines)} sinyal kaldı.")


    # Zaman damgası ekleyerek aynı sembol için birden fazla sinyali ayırt edebiliriz
    # Şimdilik sadece sembol/exchange bazında tutuyoruz
    processed_signals = 0
    for signal_data in parsed_lines:
        processed_signals += 1
        symbol = signal_data.get("symbol", "N/A")
        exchange = signal_data.get("exchange", "N/A")
        signal = signal_data.get("signal", "")
        timestamp_str = signal_data.get("timestamp", "") # Zaman damgasını alalım

        # Exchange adını kısaltalım
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ").upper()
        key = f"`{symbol}` ({exchange_display})"
        key_with_time = f"`{symbol}` ({exchange_display} \\- {timestamp_str})" if timestamp_str else key

        signal_lower = signal.lower()

        try:
            if "kairi" in signal_lower:
                kairi_match = re.search(r"[-+]?\d*\.?\d+", signal) # Daha sağlam regex
                if kairi_match:
                    kairi_value = round(float(kairi_match.group(0)), 2)
                    kairi_key = f"{key}: KAIRI `{kairi_value}`"
                    if kairi_value <= -30:
                        summary["kairi_-30"].add(kairi_key)
                    elif kairi_value <= -20:
                        summary["kairi_-20"].add(kairi_key)

                    # Güçlü sinyal kontrolü (performans için optimize edilebilir)
                    # for other in parsed_lines:
                    #     if (
                    #         other.get("symbol") == symbol and other.get("exchange") == exchange and
                    #         re.search(r"(mükemmel alış|alış sayımı)", other.get("signal", ""), re.IGNORECASE)
                    #     ):
                    #         summary["güçlü"].add(f"✅ {key} \\- KAIRI: `{kairi_value}` ve Alış sinyali\\!")
                    #         break # Bir eşleşme yeterli
            elif re.search(r"mükemmel alış", signal, re.IGNORECASE):
                summary["mükemmel_alış"].add(key)
            elif re.search(r"alış sayımı", signal, re.IGNORECASE):
                summary["alış_sayımı"].add(key)
            elif re.search(r"mükemmel satış", signal, re.IGNORECASE):
                summary["mükemmel_satış"].add(key)
            elif re.search(r"satış sayımı", signal, re.IGNORECASE):
                summary["satış_sayımı"].add(key)
            elif "matisay" in signal_lower:
                matisay_match = re.search(r"[-+]?\d*\.?\d+", signal)
                if matisay_match:
                    matisay_value = round(float(matisay_match.group(0)), 2)
                    if matisay_value < -25:
                        summary["matisay_-25"].add(f"{key}: Matisay `{matisay_value}`")
        except Exception as e:
             logging.error(f"Sinyal işlenirken hata ({key}): {e} - Sinyal: {signal}", exc_info=True)


    logging.info(f"Toplam {processed_signals} sinyal işlendi.")

    # Mesaj oluşturma
    msg_parts = []
    title_keyword = f" ({keyword.upper()})" if keyword else ""
    msg_parts.append(f"📊 *Sinyal Özeti{title_keyword}*")

    # Kategorileri ekle
    cat_map = {
        #"güçlü": "✅ GÜÇLÜ EŞLEŞEN SİNYALLER", # Bu kısım yavaş olabilir, şimdilik kapalı
        "kairi_-30": "🔴 KAIRI ≤ \\-30",
        "kairi_-20": "🟠 KAIRI ≤ \\-20",
        "matisay_-25": "🟣 Matisay < \\-25",
        "mükemmel_alış": "🟢 Mükemmel Alış",
        "alış_sayımı": "📈 Alış Sayımı",
        "mükemmel_satış": "🔵 Mükemmel Satış",
        "satış_sayımı": "📉 Satış Sayımı",
    }

    has_content = False
    for cat_key, cat_title in cat_map.items():
        items = sorted(list(summary[cat_key])) # Alfabetik sıralama
        if items:
            has_content = True
            msg_parts.append(f"\n*{cat_title}* ({len(items)} adet):")
            # Çok fazla ise kısalt
            item_limit = 20
            if len(items) > item_limit:
                 msg_parts.extend([f"• {item}" for item in items[:item_limit]])
                 msg_parts.append(f"  \\.\\.\\. ve {len(items) - item_limit} tane daha")
            else:
                 msg_parts.extend([f"• {item}" for item in items])


    if not has_content:
        return f"📊 Gösterilecek {keyword.upper() if keyword else ''} sinyal bulunamadı\\."

    return "\n".join(msg_parts)


def clear_signals():
    """signals.json dosyasının içeriğini temizler."""
    try:
        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            f.write("")
        logging.info(f"📁 {SIGNALS_FILE} dosyası başarıyla temizlendi!")
    except Exception as e:
        logging.error(f"📁 {SIGNALS_FILE} temizlenirken hata: {e}", exc_info=True)

def clear_signals_daily():
    """Her gün belirli bir saatte sinyal dosyasını temizler."""
    already_cleared_today = False
    target_hour = 23
    target_minute = 59
    check_interval = 30 # Saniye

    while True:
        try:
            now_utc = datetime.now(pytz.utc)
            now_local = now_utc.astimezone(pytz.timezone("Europe/Istanbul"))
            #logging.debug(f"Günlük temizleme kontrolü: {now_local.strftime('%H:%M:%S')}")

            # Hedef zamana geldiysek ve bugün temizlemediysek
            if now_local.hour == target_hour and now_local.minute >= target_minute and not already_cleared_today:
                 logging.info(f"Günlük sinyal temizleme zamanı ({target_hour}:{target_minute}). Temizleniyor...")
                 clear_signals()
                 already_cleared_today = True
            # Gece yarısını geçtiyse flag'i sıfırla
            elif now_local.hour == 0 and now_local.minute < 5 and already_cleared_today:
                 logging.info("Yeni gün, günlük temizleme bayrağı sıfırlandı.")
                 already_cleared_today = False

        except Exception as e:
             logging.error(f"Günlük temizleme döngüsünde hata: {e}", exc_info=True)

        time.sleep(check_interval)


# Günlük temizleme iş parçacığını başlat
# Flask'ın reloader'ı ile kullanırken dikkatli olun, birden fazla thread başlatabilir.
# Üretim ortamında (örneğin gunicorn ile) bu genellikle sorun olmaz.
# Gunicorn kullanıyorsanız, preload_app=True ile thread'in tek sefer başlatılmasını sağlayabilirsiniz.
# Basitlik adına şimdilik burada bırakıyoruz.
if os.environ.get("WERKZEUG_RUN_MAIN") != "true": # Flask reloader'ın çift başlatmasını engelle
     clear_thread = threading.Thread(target=clear_signals_daily, daemon=True)
     clear_thread.start()
     logging.info("Günlük sinyal temizleme iş parçacığı başlatıldı.")


if __name__ == "__main__":
    # Gunicorn gibi bir WSGI sunucusu kullanmıyorsanız, development server için:
    # debug=True reloader'ı etkinleştirir, bu da thread'in iki kez başlamasına neden olabilir.
    # Üretim için debug=False kullanın.
    app.run(host="0.0.0.0", port=5000, debug=False)
