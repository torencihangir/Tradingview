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
import traceback # Hata ayıklama için eklendi

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")

# --- Diğer Fonksiyonlar (escape_markdown_v2, send_telegram_message, receive_signal, parse_signal_line, load_json_file, load_analiz_json, load_bist_analiz_json, generate_analiz_response, telegram_webhook, generate_summary, clear_signals_endpoint, clear_signals, clear_signals_daily) ---
# BU KISIMLAR ÖNCEKİ KOD İLE AYNI, BURAYA TEKRAR KOPYALANMADI.
# Sadece generate_bist_analiz_response fonksiyonunu değiştiriyoruz.

def escape_markdown_v2(text):
    """
    Telegram MarkdownV2 için özel karakterleri kaçırır.
    """
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def send_telegram_message(message):
    """Telegram'a mesaj gönderir, MarkdownV2 kaçırma işlemi yapar ve uzun mesajları böler."""
    escaped_message = escape_markdown_v2(message)
    max_length = 4096
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            r = requests.post(url, json=data, timeout=20)
            r.raise_for_status()
            print(f"✅ Telegram yanıtı: {r.status_code}")
        except requests.exceptions.Timeout:
            print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {r.text}")
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+max_length]}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi (RequestException): {e}")
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+max_length]}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+max_length]}")

# Diğer endpointler ve fonksiyonlar buradaydı...

def load_json_file(filepath):
    """Genel JSON dosyası yükleme fonksiyonu."""
    try:
        if not os.path.exists(filepath):
             print(f"Uyarı: {filepath} dosyası bulunamadı.")
             return None
        if os.path.getsize(filepath) == 0:
            print(f"Uyarı: {filepath} dosyası boş.")
            return {}
        with open(filepath, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Uyarı: {filepath} dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ Hata: {filepath} dosyası geçerli bir JSON formatında değil. Hata: {e}")
        try:
             with open(filepath, "r", encoding="utf-8") as f_err:
                 print(f"Dosyanın başı: {f_err.read(100)}...")
        except Exception:
             pass
        return {}
    except IOError as e:
        print(f"❌ G/Ç Hatası ({filepath} okuma): {e}")
        return {}
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filepath} okuma): {e}")
        return {}

def load_bist_analiz_json():
    data = load_json_file(ANALIZ_SONUCLARI_FILE)
    return data if data is not None else {}

