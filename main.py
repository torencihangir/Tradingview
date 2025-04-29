# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify # jsonify debug için eklendi
import json
import requests
import os
import time
import re
# import threading # Şimdilik kullanılmıyor, kaldırılabilir veya ileride gerekirse eklenebilir
from datetime import datetime
import pytz # Şimdilik kullanılmıyor
from dotenv import load_dotenv
import traceback # Hata ayıklama için

# Ortam değişkenlerini yükle
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Kullanıcıya yanıt vermek için dinamik chat_id kullanılacak.
# Bu ID'yi yöneticiye özel bildirimler (örn. hatalar) için kullanabiliriz.
ADMIN_CHAT_ID = os.getenv("CHAT_ID")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
BIST_ANALIZ_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")

app = Flask(__name__)

# --- Yardımcı Fonksiyonlar ---

def load_json_file(path):
    """Verilen yoldaki JSON dosyasını okur ve içeriğini döndürür."""
    try:
        if not os.path.exists(path):
            print(f"❌ Uyarı: JSON dosyası bulunamadı: {path}")
            return {}
        if os.path.getsize(path) == 0:
            print(f"❌ Uyarı: JSON dosyası boş: {path}")
            # Boş dosya geçerli bir JSON değildir, hata verelim.
            raise json.JSONDecodeError("Dosya boş", "", 0)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Yüklenen verinin bir sözlük olduğunu varsayıyoruz, kontrol edelim
            if not isinstance(data, dict):
                 print(f"❌ Uyarı: JSON dosyasının kökü bir sözlük değil: {path}")
                 raise ValueError("JSON root is not a dictionary")
            return data
    except json.JSONDecodeError as e:
        error_message = f"🚨 JSON Decode Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}"
        print(f"❌ JSON okuma/decode hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
            # Hatalı durumda admin'e bilgi verelim (send_telegram_message içinde tekrar göndermemek için kontrol)
            send_telegram_message(ADMIN_CHAT_ID, error_message, avoid_self_notify=True)
        return None # Hata durumunda None döndürerek kontrolü kolaylaştır
    except ValueError as e:
        error_message = f"🚨 JSON Format Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}"
        print(f"❌ JSON format hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, error_message, avoid_self_notify=True)
        return None
    except Exception as e:
        error_message = f"🚨 Genel JSON Yükleme Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}\n{traceback.format_exc()}"
        print(f"❌ Genel JSON yükleme hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, error_message, avoid_self_notify=True)
        return None

def send_telegram_message(chat_id, msg, parse_mode="Markdown", avoid_self_notify=False):
    """
    Verilen chat_id'ye Telegram mesajı gönderir.
    Mesaj çok uzunsa böler.
    avoid_self_notify: Admin'e gönderilen hata mesajlarında tekrar admin'e göndermeyi engeller.
    """
    if not BOT_TOKEN or not chat_id:
        print("🚨 Telegram gönderimi için BOT_TOKEN veya chat_id eksik!")
        return False # Gönderim başarısız

    # Mesajı string'e çevir (emin olmak için)
    msg = str(msg)

    max_length = 4096
    messages_to_send = []

    if len(msg) > max_length:
        # Öncelikli olarak çift yeni satıra göre böl
        parts = msg.split('\n\n')
        current_message = ""
        for part in parts:
            # Parçanın kendisi çok uzunsa, onu da böl
            if len(part) > max_length:
                # Mevcut mesajı gönder (eğer varsa)
                if current_message:
                    messages_to_send.append(current_message.strip())
                    current_message = ""
                # Uzun parçayı karakter bazında böl
                for i in range(0, len(part), max_length - 10): # Biraz pay bırakalım
                    messages_to_send.append(part[i:i + max_length - 10])
            # Mevcut mesaja ekle veya yeni mesaj başlat
            elif len(current_message) + len(part) + 2 <= max_length:
                current_message += part + "\n\n"
            else:
                # Mevcut mesaj doldu, gönder ve yeniye başla
                messages_to_send.append(current_message.strip())
                current_message = part + "\n\n"
        # Son kalan mesajı ekle
        if current_message:
            messages_to_send.append(current_message.strip())
    else:
        messages_to_send.append(msg)

    all_sent_successfully = True
    for message_part in messages_to_send:
         if not message_part.strip(): # Tamamen boş mesaj gönderme
             continue
         try:
             url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
             data = {
                 "chat_id": chat_id,
                 "text": message_part,
                 "parse_mode": parse_mode
             }
             r = requests.post(url, json=data, timeout=20) # Timeout'u biraz daha artır
             r.raise_for_status() # HTTP hatalarını kontrol et (4xx, 5xx)
             print(f"📤 Telegram'a gönderildi (Chat ID: {chat_id}): {r.status_code}")
             time.sleep(0.6) # Rate limiting için biraz daha bekleme
         except requests.exceptions.RequestException as e:
             all_sent_successfully = False
             print(f"🚨 Telegram gönderim hatası (Chat ID: {chat_id}): {e}")
             # Hata durumunda admin'e bilgi ver (eğer admin'e zaten göndermiyorsak)
             if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID) and not avoid_self_notify:
                 send_telegram_message(ADMIN_CHAT_ID, f"🚨 Kullanıcıya Mesaj Gönderilemedi!\nChat ID: {chat_id}\nHata: {e}", avoid_self_notify=True)
             # Eğer kullanıcıya gönderilemiyorsa, döngüden çıkabiliriz.
             break
         except Exception as e:
             all_sent_successfully = False
             print(f"🚨 Beklenmedik Telegram gönderim hatası (Chat ID: {chat_id}): {e}")
             if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID) and not avoid_self_notify:
                  send_telegram_message(ADMIN_CHAT_ID, f"🚨 Beklenmedik Hata (TG Gönderim)!\nChat ID: {chat_id}\nHata: {e}\n{traceback.format_exc()}", avoid_self_notify=True)
             break # Diğer parçaları göndermeyi durdur

    return all_sent_successfully

# --- Analiz İşleme Fonksiyonları ---

def format_analiz_output(ticker_data):
    """ABD borsası analiz verisini istenen formata getirir."""
    t = ticker_data.get("symbol", "Bilinmiyor") # Sembolü ekledik
    puan = ticker_data.get("puan", "N/A")
    detaylar = ticker_data.get("detaylar", [])

    # Anahtar bilgileri detaylar listesinden regex veya string arama ile çekmeye çalışalım
    # Bu, JSON yapısındaki olası tutarsızlıklara karşı daha dayanıklı olabilir.
    target_price_line = "🎯 Hedef Fiyat: Bilgi Yok"
    potential_line = "🚀 Potansiyel: Bilgi Yok"
    analyst_count_line = "👨‍💼 Analist Sayısı: Bilgi Yok"
    sector_line = "🏢 Sektör: Bilgi Yok"
    industry_line = "⚙️ Endüstri: Bilgi Yok"

    keys_to_extract = {
        "Hedef Fiyat:": ("🎯", target_price_line),
        "Potansiyel:": ("🚀", potential_line),
        "Analist Sayısı:": ("👨‍💼", analyst_count_line),
        "Sektör:": ("🏢", sector_line),
        "Endüstri:": ("⚙️", industry_line)
    }
    extracted_lines_set = set() # Çıkarılan satırları takip et

    for line in detaylar:
        for key, (emoji, default_value) in keys_to_extract.items():
            if key in line:
                # Emojiyi satırın başına ekleyelim (eğer zaten yoksa)
                formatted_line = f"{emoji} {line}" if not line.startswith(emoji) else line
                # İlgili değişkene ata
                if key == "Hedef Fiyat:": target_price_line = formatted_line
                elif key == "Potansiyel:": potential_line = formatted_line # % işareti zaten geliyorsa eklemeyelim
                elif key == "Analist Sayısı:": analyst_count_line = formatted_line
                elif key == "Sektör:": sector_line = formatted_line
                elif key == "Endüstri:": industry_line = formatted_line
                extracted_lines_set.add(line) # Bu satırı ana listeden çıkarmak için işaretle
                break # Bir anahtar eşleşince diğerlerine bakmaya gerek yok

    # Anahtar bilgileri içermeyen "core" detayları al
    core_details = [line for line in detaylar if line not in extracted_lines_set]
    detay_text = "\n".join(core_details)

    # Çıktıyı örnekteki gibi formatla
    output = (
        f"📊 *{t} Analiz Sonuçları (Puan: {puan})*\n"
        f"{detay_text}\n"
        f"{target_price_line}\n"
        f"{potential_line}\n"
        f"{analyst_count_line}\n"
        f"{sector_line}\n"
        f"{industry_line}\n\n"
        # Yorumu da ekleyelim (eğer varsa ve farklıysa)
        # f"{ticker_data.get('yorum', '')}" # Bu satır zaten alttaki ile aynı bilgiyi veriyor
        f"{t} için analiz tamamlandı. Toplam puan: {puan}."
    )
    return output

def format_bist_analiz_output(ticker_data):
    """BİST analiz verisini istenen formata getirir."""
    sembol = ticker_data.get("symbol", "Bilinmiyor")
    puan = ticker_data.get("score", "N/A")
    sinif = ticker_data.get("classification", "Belirtilmemiş")
    yorumlar = ticker_data.get("comments", [])

    emoji_map = {
        "peg oranı": "🎯",
        "f/k oranı": "💰",
        "net borç/favök": "🏦",
        "net dönem karı": "📈",
        "finansal borç": "📉",
        "net borç": "💸",
        "dönen varlıklar": "🔄",
        "duran varlıklar": "🏢",
        "toplam varlıklar": "🏛️",
        "özkaynak": "🧱",
        "default": "➡️" # Eşleşmeyenler için varsayılan emoji
    }

    yorum_lines = []
    if yorumlar: # Yorumlar listesi boş değilse işle
        for y in yorumlar:
            y_clean = str(y).strip() # String'e çevir ve boşlukları temizle
            if not y_clean: continue # Boş yorumları atla

            eklenecek_emoji = emoji_map["default"]
            lower_y = y_clean.lower()
            found_emoji = False
            # Daha spesifik eşleşme için metrik adının başta olup olmadığını kontrol et
            for k, v in emoji_map.items():
                if k != "default" and lower_y.startswith(k):
                    eklenecek_emoji = v
                    found_emoji = True
                    break
            # Eğer başta bulunamadıysa, içinde geçiyor mu diye bak (ikinci tercih)
            if not found_emoji:
                 for k, v in emoji_map.items():
                     if k != "default" and k in lower_y:
                         eklenecek_emoji = v
                         break # İlk bulduğunu al

            yorum_lines.append(f"{eklenecek_emoji} {y_clean}")
    else:
        yorum_lines.append("➡️ Yorum bulunamadı.")

    yorum_text = "\n".join(yorum_lines)

    # Çıktıyı örnekteki gibi formatla
    output = (
        f"📊 BİST Detaylı Analiz\n\n"
        f"🏷️ Sembol: *{sembol}*\n" # Sembolü kalın yapalım
        f"📈 Puan: *{puan}*\n" # Puanı kalın yapalım
        f"🏅 Sınıflandırma: {sinif}\n\n"
        f"📝 Öne Çıkanlar:\n{yorum_text}"
    )
    return output


# --- Komut İşleyiciler ---

def handle_analiz_command(chat_id, args):
    """ /analiz komutunu işler ve sonucu Telegram'a gönderir. """
    if not args:
        send_telegram_message(chat_id, "Lütfen analiz etmek istediğiniz hisse senedi sembollerini virgülle ayırarak belirtin.\nÖrnek: `/analiz AAPL, MSFT`")
        return

    # Argümanları temizle (virgül ve boşluklara göre ayır, büyük harfe çevir, boşları filtrele)
    tickers = [t.strip().upper() for t in re.split(r'[ ,]+', args) if t.strip()]
    if not tickers:
        send_telegram_message(chat_id, "Geçerli bir hisse senedi sembolü belirtilmedi.\nÖrnek: `/analiz AAPL,MSFT`")
        return

    print(f"🔍 /analiz komutu alındı (Chat ID: {chat_id}): {tickers}")

    data = load_json_file(ANALIZ_FILE)
    if data is None: # load_json_file hata ile None döndürdüyse
        send_telegram_message(chat_id, f"❌ Analiz verileri ({os.path.basename(ANALIZ_FILE)}) yüklenirken bir hata oluştu. Lütfen yönetici ile iletişime geçin.")
        return
    if not data: # Boş sözlük döndüyse (dosya boş veya bulunamadı)
         send_telegram_message(chat_id, f"❌ Analiz verileri ({os.path.basename(ANALIZ_FILE)}) bulunamadı veya boş. Lütfen daha sonra tekrar deneyin.")
         return

    results_found = []
    results_not_found = []

    for t in tickers:
        hisse_data = data.get(t)
        if hisse_data and isinstance(hisse_data, dict): # Veri var mı ve sözlük mü?
            # JSON verisine sembolü ekleyelim, formatlama fonksiyonunda kullanmak için
            hisse_data['symbol'] = t
            results_found.append(hisse_data)
        else:
            results_not_found.append(f"❌ `{t}` için veri bulunamadı.") # Bulunamayanları Markdown ile işaretle

    if not results_found:
        error_message = "\n".join(results_not_found) if results_not_found else f"❌ Belirtilen sembol(ler) için ({', '.join(tickers)}) analiz verisi bulunamadı."
        send_telegram_message(chat_id, error_message)
        return

    # Bulunan hisseleri puanlarına göre sırala (puan 'N/A' veya sayısal değilse en sona)
    def get_score(item):
        score = item.get('puan', -float('inf')) # Puan yoksa en düşük
        if isinstance(score, (int, float)):
            return score
        # Sayısal olmayan puanları (örn. string) en sona atmak için -inf kullan
        try:
             return float(score)
        except (ValueError, TypeError):
             return -float('inf')

    results_found.sort(key=get_score, reverse=True)

    # Sıralanmış sonuçları formatla
    formatted_results = [format_analiz_output(hisse) for hisse in results_found]

    # Tüm mesajları birleştir (bulunanlar + bulunamayanlar)
    final_output_parts = formatted_results + results_not_found
    final_output = "\n\n".join(final_output_parts)

    # Tek mesaj olarak gönder (send_telegram_message zaten bölecek)
    send_telegram_message(chat_id, final_output)

def handle_bist_analiz_command(chat_id, args):
    """ /bist_analiz komutunu işler """
    if not args:
        send_telegram_message(chat_id, "Lütfen analiz etmek istediğiniz BİST hisse senedi sembolünü belirtin.\nÖrnek: `/bist_analiz MIATK`")
        return

    # Sadece ilk sembolü al, temizle
    ticker = args.split(None, 1)[0].strip().upper() # İlk kelimeyi al
    if not ticker:
        send_telegram_message(chat_id, "Geçerli bir BİST hisse senedi sembolü belirtilmedi.\nÖrnek: `/bist_analiz MIATK`")
        return

    print(f"🔍 /bist_analiz komutu alındı (Chat ID: {chat_id}): {ticker}")

    data = load_json_file(BIST_ANALIZ_FILE)
    if data is None: # Hata durumu
        send_telegram_message(chat_id, f"❌ BİST Analiz verileri ({os.path.basename(BIST_ANALIZ_FILE)}) yüklenirken bir hata oluştu. Lütfen yönetici ile iletişime geçin.")
        return
    if not data: # Boş veya bulunamadı
         send_telegram_message(chat_id, f"❌ BİST Analiz verileri ({os.path.basename(BIST_ANALIZ_FILE)}) bulunamadı veya boş.")
         return

    hisse_data = data.get(ticker)

    if not hisse_data or not isinstance(hisse_data, dict):
        send_telegram_message(chat_id, f"❌ `{ticker}` için BİST analiz verisi bulunamadı.")
        return

    # Sonucu formatla ve gönder
    output = format_bist_analiz_output(hisse_data)
    send_telegram_message(chat_id, output)

def handle_ozet_command(chat_id, args):
    """ /ozet komutunu işler (şimdilik pasif) """
    print(f"🔍 /ozet komutu alındı (Chat ID: {chat_id})")
    # Örnek çıktıyı doğrudan gönderelim (geçici olarak)
    ozet_text = """
📊 GÜÇLÜ EŞLEŞEN SİNYALLER:

Yok

🔴 KAIRI ≤ -30:
SUIUSDT.P (BINANCE): KAIRI -30.45
ETHUSDT.P (BINANCE): KAIRI -41.8
AVAXUSDT.P (BINANCE): KAIRI -33.94
DOGEUSDT.P (BINANCE): KAIRI -38.69
DOTUSDT.P (BINANCE): KAIRI -34.32
TONUSDT.P (BINANCE): KAIRI -39.19

🟠 KAIRI ≤ -20:
LINKUSDT.P (BINANCE): KAIRI -26.53
LTCUSDT.P (BINANCE): KAIRI -20.43
SOLUSDT.P (BINANCE): KAIRI -28.68

🟢 Mükemmel Alış:
Yok

📈 Alış Sayımı Tamamlananlar:
Yok

🔵 Mükemmel Satış:
Yok

🟣 Matisay < -25:
MSFT (NASDAQ): Matisay -28.67
BIA (BINANCE): Matisay -28.0
AAPL (NASDAQ): Matisay -26.0
Bilinmiyor (Bilinmiyor): Matisay -27.0
    """
    # /ozet için Markdown yerine düz metin daha iyi olabilir, veya formatlamayı düzeltmek gerekir.
    # Şimdilik düz gönderelim.
    send_telegram_message(chat_id, ozet_text.strip(), parse_mode=None) # Markdown kapalı
    # send_telegram_message(chat_id, "ℹ️ `/ozet` komutu şu anda statik veri göstermektedir.") # Bilgilendirme


# --- Flask Rotaları ---

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Telegram'dan gelen webhook isteklerini işler."""
    start_time = time.time() # İşlem süresini ölçmek için
    try:
        update = request.get_json()
        if not update:
            print("⚠️ Boş veya geçersiz JSON alındı.")
            return "error: invalid json", 400

        # print(f"🔄 Gelen Update: {json.dumps(update, indent=2, ensure_ascii=False)}") # Debug

        # Sadece metin mesajlarını ve komutları işle
        if "message" in update and "text" in update["message"]:
            message = update["message"]
            chat_id = message["chat"]["id"]
            text = message["text"]
            user_info = message.get("from", {})
            username = user_info.get("username", "N/A")
            first_name = user_info.get("first_name", "")

            # Sadece komutları işle ( '/' ile başlayanlar)
            if text.startswith('/'):
                parts = text.split(' ', 1)
                command = parts[0].lower()
                args = parts[1].strip() if len(parts) > 1 else ""

                print(f"➡️ Komut alındı: {command} | Args: '{args}' | Chat: {chat_id} | User: @{username} ({first_name})")

                if command == "/analiz":
                    handle_analiz_command(chat_id, args)
                elif command == "/bist_analiz":
                    handle_bist_analiz_command(chat_id, args)
                elif command == "/ozet":
                     handle_ozet_command(chat_id, args)
                elif command == "/start" or command == "/help":
                     help_text = (
                         f"Merhaba {first_name}! 👋\n\n"
                         "Kullanılabilir komutlar:\n\n"
                         "*ABD Analizi:*\n"
                         "`/analiz <Sembol1>,<Sembol2>,...`\n"
                         "_(Örn: `/analiz TSLA,AAPL`)_\n\n"
                         "*BİST Analizi:*\n"
                         "`/bist_analiz <Sembol>`\n"
                         "_(Örn: `/bist_analiz MIATK`)_\n\n"
                         "*Diğer:*\n"
                         "`/ozet` - Günlük sinyal özeti (Statik Veri).\n"
                         "`/help` - Bu yardım mesajı."
                     )
                     send_telegram_message(chat_id, help_text)
                else:
                    send_telegram_message(chat_id, f"❓ Bilinmeyen komut: `{command}`\nKullanılabilir komutlar için /help yazın.")
            # else: # Komut olmayan mesajları logla (opsiyonel)
            #     print(f"💬 Mesaj alındı (Komut Değil): Chat: {chat_id} | User: @{username} | Text: '{text[:50]}...'")

        # Telegram'a hızlı yanıt vermek önemli
        return "ok", 200

    except Exception as e:
        # Hata durumunda admin'e detaylı bilgi ver
        error_details = traceback.format_exc()
        print(f"💥 Webhook HATA: {e}\n{error_details}")
        if ADMIN_CHAT_ID:
             # Gelen isteği de ekleyerek hatayı daha iyi anlamayı sağla
             try:
                 request_data = request.get_data(as_text=True)
             except Exception:
                 request_data = "Request data could not be read."
             error_message_to_admin = f"🚨 Webhook Hatası!\n\nError: {e}\n\nTraceback:\n{error_details}\n\nRequest Data:\n{request_data[:1000]}" # İlk 1000 karakter
             send_telegram_message(ADMIN_CHAT_ID, error_message_to_admin, parse_mode=None, avoid_self_notify=True) # Markdown kullanma

        # Kullanıcıya genel bir hata mesajı gönder (opsiyonel)
        try:
             if 'message' in update and 'chat' in update['message']:
                 user_chat_id = update['message']['chat']['id']
                 send_telegram_message(user_chat_id, "⚠️ Bir hata oluştu. Lütfen daha sonra tekrar deneyin veya yönetici ile iletişime geçin.")
        except Exception as inner_e:
             print(f"⚠️ Kullanıcıya hata mesajı gönderirken hata: {inner_e}")

        return "error", 500
    finally:
         # İşlem süresini yazdır
         end_time = time.time()
         print(f"⏱️ İstek işleme süresi: {end_time - start_time:.4f} saniye")


@app.route("/", methods=["GET"])
def index():
    # Basit bir HTML sayfası döndürebiliriz
    return """
    <!DOCTYPE html>
    <html>
    <head><title>SignalCihangir Bot</title></head>
    <body>
        <h1>SignalCihangir Bot Aktif!</h1>
        <p>Telegram webhook istekleri <code>/telegram</code> adresinde dinleniyor.</p>
        <p>Test endpoint'i: <a href="/test">/test</a></p>
    </body>
    </html>
    """, 200

@app.route("/test", methods=["GET"])
def test():
    # Test mesajı gönder
    message_to_admin = "✅ Bot test endpoint'i başarıyla çalıştırıldı."
    if ADMIN_CHAT_ID:
        if send_telegram_message(ADMIN_CHAT_ID, message_to_admin):
            return f"Test başarılı! Yöneticiye (Chat ID: {ADMIN_CHAT_ID}) mesaj gönderildi.", 200
        else:
            return f"Test endpoint'i çalıştı ancak yöneticiye mesaj gönderilemedi (Chat ID: {ADMIN_CHAT_ID}).", 500
    else:
        return "Test başarılı! Ancak yönetici CHAT_ID ayarlanmadığı için mesaj gönderilemedi.", 200

# --- Sunucuyu Başlatma ---

if __name__ == "__main__":
    print(f" HHHHHH   EEEEEEE  RRRRRR   EEEEEEE   SSSSSS\n"
            f" H::::H   E:::::E  R::::R   E:::::E  SS::::SS\n"
            f" H::::H   E:::::E  R:::::R  E:::::E S:::::S\n"
            f" HH::HH   E:::::E  R:::::R  E:::::E S:::::S\n"
            f"   H::::H   E:::::E  RR:::::R   E:::::E  S:::::S\n"
            f"   H::::H   E:::::E   R::::R    E:::::E   S::::SS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E    SS::::SS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E     SSS::::S\n"
            f"   H::::H   E:::::E   R::::R    E:::::E       SSSSS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E       SSSSS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E       SSSSS\n"
            f"   H::::H   E:::::E  RR:::::R   E:::::E       SSSSS\n"
            f" HH::HH   E:::::E  R:::::R  E:::::E S:::::S  SSSSS\n"
            f" H::::H   E:::::E  R:::::R  E:::::E S:::::S  SSSSS\n"
            f" H::::H   E:::::E  R:::::R  E:::::E SS::::SS SSSSS\n"
            f" HHHHHH   EEEEEEE  RRRRRR   EEEEEEE  SSSSSS  SSSSS\n")
    print("==============================================")
    print("✅ SignalCihangir Flask Bot Başlatılıyor...")
    print(f"🔧 Ortam: {'Production' if not os.getenv('FLASK_DEBUG') else 'Development'}")
    print(f"🔗 Dinlenen Adres: http://0.0.0.0:5000")
    print(f"📄 ABD Analiz Dosyası: {ANALIZ_FILE}")
    print(f"📄 BIST Analiz Dosyası: {BIST_ANALIZ_FILE}")
    print(f"👤 Yönetici Chat ID: {ADMIN_CHAT_ID if ADMIN_CHAT_ID else 'Ayarlanmadı'}")
    print("==============================================")
    # Geliştirme ortamı için debug=True kullanılabilir:
    # export FLASK_DEBUG=1
    # app.run(host="0.0.0.0", port=5000)
    # Production için debug=False (varsayılan)
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000) # Daha stabil bir production sunucusu
