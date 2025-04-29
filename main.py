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
# DOSYA YOLLARI - Bunların sunucunuzdaki gerçek yollar olduğundan emin olun!
# Örnek: SIGNALS_FILE = "/home/user/tradingview-telegram-bot/signals.json"
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json") # .env'den yolu al, yoksa varsayılanı kullan
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")

# --- Helper Functions ---

def escape_markdown_v2(text):
    """Telegram MarkdownV2 için özel karakterleri kaçırır."""
    # Kaçırılacak karakterler: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    # Metin içindeki TÜM bu karakterleri kaçırır. Formatlama (kalın, italik vb.)
    # mesaj gönderilmeden önce * veya _ eklenerek yapılır, bu fonksiyon sadece
    # metnin kendisindeki karakterleri korumak içindir.
    return re.sub(r"([{}])".format(re.escape(escape_chars)), r"\\\1", str(text)) # Girdi her zaman string olsun

def send_telegram_message(message_text):
    """Mesajı Telegram'a gönderir, MarkdownV2 kullanır ve karakterleri kaçırır."""
    # ÖNEMLİ: Markdown formatlaması (*bold*, _italic_) bu fonksiyona gönderilmeden
    # ÖNCE mesaja eklenmelidir. Bu fonksiyon sadece metin İÇİNDEKİ özel karakterleri
    # Telegram'ın yanlış yorumlamaması için kaçırır.

    # Kaçırma işlemi: Metin içindeki özel karakterleri koru
    # Not: Bu basit kaçırma, mesaj içinde bilinçli olarak * veya _ kullanmak
    # isterseniz sorun yaratabilir. Daha gelişmiş bir kaçırma gerekebilir.
    # Şimdilik, formatlama için kullanılan * ve _'nin mesaj içinde
    # düz metin olarak geçmediğini varsayıyoruz.
    escaped_message = escape_markdown_v2(message_text)

    # Telegram API URL
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # Mesajı 4096 karakterlik parçalara böl (Telegram limiti)
    for i in range(0, len(escaped_message), 4096):
        chunk = escaped_message[i:i+4096]
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            r = requests.post(url, json=data, timeout=20) # Timeout artırıldı
            r.raise_for_status() # HTTP hatalarını kontrol et (4xx, 5xx)
            response_json = r.json()
            if response_json.get("ok"):
                print(f"✅ Mesaj parçası başarıyla gönderildi (Chat ID: {CHAT_ID})")
            else:
                print(f"❌ Telegram API hatası: {response_json.get('description')}")
                print(f"❌ Hatalı Chunk (escaped): {chunk[:200]}...") # Sorunlu parçanın başını logla
                print(f"❌ Orijinal Mesaj Başlangıcı: {message_text[i:i+200]}...")

        except requests.exceptions.Timeout:
            print(f"❌ Telegram API isteği zaman aşımına uğradı (URL: {url})")
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi: {e}")
            print(f"❌ Gönderilemeyen mesaj parçası (orijinal): {message_text[i:i+4096][:200]}...")
        except json.JSONDecodeError:
             print(f"❌ Telegram API'den geçerli JSON yanıtı alınamadı. Yanıt: {r.text}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")
            print(f"❌ Hata detayı (Tip): {type(e)}")