# --- /bist_analiz için Güncellenmiş Fonksiyon ---
def generate_bist_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz_sonuclari.json'dan veri çeker.
    'Öne Çıkanlar' listesindeki her madde için içeriğe göre farklı emoji kullanır.
    """
    all_analiz_data = load_bist_analiz_json()
    response_lines = []

    if not all_analiz_data:
         return f"⚠️ Detaylı analiz verileri (`{os.path.basename(ANALIZ_SONUCLARI_FILE)}`) yüklenemedi veya boş."

    # Anahtar kelimelere göre emoji eşleştirme (daha spesifik olanlar önce gelmeli)
    # Bu listeyi kendi metriklerinize ve istediğiniz emojilere göre düzenleyebilirsiniz.
    emoji_map = {
        "peg oranı": "🎯",
        "f/k oranı": "💰",
        "net borç/favök": "🏦",
        "net dönem karı": "📈", # Artış/Azalışa göre emoji değişebilir (daha karmaşık)
        "finansal borç": "📉",  # Genellikle azalışı istenir
        "net borç": "💸",      # Artış/Azalışa göre emoji değişebilir
        "dönen varlıklar": "🔄",
        "duran varlıklar": "🏢",
        "toplam varlıklar": "🏛️",
        "özkaynak": "🧱",
        # Eklenebilecek diğer metrikler...
        "default": "➡️" # Eşleşme bulunamazsa kullanılacak varsayılan emoji
    }

    for ticker in tickers:
        analiz_data = all_analiz_data.get(ticker.strip().upper())

        if analiz_data:
            symbol = analiz_data.get("symbol", ticker.strip().upper())
            score = analiz_data.get("score", "N/A")
            classification = analiz_data.get("classification", "Belirtilmemiş")
            comments = analiz_data.get("comments", [])

            formatted_comments_list = []
            if comments and isinstance(comments, list):
                for comment in comments:
                    comment_lower = comment.lower() # Küçük harfe çevirerek kontrol
                    chosen_emoji = emoji_map["default"] # Varsayılan emoji ile başla

                    # Eşleşme bulmak için anahtar kelimeleri kontrol et
                    # Not: Bu basit bir kontrol. Daha karmaşık metinler için regex gerekebilir.
                    # Önem sırasına göre veya en spesifik eşleşmeyi bulacak şekilde kontrol edilebilir.
                    found_match = False
                    for keyword, emoji in emoji_map.items():
                        if keyword == "default": continue # Default anahtar kelimesini atla

                        # Anahtar kelimenin yorum içinde geçip geçmediğini kontrol et
                        # Daha sağlam olması için kelime sınırları (\b) ile regex kullanılabilir:
                        # if re.search(r'\b' + re.escape(keyword) + r'\b', comment_lower):
                        # Şimdilik basit 'in' kontrolü yapalım:
                        if keyword in comment_lower:
                            chosen_emoji = emoji
                            found_match = True
                            break # İlk eşleşmeyi bulduğumuzda döngüden çık (veya en iyi eşleşmeyi ara)

                    formatted_comments_list.append(f"{chosen_emoji} {comment}") # Seçilen emoji + orijinal yorum

                formatted_comments = "\n".join(formatted_comments_list)
            else:
                formatted_comments = "Yorum bulunamadı."

            # Mesajı oluştur
            response_lines.append(
                f"📊 BİST Detaylı Analiz\n\n"
                f"🏷️ Sembol: {symbol}\n"
                f"📈 Puan: {score}\n"
                f"🏅 Sınıflandırma: {classification}\n\n"
                f"📝 Öne Çıkanlar:\n{formatted_comments}" # Dinamik emojili yorumlar
            )
        else:
            response_lines.append(f"❌ {ticker.strip().upper()} için detaylı analiz bulunamadı.")

    return "\n\n".join(response_lines)

# --- Telegram Webhook (Değişiklik Yok) ---
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    try:
        update = request.json
        if not update:
            print("Boş JSON verisi alındı.")
            return "ok", 200

        message = update.get("message") or update.get("edited_message")
        if not message:
            # Desteklenmeyen güncellemeleri logla ve atla
            update_type = next((key for key in update if key != 'update_id'), 'bilinmiyor')
            print(f"Desteklenmeyen güncelleme türü '{update_type}' alındı, işlenmiyor.")
            return "ok", 200

        text = message.get("text", "").strip()
        chat_info = message.get("chat")
        user_info = message.get("from")

        if not chat_info or not user_info:
             print("❌ Sohbet veya kullanıcı bilgisi eksik, mesaj işlenemiyor.")
             return "ok", 200

        chat_id = chat_info.get("id")
        user_id = user_info.get("id")
        first_name = user_info.get("first_name", "")
        username = user_info.get("username", "N/A")

        if str(chat_id) != CHAT_ID:
            print(f"⚠️ Uyarı: Mesaj beklenen sohbetten ({CHAT_ID}) gelmedi. Gelen: {chat_id}. İşlenmeyecek.")
            return "ok", 200

        if not text:
            print("Boş mesaj içeriği alındı.")
            return "ok", 200

        print(f">>> Mesaj alındı (Chat: {chat_id}, User: {first_name} [{username}/{user_id}]): {text}")

        response_message = ""
        # Komut işleme mantığı (Önceki kod ile aynı)
        if text.startswith("/ozet"):
            print(">>> /ozet komutu işleniyor...")
            parts = text.split(maxsplit=1)
            keyword = parts[1].lower() if len(parts) > 1 else None
            allowed_keywords = ["bats", "nasdaq", "bist_dly", "binance", "bist"]
            print(f"Anahtar kelime: {keyword}")
            if keyword and keyword not in allowed_keywords:
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords])
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{keyword}`. İzin verilenler: {allowed_str}"
                 print(f"Geçersiz özet anahtar kelimesi: {keyword}")
            else:
                 # generate_summary fonksiyonu çağrılır (önceki kodda tanımlı)
                 summary = generate_summary(keyword) # Bu fonksiyonun var olduğunu varsayıyoruz
                 response_message = summary
        elif text.startswith("/analiz"):
            print(">>> /analiz komutu işleniyor...")
            tickers_input = text[len("/analiz"):].strip()
            if not tickers_input:
                 response_message = "Lütfen bir veya daha fazla hisse kodu belirtin. Örnek: `/analiz AAPL, MSFT, AMD`"
            else:
                tickers = [ticker.strip().upper() for ticker in re.split(r'[,\s]+', tickers_input) if ticker.strip()]
                if not tickers:
                     response_message = "Geçerli bir hisse kodu bulunamadı. Örnek: `/analiz AAPL, MSFT`"
                else:
                    print(f"Analiz istenen hisseler (/analiz): {tickers}")
                    # generate_analiz_response fonksiyonu çağrılır (önceki kodda tanımlı)
                    response_message = generate_analiz_response(tickers) # Bu fonksiyonun var olduğunu varsayıyoruz
        elif text.startswith("/bist_analiz"): # GÜNCELLENMİŞ FONKSİYONU KULLANIR
            print(">>> /bist_analiz komutu işleniyor...")
            tickers_input = text[len("/bist_analiz"):].strip()
            if not tickers_input:
                response_message = "Lütfen bir veya daha fazla BIST hisse kodu belirtin. Örnek: `/bist_analiz MIATK, THYAO`"
            else:
                tickers = [ticker.strip().upper() for ticker in re.split(r'[,\s]+', tickers_input) if ticker.strip()]
                if not tickers:
                     response_message = "Geçerli bir hisse kodu bulunamadı. Örnek: `/bist_analiz MIATK, THYAO`"
                else:
                    print(f"Detaylı analiz istenen hisseler (/bist_analiz): {tickers}")
                    response_message = generate_bist_analiz_response(tickers) # YENİ GÜNCELLENMİŞ FONKSİYON
        elif text.startswith("/start") or text.startswith("/help"):
             print(">>> /start veya /help komutu işleniyor...")
             response_message = "👋 Merhaba! Kullanabileceğiniz komutlar:\n\n" \
                                "• `/ozet` : Tüm borsalardan gelen sinyallerin özetini gösterir.\n" \
                                "• `/ozet [borsa]` : Belirli bir borsa için özet gösterir (Örn: `/ozet bist`, `/ozet nasdaq`).\n" \
                                "• `/analiz [HİSSE1,HİSSE2,...]` : Belirtilen hisseler için temel analiz puanını ve yorumunu gösterir (Örn: `/analiz GOOGL,AAPL`).\n" \
                                "• `/bist_analiz [HİSSE1,HİSSE2,...]` : Belirtilen BIST hisseleri için daha detaylı analizi gösterir (Örn: `/bist_analiz EREGL, TUPRS`).\n" \
                                "• `/help` : Bu yardım mesajını gösterir."
        else:
            print(f"Bilinmeyen komut veya metin alındı: {text}")
            # response_message = f"❓ `{text}` komutunu anlayamadım. Yardım için `/help` yazabilirsiniz."

        if response_message:
             send_telegram_message(response_message)
        else:
             print("İşlenecek bilinen bir komut bulunamadı, yanıt gönderilmedi.")

        return "ok", 200

    except Exception as e:
        print(f"❌ /telegram endpoint genel hatası: {e}")
        print(traceback.format_exc())
        try:
             error_message = f"🤖 Üzgünüm, isteğinizi işlerken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
             if 'chat_id' in locals() and str(chat_id) == CHAT_ID:
                 send_telegram_message(error_message)
             else:
                 print("Hata oluştu ancak hedef sohbet ID'si belirlenemedi veya yetkisiz.")
        except Exception as telegram_err:
             print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return "Internal Server Error", 500


# --- Uygulama Başlangıcı ve Diğer Fonksiyonlar ---
# generate_summary, clear_signals_endpoint, clear_signals, clear_signals_daily, __main__ bloğu
# önceki kod ile aynı kabul edildi ve buraya eklenmedi.
# KODUN TAMAMINI ÇALIŞTIRMAK İÇİN BU KISIMLARI ÖNCEKİ VERSİYONDAN ALIP
# generate_bist_analiz_response fonksiyonunu bu dosyadaki ile değiştirin.

if __name__ == "__main__":
    print("🚀 Flask uygulaması başlatılıyor...")
    # Eksik fonksiyonları varsayılan olarak ekleyelim (gerçek kodda bunlar olmalı)
    def generate_summary(keyword=None): return "Özet oluşturuluyor..."
    def generate_analiz_response(tickers): return "Analiz oluşturuluyor..."
    def clear_signals(): print("Sinyaller temizleniyor..."); return True
    def clear_signals_daily(): print("Günlük temizlik döngüsü çalışıyor..."); time.sleep(3600) # Sadece göstermelik
    @app.route("/signal", methods=["POST"])
    def receive_signal(): return "ok", 200
    @app.route("/clear_signals", methods=["POST"])
    def clear_signals_endpoint(): clear_signals(); return "ok", 200

    # Arka plan temizlik görevini başlat (gerçek kodda bu olmalı)
    # cleanup_thread = threading.Thread(target=clear_signals_daily, daemon=True)
    # cleanup_thread.start()
    # print("✅ Günlük sinyal temizleme görevi arka planda başlatıldı.")

    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    print(f"🔧 Ayarlar: Port={port}, Debug={debug_mode}")
    print(f"🔧 Telegram Bot Token: {'Var' if BOT_TOKEN else 'Yok!'}, Chat ID: {'Var' if CHAT_ID else 'Yok!'}")
    if not BOT_TOKEN or not CHAT_ID: print("❌ UYARI: BOT_TOKEN veya CHAT_ID .env dosyasında ayarlanmamış!")

    app.run(host="0.0.0.0", port=port, debug=debug_mode)