def parse_signal_line(line):
    """signals.json dosyasından bir satırı JSON olarak ayrıştırır."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        print(f"⚠️ JSON parse hatası (atlandı): {line.strip()}")
        return None # Hatalı satırı atla

def load_json_file(filepath):
    """Belirtilen JSON dosyasını yükler ve içeriğini döndürür."""
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Uyarı: '{filepath}' dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError:
        print(f"Hata: '{filepath}' dosyası geçerli bir JSON formatında değil.")
        return {}
    except Exception as e:
        print(f"Beklenmedik Hata ('{filepath}' okuma): {e}")
        return {}

# --- Flask Routes ---

@app.route("/signal", methods=["POST"])
def receive_signal():
    """TradingView'dan gelen sinyalleri alır, dosyaya yazar ve Telegram'a gönderir."""
    print(f"[{datetime.now()}] >>> /signal endpoint tetiklendi")
    try:
        if request.is_json:
            data = request.get_json()
            print(">>> Gelen JSON verisi:", data)
        elif request.content_type == 'text/plain':
             # Ham metin verisini işle
            raw_text = request.data.decode("utf-8").strip()
            print(">>> Gelen metin verisi:", raw_text)
            # Basit bir varsayım: İlk kelime sembol, geri kalanı sinyal mesajı
            # Daha karmaşık formatlar için regex veya split kullanılabilir.
            parts = raw_text.split(None, 2) # En fazla 2 boşluğa göre ayır
            symbol = "Bilinmiyor"
            exchange = "Bilinmiyor" # Varsa ayrıştırılabilir, şimdilik varsayılan
            signal_msg = raw_text # Varsayılan olarak tüm metin

            if len(parts) >= 2:
                # Format: "SYMBOL (EXCHANGE) - Signal Message" veya "SYMBOL Signal Message"
                match_exchange = re.match(r"^(.*?)\s+\((.*?)\)\s*-\s*(.*)$", raw_text)
                if match_exchange:
                    symbol, exchange, signal_msg = match_exchange.groups()
                else:
                    # Format: "SYMBOL Signal Message"
                    symbol = parts[0]
                    signal_msg = " ".join(parts[1:])
            elif len(parts) == 1:
                # Sadece sinyal mesajı geldi varsayımı
                 signal_msg = parts[0]


            data = {
                "symbol": symbol.strip(),
                "exchange": exchange.strip(),
                "signal": signal_msg.strip()
            }
            print(">>> Metinden ayrıştırılan veri:", data)

        else:
            print(f"❌ Desteklenmeyen içerik türü: {request.content_type}")
            return "Unsupported Media Type", 415

        # Zaman damgası ekle (UTC)
        data["timestamp_utc"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        # Yerel zaman damgası (İstanbul)
        try:
             tz_istanbul = pytz.timezone("Europe/Istanbul")
             data["timestamp_tr"] = datetime.now(tz_istanbul).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as tz_err:
             print(f"Yerel zaman alınırken hata: {tz_err}")
             data["timestamp_tr"] = "Hata"


        # Sinyal dosyasına ekle (her sinyal yeni bir satırda JSON)
        try:
            with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
                # ensure_ascii=False Türkçe karakterlerin korunmasını sağlar
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except IOError as e:
             print(f"❌ Sinyal dosyasına yazılamadı ({SIGNALS_FILE}): {e}")
             # Hata durumunda Telegram'a bildirim gönderilebilir
             send_telegram_message(f"⚠️ *UYARI:* Sinyal dosyasına yazılamadı\\! Hata: `{escape_markdown_v2(str(e))}`")
             # return "Error writing to file", 500 # Opsiyonel: İstemciye hata döndür

        # Telegram'a gönderilecek mesajı hazırla
        symbol = escape_markdown_v2(data.get("symbol", "Bilinmiyor"))
        exchange = escape_markdown_v2(data.get("exchange", "Bilinmiyor"))
        signal_msg = escape_markdown_v2(data.get("signal", "İçerik Yok"))
        timestamp_tr = escape_markdown_v2(data.get("timestamp_tr", "N/A"))

        # Borsa isimlerini daha okunabilir hale getir (kaçırmadan önce)
        exchange_display = data.get("exchange", "Bilinmiyor").replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        exchange_display_escaped = escape_markdown_v2(exchange_display)

        # Mesaj Formatı (MarkdownV2) - Format karakterleri (*, _) burada eklenir
        message = f"📡 *Yeni Sinyal Geldi*\n\n" \
                  f"🪙 *Sembol:* `{symbol}`\n" \
                  f"🏦 *Borsa:* {exchange_display_escaped}\n" \
                  f"💬 *Sinyal:* _{signal_msg}_\n" \
                  f"⏰ *Zaman \\(TR\\):* {timestamp_tr}"

        send_telegram_message(message)

        return "ok", 200

    except json.JSONDecodeError as e:
         print(f"❌ /signal JSON parse hatası: {e}")
         print(f"Gelen Ham Veri: {request.data}")
         return f"Bad Request: Invalid JSON - {e}", 400
    except Exception as e:
        print(f"❌ /signal endpoint genel hatası: {e}")
        print(f"❌ Hata Tipi: {type(e)}")
        # Hata durumunda Telegram'a bilgi gönderilebilir
        try:
            error_message = f"❌ `/signal` endpointinde kritik hata oluştu\\!\n*Hata:* `{escape_markdown_v2(str(e))}`"
            send_telegram_message(error_message)
        except Exception as telegram_err:
            print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return f"Internal Server Error: {e}", 500

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Telegram'dan gelen mesajları (komutları) işler."""
    print(f"[{datetime.now()}] >>> /telegram endpoint tetiklendi")
    update = request.json
    if not update:
        print("⚠️ Boş JSON verisi alındı.")
        return "ok", 200

    message = update.get("message") or update.get("channel_post") # Normal mesaj veya kanal postu olabilir

    if not message:
        # Mesaj olmayan diğer güncellemeleri (edited_message vb.) şimdilik atla
        print("Gelen güncelleme işlenecek bir mesaj değil, atlanıyor.")
        return "ok", 200

    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")
    sender_info = message.get("from", {}) # Kullanıcı bilgisi (varsa)
    sender_username = sender_info.get("username", "N/A")
    sender_id = sender_info.get("id", "N/A")

    # Güvenlik: Sadece belirlenen CHAT_ID'den gelen mesajları işle
    if str(chat_id) != CHAT_ID:
        print(f"⚠️ Uyarı: Mesaj beklenen sohbetten gelmedi (Gelen: {chat_id}, Beklenen: {CHAT_ID}). İşlenmeyecek.")
        # İsterseniz yetkisiz erişim hakkında bir log veya bildirim yapabilirsiniz
        # send_telegram_message(f"Yetkisiz erişim denemesi: Chat ID {chat_id}")
        return "ok", 200 # Yetkisiz sohbetten gelen komutları sessizce engelle

    if not text:
        print("ℹ️ Boş mesaj içeriği alındı.")
        return "ok", 200

    print(f">>> Mesaj alındı (Chat ID: {chat_id}, Kullanıcı: @{sender_username} / {sender_id}): '{text}'")

    # Komutları işle
    response_message = None
    try:
        if text.startswith("/ozet"):
            print(">>> /ozet komutu işleniyor...")
            keyword = text[6:].strip().lower() if len(text) > 6 else None
            # İzin verilen anahtar kelimeler (küçük harf)
            allowed_keywords = ["bats", "nasdaq", "bist_dly", "binance", "bist"]
            if keyword and keyword not in allowed_keywords:
                 # Geçersiz anahtar kelimeyse hata mesajı hazırla
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords]) # ` ile çevrele
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{escape_markdown_v2(keyword)}`\\.\nİzin verilenler: {allowed_str}"
                 print(f"Geçersiz özet anahtar kelimesi: {keyword}")
            else:
                # Geçerli keyword veya keyword yoksa özeti oluştur
                print(f">>> /ozet için anahtar kelime: {keyword if keyword else 'Yok (Tümü)'}")
                response_message = generate_summary(keyword)

        elif text.startswith("/analiz"): # Mevcut /analiz komutu
            print(">>> /analiz komutu işleniyor...")
            tickers_input = text[8:].strip() # "/analiz " kısmını atla (8 karakter)
            tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
            if not tickers:
                response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\\. Örnek: `/analiz AAPL,MSFT,AMD`"
            else:
                print(f"Analiz istenen hisseler (analiz.json): {tickers}")
                response_message = generate_analiz_response(tickers)

        elif text.startswith("/bist_analiz"): # YENİ /bist_analiz komutu
            print(">>> /bist_analiz komutu işleniyor...")
            tickers_input = text[13:].strip() # "/bist_analiz " kısmını atla (13 karakter)
            tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
            if not tickers:
                response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\\. Örnek: `/bist_analiz MIATK,THYAO`"
            else:
                print(f"Detaylı analiz istenen hisseler (analiz_sonuclari.json): {tickers}")
                # Yeni fonksiyonu çağır
                response_message = generate_bist_analiz_response(tickers)

        elif text.startswith("/temizle"): # Manuel temizlik komutu (dikkatli kullanın!)
            print(">>> /temizle komutu işleniyor (Manuel)...")
            # Belki ek bir onay veya yetkilendirme mekanizması eklenebilir
            clear_signals()
            response_message = f"✅ `{escape_markdown_v2(SIGNALS_FILE)}` dosyası manuel olarak temizlendi\\."

        # Başka komutlar buraya eklenebilir (elif ...)

        else:
            # Bilinmeyen komut veya metin için yanıt (isteğe bağlı)
            print(f"Bilinmeyen komut veya metin: '{text}'")
            # response_message = "❓ Anlamadım\\. Kullanılabilir komutlar:\n`/ozet [bist/nasdaq/...]`\n`/analiz HISSE1,HISSE2`\n`/bist_analiz HISSE1,HISSE2`"
            pass # Bilinmeyen komutlara yanıt verme

        # Eğer bir yanıt mesajı oluşturulduysa gönder
        if response_message:
            send_telegram_message(response_message)
        else:
             print("İşlenecek komut bulunamadı veya yanıt oluşturulmadı.")


    except Exception as e:
        print(f"❌ /telegram endpoint komut işleme hatası: {e}")
        print(f"❌ Hata Tipi: {type(e)}")
        # Hata durumunda kullanıcıya bilgi ver
        try:
            error_text = f"Komut işlenirken bir hata oluştu: `{escape_markdown_v2(str(e))}`"
            send_telegram_message(f"⚙️ *HATA* ⚙️\n{error_text}")
        except Exception as telegram_err:
            print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")

    return "ok", 200


@app.route("/clear_signals", methods=["POST"]) # Dışarıdan tetikleme için (güvenlik önemli!)
def clear_signals_endpoint():
    """signals.json dosyasını temizlemek için HTTP endpoint'i."""
    # Güvenlik Notu: Bu endpoint'i production'da korumasız bırakmayın!
    # IP kısıtlaması, secret token vb. kullanın.
    print(f"[{datetime.now()}] >>> /clear_signals endpoint tetiklendi (HTTP POST)")
    # Örnek Güvenlik: Basit bir token kontrolü
    # expected_token = os.getenv("CLEAR_TOKEN")
    # received_token = request.headers.get("Authorization")
    # if not expected_token or received_token != f"Bearer {expected_token}":
    #     print("❌ Yetkisiz temizleme isteği!")
    #     return "Unauthorized", 401

    try:
        clear_signals()
        send_telegram_message(f"📁 `{escape_markdown_v2(SIGNALS_FILE)}` dosyası HTTP isteği ile temizlendi\\.")
        return f"{SIGNALS_FILE} dosyası temizlendi!", 200
    except Exception as e:
        print(f"❌ Manuel sinyal temizleme hatası (HTTP): {e}")
        send_telegram_message(f"❌ `{escape_markdown_v2(SIGNALS_FILE)}` temizlenirken hata oluştu \\(HTTP\\): `{escape_markdown_v2(str(e))}`")
        return str(e), 500


# --- Analiz ve Özet Fonksiyonları ---

def generate_analiz_response(tickers):
    """analiz.json dosyasından veri çekerek basit analiz yanıtı oluşturur."""
    analiz_verileri = load_json_file(ANALIZ_FILE)
    analiz_listesi = []

    if not analiz_verileri:
         return f"⚠️ Analiz verileri \\(`{escape_markdown_v2(ANALIZ_FILE)}`\\) yüklenemedi veya boş\\."

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        analiz = analiz_verileri.get(ticker_upper)
        if analiz:
            puan = analiz.get("puan", 0)
            detaylar_list = analiz.get("detaylar")
            detaylar_str = "\n".join([f"- {escape_markdown_v2(d)}" for d in detaylar_list]) if isinstance(detaylar_list, list) else "_Detay bulunamadı_"
            yorum = escape_markdown_v2(analiz.get("yorum", "_Yorum bulunamadı_"))

            analiz_listesi.append({
                "ticker": escape_markdown_v2(ticker_upper),
                "puan": puan, # Sayısal kalsın, sıralama için
                "puan_str": escape_markdown_v2(str(puan)), # Gösterim için string
                "detaylar": detaylar_str,
                "yorum": yorum
            })
        else:
            analiz_listesi.append({
                "ticker": escape_markdown_v2(ticker_upper),
                "puan": None,
                "puan_str": "N/A",
                "detaylar": None,
                "yorum": f"❌ `{escape_markdown_v2(ticker_upper)}` için analiz bulunamadı \\(`{escape_markdown_v2(ANALIZ_FILE)}`\\)\\."
            })

    # Puana göre sırala (None olanlar sona)
    analiz_listesi.sort(key=lambda x: (x["puan"] is not None, x["puan"]), reverse=True)

    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            # Mesaj oluştururken formatlama (*, `)
            response_lines.append(
                f"📊 *{analiz['ticker']}* Analiz \\(Puan: `{analiz['puan_str']}`\\):\n"
                f"_{analiz['detaylar']}_\n\n" # Detayları italik yap
                f"*{analiz['yorum']}*" # Yorumu kalın yap
            )
        else:
            response_lines.append(analiz["yorum"]) # Zaten formatlanmış hata mesajı

    return "\n\n---\n\n".join(response_lines) # Hisseler arasına ayırıcı ekle


def generate_bist_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz_sonuclari.json'dan veri çeker,
    emoji ekler, .0'ı kaldırır ve formatlar.
    """
    all_analiz_data = load_json_file(ANALIZ_SONUCLARI_FILE)
    response_lines = []

    if not all_analiz_data:
         return f"⚠️ Detaylı analiz verileri \\(`{escape_markdown_v2(ANALIZ_SONUCLARI_FILE)}`\\) yüklenemedi veya boş\\."

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        # JSON anahtarlarının büyük harf olduğunu varsayıyoruz
        analiz_data = all_analiz_data.get(ticker_upper)

        if analiz_data:
            # Verileri al ve kaçır (escape)
            symbol = escape_markdown_v2(analiz_data.get("symbol", ticker_upper))
            score_raw = analiz_data.get("score", "N/A") # Ham skoru al
            classification = escape_markdown_v2(analiz_data.get("classification", "Belirtilmemiş"))
            comments_raw = analiz_data.get("comments", []) # Ham yorum listesi

            # --- PUAN FORMATLAMA (.0 kaldırma) ---
            display_score = escape_markdown_v2(score_raw) # Varsayılan olarak ham değeri kullan (kaçırılmış)
            try:
                # Sayısal olup olmadığını kontrol et
                score_float = float(score_raw)
                # Tam sayı ise .0 olmadan göster
                if score_float.is_integer():
                    display_score = str(int(score_float))
                else:
                    # Ondalıklı ise olduğu gibi (veya yuvarlayarak) göster
                    display_score = str(score_float) # str() ile kaçırmaya gerek yok, zaten sayı
                # Sayısal değerleri tekrar kaçırmaya gerek yok (özel karakter içermezler)
            except (ValueError, TypeError):
                # Sayı değilse (örn. "N/A"), zaten başta kaçırılmıştı
                pass
            # --- PUAN FORMATLAMA SONU ---

            # Yorumları formatla (başına emoji ve kaçırma)
            formatted_comments = "\n".join(
                [f"🔹 {escape_markdown_v2(comment)}" for comment in comments_raw if comment] # Boş yorumları atla
            )
            if not formatted_comments:
                formatted_comments = "_Yorum bulunamadı_" # Yorum yoksa belirt (italik)

            # MarkdownV2 formatında mesaj oluştur (emoji ve formatlama ile)
            response_lines.append(
                f"📊 *{symbol}* Detaylı Analiz:\n\n"
                f"📈 *Puan:* `{display_score}`\n"  # Puanı `code` formatında göster
                f"🏅 *Sınıflandırma:* {classification}\n\n"
                f"📝 *Öne Çıkanlar:*\n{formatted_comments}"
            )
        else:
            # Hisse bulunamadı mesajı (kaçırılmış ticker ile)
            response_lines.append(f"❌ `{escape_markdown_v2(ticker_upper)}` için detaylı analiz bulunamadı \\(`{escape_markdown_v2(ANALIZ_SONUCLARI_FILE)}`\\)\\.")

    # Farklı hisselerin sonuçlarını ayırıcı ile birleştir
    return "\n\n---\n\n".join(response_lines)


def generate_summary(keyword=None):
    """signals.json dosyasını okuyarak sinyal özeti oluşturur."""
    if not os.path.exists(SIGNALS_FILE):
        return "📊 Henüz hiç sinyal kaydedilmedi\\."

    lines = []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except IOError as e:
        print(f"❌ Sinyal dosyası okunamadı ({SIGNALS_FILE}): {e}")
        return f"⚠️ Sinyal dosyası \\(`{escape_markdown_v2(SIGNALS_FILE)}`\\) okunurken bir hata oluştu: `{escape_markdown_v2(str(e))}`"

    if not lines:
        return "📊 Sinyal dosyasında kayıtlı veri bulunamadı\\."

    # Kategoriler (set kullanarak tekrarları önle)
    summary = {
        "güçlü": set(),         # KAIRI ve Alış eşleşmesi
        "kairi_-30": set(),     # KAIRI <= -30
        "kairi_-20": set(),     # -30 < KAIRI <= -20
        "matisay_-25": set(),   # Matisay < -25
        "mükemmel_alış": set(),
        "alış_sayımı": set(),
        "mükemmel_satış": set(),
        "satış_sayımı": set(),
    }

    parsed_signals = [parse_signal_line(line) for line in lines if line.strip()]
    parsed_signals = [s for s in parsed_signals if s] # None olanları (parse hatası) filtrele

    # Anahtar kelimeye göre filtreleme (Borsa bazında)
    keyword_map = {
        "bist": "bist_dly",
        "nasdaq": "bats",
        "binance": "binance" # Binance exchange adı 'binance' ise
    }
    active_filter = None
    if keyword:
        keyword_lower = keyword.lower()
        # Hem doğrudan eşleşme hem de map üzerinden eşleşme kontrolü
        active_filter = keyword_map.get(keyword_lower, keyword_lower)
        print(f"Özet filtreleniyor: Exchange '{active_filter}' içerenler")
        filtered_signals = []
        for s in parsed_signals:
            exchange_lower = s.get("exchange", "").lower()
            if active_filter in exchange_lower:
                 filtered_signals.append(s)
        parsed_signals = filtered_signals # Filtrelenmiş liste ile devam et
        if not parsed_signals:
             return f"📊 `{escape_markdown_v2(keyword)}` filtresi için sinyal bulunamadı\\."

    print(f"Özet için işlenecek sinyal sayısı: {len(parsed_signals)}")

    # Sinyalleri işle ve kategorize et
    processed_symbols_for_strong = set() # Güçlü eşleşme için işlem gören sembolleri takip et

    for signal_data in parsed_signals:
        symbol = signal_data.get("symbol", "Bilinmiyor")
        exchange = signal_data.get("exchange", "Bilinmiyor")
        signal_text = signal_data.get("signal", "")
        # Borsa adını güzelleştir
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        # Anahtar formatı: SEMBOL (Borsa) - Kaçırmayı sonra yap
        base_key = f"{symbol} ({exchange_display})"
        escaped_key = escape_markdown_v2(base_key) # Mesajda kullanılacak kaçırılmış anahtar

        signal_lower = signal_text.lower() # Küçük harfe çevirerek kontrol yap

        # KAIRI Sinyalleri
        if "kairi" in signal_lower:
            kairi_match = re.search(r"kairi\s*([-+]?\d*\.?\d+)", signal_lower)
            if kairi_match:
                try:
                    kairi_value = round(float(kairi_match.group(1)), 2)
                    kairi_entry = f"{escaped_key}: KAIRI `{kairi_value}`" # Değeri `code` yap
                    if kairi_value <= -30:
                        summary["kairi_-30"].add(kairi_entry)
                    elif kairi_value <= -20:
                        summary["kairi_-20"].add(kairi_entry)

                    # Güçlü eşleşme kontrolü (Aynı sembol/borsa için Alış Sinyali var mı?)
                    if base_key not in processed_symbols_for_strong:
                        for other in parsed_signals:
                            if (other.get("symbol") == symbol and
                                other.get("exchange") == exchange and
                                re.search(r"(mükemmel alış|alış sayımı)", other.get("signal", "").lower())):
                                strong_entry = f"✅ {escaped_key} \\- KAIRI: `{kairi_value}` & Alış Sinyali"
                                summary["güçlü"].add(strong_entry)
                                processed_symbols_for_strong.add(base_key) # Bu sembol için güçlü eşleşme bulundu
                                break # Bir eşleşme yeterli
                except ValueError:
                    print(f"⚠️ KAIRI değeri ayrıştırılamadı: {signal_text}")
                except Exception as e:
                     print(f"KAIRI işlenirken hata: {e} - Sinyal: {signal_text}")

        # Matisay Sinyalleri
        elif "matisay" in signal_lower:
            matisay_match = re.search(r"matisay\s*([-+]?\d*\.?\d+)", signal_lower)
            if matisay_match:
                try:
                    matisay_value = round(float(matisay_match.group(1)), 2)
                    if matisay_value < -25: # -25'ten KÜÇÜK olanlar
                        matisay_entry = f"{escaped_key}: Matisay `{matisay_value}`"
                        summary["matisay_-25"].add(matisay_entry)
                except ValueError:
                    print(f"⚠️ Matisay değeri ayrıştırılamadı: {signal_text}")
                except Exception as e:
                     print(f"Matisay işlenirken hata: {e} - Sinyal: {signal_text}")

        # Diğer Sinyal Türleri (KAIRI veya Matisay değilse)
        elif re.search(r"mükemmel alış", signal_lower):
             summary["mükemmel_alış"].add(escaped_key)
             # Güçlü eşleşme kontrolü (KAIRI var mı diye ters kontrol)
             if base_key not in processed_symbols_for_strong:
                 for other in parsed_signals:
                     if (other.get("symbol") == symbol and
                         other.get("exchange") == exchange and
                         "kairi" in other.get("signal", "").lower()):
                         kairi_match_rev = re.search(r"kairi\s*([-+]?\d*\.?\d+)", other.get("signal", "").lower())
                         if kairi_match_rev:
                            kairi_val_rev = round(float(kairi_match_rev.group(1)), 2)
                            if kairi_val_rev <= -20: # KAIRI <= -20 ise güçlü say
                                strong_entry = f"✅ {escaped_key} \\- Alış Sinyali & KAIRI: `{kairi_val_rev}`"
                                summary["güçlü"].add(strong_entry)
                                processed_symbols_for_strong.add(base_key)
                                break # Eşleşme bulundu
        elif re.search(r"alış sayımı", signal_lower):
            summary["alış_sayımı"].add(escaped_key)
            # Güçlü eşleşme kontrolü (KAIRI var mı diye ters kontrol)
            if base_key not in processed_symbols_for_strong:
                for other in parsed_signals:
                    if (other.get("symbol") == symbol and
                        other.get("exchange") == exchange and
                        "kairi" in other.get("signal", "").lower()):
                        kairi_match_rev = re.search(r"kairi\s*([-+]?\d*\.?\d+)", other.get("signal", "").lower())
                        if kairi_match_rev:
                           kairi_val_rev = round(float(kairi_match_rev.group(1)), 2)
                           if kairi_val_rev <= -20: # KAIRI <= -20 ise güçlü say
                               strong_entry = f"✅ {escaped_key} \\- Alış Sayımı & KAIRI: `{kairi_val_rev}`"
                               summary["güçlü"].add(strong_entry)
                               processed_symbols_for_strong.add(base_key)
                               break # Eşleşme bulundu
        elif re.search(r"mükemmel satış", signal_lower):
            summary["mükemmel_satış"].add(escaped_key)
        elif re.search(r"satış sayımı", signal_lower):
            summary["satış_sayımı"].add(escaped_key)


    # Özeti oluştur (Başlıklar kalın)
    msg_parts = []
    filter_title = f" (`{escape_markdown_v2(keyword)}` Filtresi)" if keyword else ""
    summary_title = f"📊 *Sinyal Özeti*{escape_markdown_v2(filter_title)}"
    msg_parts.append(summary_title)

    # Her kategori için başlık ve listeyi ekle (eğer boş değilse)
    category_map = {
        "güçlü": "✅ *GÜÇLÜ EŞLEŞENLER (Alış & KAIRI ≤ -20)*",
        "kairi_-30": "🔴 *KAIRI ≤ -30*",
        "kairi_-20": "🟠 *-30 < KAIRI ≤ -20*",
        "matisay_-25": "🟣 *Matisay < -25*",
        "mükemmel_alış": "🟢 *Mükemmel Alış*",
        "alış_sayımı": "📈 *Alış Sayımı Tamamlananlar*",
        "mükemmel_satış": "🔵 *Mükemmel Satış*",
        "satış_sayımı": "📉 *Satış Sayımı Tamamlananlar*"
    }

    has_content = False
    for key, title in category_map.items():
        if summary[key]:
            has_content = True
            # Set'i sıralı listeye çevir ve birleştir
            sorted_items = sorted(list(summary[key]))
            msg_parts.append(f"{title}:\n" + "\n".join(f"- {item}" for item in sorted_items))

    # Eğer hiçbir kategori dolu değilse, uygun bir mesaj döndür
    if not has_content:
        filter_text = f" `{escape_markdown_v2(keyword)}` filtresi ile" if keyword else ""
        return f"📊 Gösterilecek uygun sinyal bulunamadı{escape_markdown_v2(filter_text)}\\."

    # Bölümleri birleştir
    final_summary = "\n\n".join(msg_parts)
    print("Oluşturulan Özet Başlangıcı:", final_summary[:300] + "...") # Özetin başını logla
    return final_summary


# --- Arka Plan Görevleri ---

def clear_signals():
    """signals.json dosyasının içeriğini güvenli bir şekilde temizler."""
    try:
        if os.path.exists(SIGNALS_FILE):
            # Dosyayı 'write' modunda açmak içeriği siler
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                f.write("") # Dosyayı boşalt
            print(f"✅ {SIGNALS_FILE} dosyası başarıyla temizlendi!")
        else:
            print(f"ℹ️ {SIGNALS_FILE} dosyası bulunamadı, temizleme işlemi atlandı.")
            # Opsiyonel: Dosya yoksa oluştur
            # with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            #     f.write("")
            # print(f"ℹ️ {SIGNALS_FILE} dosyası bulunamadı, boş olarak oluşturuldu.")
    except IOError as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken G/Ç hatası: {e}")
        # Hata durumunda Telegram'a bildirim gönderilebilir
        send_telegram_message(f"⚠️ *Otomatik Temizlik Hatası:* `{escape_markdown_v2(SIGNALS_FILE)}` temizlenemedi \\- G/Ç Hatası: `{escape_markdown_v2(str(e))}`")
    except Exception as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken beklenmedik hata: {e}")
        send_telegram_message(f"⚠️ *Otomatik Temizlik Hatası (Genel):* `{escape_markdown_v2(SIGNALS_FILE)}` temizlenemedi \\- Hata: `{escape_markdown_v2(str(e))}`")


def clear_signals_daily():
    """Her gün belirli bir saatte (örn. 23:59 TR saati) signals.json dosyasını temizler."""
    print("🕒 Günlük sinyal temizleme görevi başlatılıyor...")
    already_cleared_today = False
    target_hour = 23 # Temizlik saati (24 saat formatında)
    target_minute = 59 # Temizlik dakikası
    check_interval_seconds = 30 # Kontrol sıklığı (saniye)

    while True:
        try:
            # Türkiye saat dilimini kullan
            tz_istanbul = pytz.timezone("Europe/Istanbul")
            now = datetime.now(tz_istanbul)

            # Hedeflenen zaman mı kontrol et
            if now.hour == target_hour and now.minute == target_minute:
                if not already_cleared_today:
                    print(f"⏰ Zamanı geldi ({now.strftime('%Y-%m-%d %H:%M:%S %Z')}), {SIGNALS_FILE} temizleniyor...")
                    clear_signals()
                    # Telegram'a bildirim gönder
                    try:
                         timestamp_str = now.strftime('%Y\\-%m\\-%d %H:%M') # Yıl-Ay-Gün Saat:Dakika
                         send_telegram_message(f"🧹 Günlük otomatik temizlik yapıldı \\({timestamp_str}\\)\\. `{escape_markdown_v2(SIGNALS_FILE)}` sıfırlandı\\.")
                    except Exception as tel_err:
                         print(f"❌ Temizlik bildirimi gönderilemedi: {tel_err}")

                    already_cleared_today = True # Bugün için temizlendi olarak işaretle
                    # Bir sonraki kontrol için hedef zamanı geçene kadar bekle (örn. 65 sn)
                    print(f"Temizlik yapıldı. Bir sonraki kontrol {check_interval_seconds*2+5} saniye sonra.")
                    time.sleep(check_interval_seconds * 2 + 5) # 23:59:xx -> 00:00:xx geçişi için
                    continue # Döngünün başına dön ve bayrağı kontrol et
            else:
                # Eğer hedef saat/dakika değilse ve bayrak True ise, yeni güne geçilmiştir, bayrağı sıfırla
                if already_cleared_today:
                     print("Yeni güne geçildi veya hedef zaman aşıldı, 'already_cleared_today' bayrağı sıfırlandı.")
                     already_cleared_today = False

            # Bir sonraki kontrol için bekle
            time.sleep(check_interval_seconds)

        except pytz.UnknownTimeZoneError:
            print("❌ Hata: 'Europe/Istanbul' saat dilimi bulunamadı. Sistem saat dilimi kullanılacak.")
            # tz_istanbul olmadan devam etmeyi dene (sistem saatine göre çalışır)
            time.sleep(check_interval_seconds) # Hata durumunda da beklemeye devam et
        except Exception as e:
            print(f"❌ clear_signals_daily döngüsünde hata: {e}")
            print(f"❌ Hata Tipi: {type(e)}")
            # Hata durumunda biraz daha uzun bekle ve Telegram'a bildirim gönder
            try:
                send_telegram_message(f"⚠️ *Kritik Hata:* Günlük temizlik görevinde sorun oluştu\\! Hata: `{escape_markdown_v2(str(e))}`")
            except Exception as tel_err:
                print(f"❌ Kritik hata bildirimi gönderilemedi: {tel_err}")
            time.sleep(60)


# --- Uygulama Başlatma ---

if __name__ == "__main__":
    # Gerekli ortam değişkenlerini kontrol et
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ HATA: BOT_TOKEN veya CHAT_ID ortam değişkenleri ayarlanmamış!")
        print("Lütfen .env dosyasını kontrol edin veya değişkenleri ayarlayın.")
        exit(1) # Değişkenler yoksa uygulamayı başlatma

    print("-" * 30)
    print("🚀 Flask Uygulaması Başlatılıyor...")
    print(f"🔧 Bot Token: ...{BOT_TOKEN[-6:]}") # Token'ın sonunu göster
    print(f"🔧 Chat ID: {CHAT_ID}")
    print(f"🔧 Sinyal Dosyası: {SIGNALS_FILE}")
    print(f"🔧 Analiz Dosyası (Basit): {ANALIZ_FILE}")
    print(f"🔧 Analiz Dosyası (Detaylı): {ANALIZ_SONUCLARI_FILE}")
    print("-" * 30)

    # Arka plan temizlik görevini başlat
    # daemon=True ana program bittiğinde thread'in de bitmesini sağlar
    daily_clear_thread = threading.Thread(target=clear_signals_daily, daemon=True)
    daily_clear_thread.start()

    # Flask uygulamasını çalıştır
    # Production için debug=False kullanılmalı.
    # host='0.0.0.0' tüm ağ arayüzlerinden erişime izin verir.
    # Gunicorn gibi bir WSGI sunucusu ile çalıştırmak daha iyidir.
    # Örnek: gunicorn --bind 0.0.0.0:5000 your_app_file:app
    try:
        # Geliştirme için: app.run(host="0.0.0.0", port=5000, debug=True)
        # Production (veya debug istemiyorsanız):
        app.run(host="0.0.0.0", port=5000, debug=False)
    except Exception as run_err:
         print(f"❌ Flask uygulaması başlatılırken hata: {run_err}")
