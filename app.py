# -*- coding: utf-8 -*-
import os
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, render_template
# PostgreSQL'e bağlanmak için psycopg2 kütüphanesini kullanıyoruz.
import psycopg2 
# Sorgu sonuçlarını sözlük (dict) olarak almak için
from psycopg2.extras import RealDictCursor 
import json
from datetime import datetime, timedelta
from collections import defaultdict
import math
from flask_cors import CORS 

# --- UYGULAMA YAPILANDIRMASI ---
# Render'ın kullandığı PORT'u alır, yerelde 5000 kullanılır.
PORT = int(os.environ.get('PORT', 5000)) 
app = Flask(__name__)
# Mobil erişim (CORS) için gereklidir.
CORS(app) 

# PostgreSQL bağlantı URL'sini ortam değişkeninden oku. 
DATABASE_URL = os.environ.get("DATABASE_URL")

# JSON dosyaları hala yerel diskte tutuluyor.
KAPASITE_FILE = 'kapasite.json' 
KALINLIK_FILE = 'kalinliklar.json' # YENİ: Kalınlıkları tutmak için dosya
# Önbellekleme (caching) sorunlarını azaltmak için ayar.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0 

# --- 0. SABİT TANIMLAMALAR VE DİNAMİK YÜKLEME ---
# Varsayılanlar
DEFAULT_KALINLIKLAR = ['2 CM', '3.6 CM', '3 CM']
CINSLER = ['BAROK', 'YATAY TAŞ', 'DÜZ TUĞLA', 'KAYRAK TAŞ', 'PARKE TAŞ', 'KIRIK TAŞ', 'BUZ TAŞ', 'MERMER', 'LB ZEMİN', 'LA']

def load_kalinliklar():
    """Kalınlık listesini JSON'dan yükler, yoksa varsayılanı kullanır ve kaydeder."""
    if os.path.exists(KALINLIK_FILE):
        with open(KALINLIK_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('kalinliklar', DEFAULT_KALINLIKLAR)
    # Yoksa varsayılanı kaydet ve döndür
    save_data({'kalinliklar': DEFAULT_KALINLIKLAR}, KALINLIK_FILE)
    return DEFAULT_KALINLIKLAR

def save_kalinliklar(kalinliklar):
    """Kalınlık listesini JSON'a kaydeder."""
    save_data({'kalinliklar': kalinliklar}, KALINLIK_FILE)
    
# Dinamik olarak yükle
KALINLIKLAR = load_kalinliklar()
VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]

# --- JSON/KAPASİTE/ÜRÜN KODU YÖNETİMİ ---

def load_data(filename):
    """JSON verisini yükler ve yoksa varsayılan değerleri döndürür."""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    if filename == KAPASITE_FILE:
        return {"gunluk_siva_m2": 600}
    
    if filename == 'urun_kodlari.json':
        # Varsayılan urun_kodlari.json verisi
        return {
            'BAROK 2 CM': ['B001', 'B002', 'B003', 'B004', 'B005', 'B006', 'B007', 'B008', 'B009', 'B010', 'B011', 'B012', 'B013', 'B014', 'B015', 'B016', 'B017', 'B018', 'B019', 'B020', 'B021', 'B022', 'B023', 'B024', 'B025', 'B026', 'B027', 'B028', 'B029', 'B030', 'B031', 'B032', 'B033', 'B035', 'B036', 'B037', 'B038', 'B039', 'B040'],
            'PARKE TAŞ 2 CM': [f'PT{i:03}' for i in range(1, 31)],
            'KIRIK TAŞ 2 CM': [f'KR{i:03}' for i in range(1, 13)],
            'YATAY TAŞ 2 CM': ['YT011', 'YT012', 'YT013', 'YT014', 'YT015', 'YT016'],
            'KAYRAK TAŞ 2 CM': [f'KY{i:03}' for i in range(1, 15)],
            'DÜZ TUĞLA 2 CM': [f'DT1{i:02}' for i in range(1, 21)],
            'DÜZ TUĞLA 3.6 CM': [f'DT3{i:02}' for i in range(1, 21)],
            'BUZ TAŞ 2 CM': [f'BT{i:03}' for i in range(1, 11)],
            'BUZ TAŞ 3.6 CM': [f'BT{i:03}' for i in range(101, 111)],
            'MERMER 3 CM': [f"M{i:03}" for i in range(1, 10)],
            'LA 3 CM': [f"L{i:03}" for i in range(1, 10)],
            'LB ZEMİN 3 CM': [f"LB{i:03}" for i in range(1, 10)],
            'BAROK 3.6 CM': ['B401', 'B402', 'B403'],
            'YATAY TAŞ 3.6 CM': ['YT401', 'YT402', 'YT403'],
            'KAYRAK TAŞ 3.6 CM': ['KY401', 'KY402', 'KY403'],
        }
    return {}

def save_data(data, filename):
    """JSON verisini kaydeder."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

CINS_TO_BOYALI_MAP = load_data('urun_kodlari.json')
URUN_KODLARI = sorted(list(set(code for codes in CINS_TO_BOYALI_MAP.values() for code in codes)))


# --- 1. VERİTABANI İŞLEMLERİ VE BAŞLANGIÇ (POSTGRESQL) ---

def get_db_connection():
    """PostgreSQL veritabanı bağlantısını açar."""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL ortam değişkeni Render'da tanımlı değil. Bağlantı kurulamıyor.")
    
    # RealDictCursor, bağlantıdan oluşturulan tüm imleçlerin sözlük (dict) döndürmesini sağlar.
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    
    return conn

def init_db():
    """Veritabanını ve tabloları oluşturur."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(""" 
            CREATE TABLE IF NOT EXISTS stok ( 
                id SERIAL PRIMARY KEY, 
                cinsi TEXT NOT NULL, 
                kalinlik TEXT NOT NULL, 
                asama TEXT NOT NULL, 
                m2 INTEGER, 
                UNIQUE(cinsi, kalinlik, asama) 
            ); 
        """)
        cur.execute(""" 
            CREATE TABLE IF NOT EXISTS siparisler ( 
                id SERIAL PRIMARY KEY, 
                siparis_kodu TEXT NOT NULL UNIQUE, 
                urun_kodu TEXT NOT NULL, 
                cinsi TEXT NOT NULL, 
                kalinlik TEXT NOT NULL, 
                musteri TEXT NOT NULL, 
                siparis_tarihi DATE NOT NULL, 
                termin_tarihi DATE, 
                bekleyen_m2 INTEGER, 
                durum TEXT NOT NULL, 
                planlanan_is_gunu INTEGER 
            ); 
        """)

        # YENİ: Kalınlıklar değişebileceği için VARYANTLAR'ı yeniden hesapla
        global KALINLIKLAR, VARYANTLAR
        KALINLIKLAR = load_kalinliklar()
        VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
        
        # Varsayılan stok girişleri (EĞER YOKSA ekle)
        for c, k in VARYANTLAR:
            for asama in ['Ham', 'Sivali']:
                cur.execute("""
                    INSERT INTO stok (cinsi, kalinlik, asama, m2) 
                    VALUES (%s, %s, %s, %s) 
                    ON CONFLICT (cinsi, kalinlik, asama) DO NOTHING
                """, (c, k, asama, 0))
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Veritabanı Başlatma Hatası: {e}")

with app.app_context():
    init_db()
    
    if not os.path.exists(KAPASITE_FILE):
        save_data({"gunluk_siva_m2": 600}, KAPASITE_FILE)
    if not os.path.exists('urun_kodlari.json'):
        save_data(CINS_TO_BOYALI_MAP, 'urun_kodlari.json')


# --- 2. YARDIMCI FONKSİYONLAR VE PLANLAMA MANTIĞI ---

def get_next_siparis_kodu(conn):
    """Bir sonraki sipariş kodunu oluşturur."""
    cur = conn.cursor()
    current_year = datetime.now().strftime('%Y')
    
    cur.execute(f""" 
        SELECT siparis_kodu 
        FROM siparisler 
        WHERE siparis_kodu LIKE 'S-{current_year}-%' 
        ORDER BY siparis_kodu DESC 
        LIMIT 1 
    """)
    last_code_row = cur.fetchone()
    
    if last_code_row:
        last_code = last_code_row['siparis_kodu'] 
        try:
            last_number = int(last_code.split('-')[-1])
            new_number = last_number + 1
        except ValueError:
            new_number = 1 
    else:
        new_number = 1
    cur.close()
    return f"S-{current_year}-{new_number:04}"

def calculate_planning(conn):
    """
    Sıva planı, sevkiyat planı ve ürün bazlı sıva ihtiyacı detaylarını hesaplar.
    """
    try: # Hata yakalamayı başlat
        cur = conn.cursor()
        kapasite = load_data(KAPASITE_FILE)['gunluk_siva_m2']
        stok_map = {}
        
        cur.execute("SELECT cinsi, kalinlik, asama, m2 FROM stok")
        stok_raw = cur.fetchall()
        
        for row in stok_raw:
            key = (row['cinsi'], row['kalinlik'])
            if key not in stok_map: stok_map[key] = {'Ham': 0, 'Sivali': 0}
            stok_map[key][row['asama']] = row['m2']

        # KRİTİK KISIM: Termin tarihine göre sıralama
        cur.execute("""
            SELECT id, cinsi, kalinlik, bekleyen_m2, termin_tarihi 
            FROM siparisler 
            WHERE durum='Bekliyor' 
            ORDER BY termin_tarihi ASC, siparis_tarihi ASC 
        """)
        bekleyen_siparisler = cur.fetchall()

        siva_uretim_ihtiyaci = [] 
        toplam_gerekli_siva = 0 
        planlama_sonuclari = {} 
        temp_stok_sivali = {k: v.get('Sivali', 0) for k, v in stok_map.items()}
        
        for siparis in bekleyen_siparisler:
            key = (siparis['cinsi'], siparis['kalinlik'])
            stok_sivali = temp_stok_sivali.get(key, 0)
            gerekli_m2 = siparis['bekleyen_m2']
            eksik_sivali = max(0, gerekli_m2 - stok_sivali)
            temp_stok_sivali[key] = max(0, stok_sivali - gerekli_m2) 

            if eksik_sivali > 0:
                toplam_gerekli_siva += eksik_sivali
                siva_uretim_ihtiyaci.append({
                    'key': f"{siparis['cinsi']} {siparis['kalinlik']}",
                    'm2': eksik_sivali
                })
                
            is_gunu = math.ceil(toplam_gerekli_siva / kapasite) if kapasite > 0 else -1
            planlama_sonuclari[siparis['id']] = is_gunu if eksik_sivali > 0 else 0

        # Hesaplanan iş günlerini veritabanına kaydet
        for siparis_id, is_gunu in planlama_sonuclari.items():
            cur.execute("UPDATE siparisler SET planlanan_is_gunu = %s WHERE id = %s", (is_gunu, siparis_id))
        conn.commit()
        
        # --- YENİ KISIM: Kapasiteyi Ürün Bazında Dağıtma ---
        siva_plan_detay = defaultdict(list) 
        kalan_kapasite_bugun = 0
        ihtiyac_index = 0
        
        for gun in range(1, 6): # Önümüzdeki 5 gün için planlama
            kalan_kapasite_bugun = kapasite
            
            while kalan_kapasite_bugun > 0 and ihtiyac_index < len(siva_uretim_ihtiyaci):
                ihtiyac = siva_uretim_ihtiyaci[ihtiyac_index]
                key = ihtiyac['key']
                m2_gerekli = ihtiyac['m2']
                
                m2_yapilacak = min(m2_gerekli, kalan_kapasite_bugun)
                
                siva_plan_detay[gun].append({
                    'cinsi': key,
                    'm2': m2_yapilacak
                })
                
                ihtiyac['m2'] -= m2_yapilacak
                kalan_kapasite_bugun -= m2_yapilacak
                
                if ihtiyac['m2'] <= 0:
                    ihtiyac_index += 1
                
            if ihtiyac_index >= len(siva_uretim_ihtiyaci):
                break 
        
        # 5 Günlük Sevkiyat Detay Planı (Termin tarihine göre)
        bugun = datetime.now().date()
        sevkiyat_plan_detay = defaultdict(list)
        for i in range(0, 5): 
            plan_tarihi = (bugun + timedelta(days=i)).strftime('%Y-%m-%d')
            cur.execute("""
                SELECT siparis_kodu, musteri, urun_kodu, bekleyen_m2 
                FROM siparisler 
                WHERE durum='Bekliyor' AND termin_tarihi = %s
                ORDER BY termin_tarihi ASC
            """, (plan_tarihi,))
            sevkiyatlar = cur.fetchall()
            
            if sevkiyatlar:
                sevkiyat_plan_detay[plan_tarihi] = sevkiyatlar
        
        cur.close()
        return toplam_gerekli_siva, kapasite, siva_plan_detay, sevkiyat_plan_detay, stok_map
        
    except Exception as e:
        print(f"--- KRİTİK HATA LOGU (calculate_planning) ---")
        print(f"Hata Tipi: {type(e).__name__}")
        print(f"Hata Mesajı: {str(e)}")
        # Hata devam etsin ki Render loglarına düşebilsin
        raise 

# --- 3. ROTALAR (PC Arayüzü ve İşlemler) ---

@app.route('/', methods=['GET'])
def index():
    """Ana PC arayüzünü (veri giriş ve kapsamlı tablolar) gösterir."""
    conn = get_db_connection() 
    cur = conn.cursor()
    message = request.args.get('message')
    gunluk_siva_m2 = load_data(KAPASITE_FILE)['gunluk_siva_m2']
    
    # YENİ: Kalınlıklar değişmiş olabileceği için VARYANTLAR'ı tekrar oluştur
    global KALINLIKLAR, VARYANTLAR
    KALINLIKLAR = load_kalinliklar()
    VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
    
    toplam_gerekli_siva, kapasite, siva_plan_detay, sevkiyat_plan_detay, stok_map = calculate_planning(conn)
    
    stok_list = []
    for cinsi, kalinlik in VARYANTLAR:
        ham_m2 = stok_map.get((cinsi, kalinlik), {}).get('Ham', 0)
        sivali_m2 = stok_map.get((cinsi, kalinlik), {}).get('Sivali', 0)
        
        cur.execute(""" SELECT SUM(bekleyen_m2) as toplam_m2 FROM siparisler WHERE durum='Bekliyor' AND cinsi=%s AND kalinlik=%s """, (cinsi, kalinlik))
        bekleyen_m2_raw = cur.fetchone()
        
        gerekli_siparis_m2 = bekleyen_m2_raw['toplam_m2'] if bekleyen_m2_raw and bekleyen_m2_raw['toplam_m2'] else 0
        sivali_eksik = max(0, gerekli_siparis_m2 - sivali_m2)
        ham_eksik = max(0, sivali_eksik - ham_m2)
        stok_list.append({'cinsi': cinsi, 'kalinlik': kalinlik, 'ham_m2': ham_m2, 'sivali_m2': sivali_m2, 'gerekli_siparis_m2': gerekli_siparis_m2, 'sivali_eksik': sivali_eksik, 'ham_eksik': ham_eksik})
    
    cur.execute("SELECT * FROM siparisler ORDER BY termin_tarihi ASC, siparis_tarihi DESC")
    siparisler = cur.fetchall() 
    next_siparis_kodu = get_next_siparis_kodu(conn)
    today = datetime.now().strftime('%Y-%m-%d')
    cur.close()
    conn.close()
    
    # HTML_TEMPLATE, uygulamanın en altında tanımlıdır.
    return render_template_string(HTML_TEMPLATE, stok_list=stok_list, siparisler=siparisler, CINSLER=CINSLER, KALINLIKLAR=KALINLIKLAR, next_siparis_kodu=next_siparis_kodu, today=today, message=message, gunluk_siva_m2=gunluk_siva_m2, toplam_gerekli_siva=toplam_gerekli_siva, siva_plan_detay=siva_plan_detay, sevkiyat_plan_detay=sevkiyat_plan_detay, CINS_TO_BOYALI_MAP=CINS_TO_BOYALI_MAP)

@app.route('/islem', methods=['POST'])
def handle_stok_islem():
    """Stok hareketlerini yönetir."""
    action = request.form['action']
    cinsi = request.form['cinsi']
    kalinlik = request.form['kalinlik']
    m2 = int(request.form['m2'])
    conn = None
    message = ""
    success = True
    try:
        conn = get_db_connection() 
        cur = conn.cursor()

        if action == 'ham_alim': 
            cur.execute("UPDATE stok SET m2 = m2 + %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (m2, cinsi, kalinlik))
            message = f"✅ {cinsi} {kalinlik} Ham stoğuna {m2} m² eklendi."
        
        elif action == 'siva_uygula':
            cur.execute("SELECT m2 FROM stok WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (cinsi, kalinlik))
            ham_stok_row = cur.fetchone()
            ham_stok = ham_stok_row['m2'] if ham_stok_row else 0
            if ham_stok < m2: 
                success = False; message = f"❌ Hata: {cinsi} {kalinlik} Ham stoğu yetersiz ({ham_stok} m²). {m2} m² Sıva uygulanamadı."
            else: 
                cur.execute("UPDATE stok SET m2 = m2 - %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (m2, cinsi, kalinlik))
                cur.execute("UPDATE stok SET m2 = m2 + %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Sivali'", (m2, cinsi, kalinlik))
                message = f"✅ {cinsi} {kalinlik} için {m2} m² Sıva Uygulandı (Ham -> Sıvalı)."
        
        elif action == 'sat_sivali':
            cur.execute("SELECT m2 FROM stok WHERE cinsi = %s AND kalinlik = %s AND asama = 'Sivali'", (cinsi, kalinlik))
            sivali_stok_row = cur.fetchone()
            sivali_stok = sivali_stok_row['m2'] if sivali_stok_row else 0
            if sivali_stok < m2: 
                success = False; message = f"❌ Hata: {cinsi} {kalinlik} Sıvalı stoğu yetersiz ({sivali_stok} m²). {m2} m² Satış yapılamadı."
            else: 
                cur.execute("UPDATE stok SET m2 = m2 - %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Sivali'", (m2, cinsi, kalinlik))
                message = f"✅ {cinsi} {kalinlik} Sıvalı stoğundan {m2} m² Satıldı."
        
        elif action == 'sat_ham':
            cur.execute("SELECT m2 FROM stok WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (cinsi, kalinlik))
            ham_stok_row = cur.fetchone()
            ham_stok = ham_stok_row['m2'] if ham_stok_row else 0
            if ham_stok < m2: 
                success = False; message = f"❌ Hata: {cinsi} {kalinlik} Ham stoğu yetersiz ({ham_stok} m²). {m2} m² Satış yapılamadı."
            else: 
                cur.execute("UPDATE stok SET m2 = m2 - %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (m2, cinsi, kalinlik))
                message = f"✅ {cinsi} {kalinlik} Ham stoğundan {m2} m² Satıldı."
        
        elif action == 'iptal_ham_alim':
            cur.execute("SELECT m2 FROM stok WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (cinsi, kalinlik))
            ham_stok_row = cur.fetchone()
            ham_stok = ham_stok_row['m2'] if ham_stok_row else 0
            if ham_stok < m2: 
                success = False; message = f"❌ Hata: {cinsi} {kalinlik} Ham stoğu yetersiz ({ham_stok} m²). Ham alımı iptal edilemedi."
            else: 
                cur.execute("UPDATE stok SET m2 = m2 - %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (m2, cinsi, kalinlik))
                message = f"✅ {cinsi} {kalinlik} Ham alımı iptal edildi ({m2} m² stoktan çıkarıldı)."
        
        elif action == 'iptal_siva':
            cur.execute("SELECT m2 FROM stok WHERE cinsi = %s AND kalinlik = %s AND asama = 'Sivali'", (cinsi, kalinlik))
            sivali_stok_row = cur.fetchone()
            sivali_stok = sivali_stok_row['m2'] if sivali_stok_row else 0
            if sivali_stok < m2: 
                success = False; message = f"❌ Hata: {cinsi} {kalinlik} Sıvalı stoğu yetersiz ({sivali_stok} m²). Sıva Geri Alınamadı."
            else: 
                cur.execute("UPDATE stok SET m2 = m2 - %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Sivali'", (m2, cinsi, kalinlik))
                cur.execute("UPDATE stok SET m2 = m2 + %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (m2, cinsi, kalinlik))
                message = f"✅ {cinsi} {kalinlik} Sıva işlemi geri alındı ({m2} m² Sıvalı -> Ham)."
        
        elif action == 'iptal_sat_sivali': 
            cur.execute("UPDATE stok SET m2 = m2 + %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Sivali'", (m2, cinsi, kalinlik))
            message = f"✅ {cinsi} {kalinlik} Sıvalı satış iptal edildi ({m2} m² stoğa eklendi)."
        
        elif action == 'iptal_sat_ham': 
            cur.execute("UPDATE stok SET m2 = m2 + %s WHERE cinsi = %s AND kalinlik = %s AND asama = 'Ham'", (m2, cinsi, kalinlik))
            message = f"✅ {cinsi} {kalinlik} Ham satış iptal edildi ({m2} m² stoğa eklendi)."

        if success: conn.commit()
        cur.close()
    except Exception as e: 
        if conn: conn.rollback()
        message = f"❌ Veritabanı Hatası: {str(e)}"
    finally: 
        if conn: conn.close()
    return redirect(url_for('index', message=message))

@app.route('/siparis', methods=['POST'])
def handle_siparis_islem():
    """Sipariş ekler, düzenler, siler veya tamamlar."""
    action = request.form['action']
    conn = None
    message = ""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if action == 'yeni_siparis':
            # Çoklu sipariş mantığı
            musteri = request.form['musteri']
            siparis_tarihi = request.form['siparis_tarihi']
            termin_tarihi = request.form['termin_tarihi']
            
            i = 0
            new_siparis_codes = []
            # Değiştirildi: İndeksleri formdaki tüm olası satırları tarayarak buluyoruz.
            # Bu, silinen satırlardan dolayı oluşan boşlukları atlamamızı sağlar.
            # JS'de kullanılan index'ler (0'dan başlayıp artan) burada form anahtarlarıdır.
            
            # Tüm form anahtarlarını kontrol ediyoruz.
            all_keys = list(request.form.keys())
            indices = sorted(list(set([int(k.split('_')[-1]) for k in all_keys if k.startswith('urun_kodu_')])))

            for i in indices:
                urun_kodu_key = f'urun_kodu_{i}'
                m2_key = f'm2_{i}'
                
                urun_kodu = request.form.get(urun_kodu_key, '').strip()
                m2_str = request.form.get(m2_key, '').strip() 
                
                # Sadece geçerli, dolu satırları işliyoruz
                if urun_kodu and m2_str:
                    try:
                        m2 = int(m2_str)
                    except ValueError:
                        m2 = 0 # Sayıya çevrilemezse 0 kabul et
                        
                    if m2 > 0:
                        siparis_kodu = get_next_siparis_kodu(conn)
                        
                        # Ürün kodundan cinsi ve kalınlığı ayrıştır
                        cins_kalinlik_key = next((key for key, codes in CINS_TO_BOYALI_MAP.items() if urun_kodu in codes), None)
                        if not cins_kalinlik_key:
                            raise ValueError(f"Ürün kodu {urun_kodu} için cins/kalınlık bulunamadı. Lütfen ürün kodlarını kontrol edin.")
                        
                        # Kalınlıklar virgüllü olabilir (örn: 1,1)
                        cinsi, kalinlik = cins_kalinlik_key.rsplit(' ', 1) 
                        
                        cur.execute(""" INSERT INTO siparisler (siparis_kodu, urun_kodu, cinsi, kalinlik, musteri, siparis_tarihi, termin_tarihi, bekleyen_m2, durum, planlanan_is_gunu) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) """, 
                                    (siparis_kodu, urun_kodu, cinsi, kalinlik, musteri, siparis_tarihi, termin_tarihi, m2, 'Bekliyor', 0))
                        
                        new_siparis_codes.append(siparis_kodu)
                
            if not new_siparis_codes:
                 raise ValueError("Hiçbir geçerli sipariş satırı (ürün kodu ve M² miktarı) girilmedi.")
                 
            conn.commit(); message = f"✅ {musteri} müşterisine ait {len(new_siparis_codes)} adet sipariş eklendi. Kodlar: {', '.join(new_siparis_codes)}"
            
        elif action == 'tamamla_siparis':
            siparis_id = request.form['siparis_id']
            cur.execute("UPDATE siparisler SET durum = 'Tamamlandi', bekleyen_m2 = 0, planlanan_is_gunu = 0 WHERE id = %s", (siparis_id,))
            conn.commit(); message = f"✅ Sipariş ID {siparis_id} tamamlandı olarak işaretlendi."
            
        # YENİ EK: Siparişi Düzenleme
        elif action == 'duzenle_siparis':
            siparis_id = request.form['siparis_id']
            yeni_urun_kodu = request.form['yeni_urun_kodu']
            yeni_m2 = int(request.form['yeni_m2'])
            
            # Ürün kodundan cins/kalınlık tespiti
            cins_kalinlik_key = next((key for key, codes in CINS_TO_BOYALI_MAP.items() if yeni_urun_kodu in codes), None)
            if not cins_kalinlik_key:
                 raise ValueError(f"Ürün kodu {yeni_urun_kodu} için cins/kalınlık bulunamadı.")
                 
            yeni_cinsi, yeni_kalinlik = cins_kalinlik_key.rsplit(' ', 1)
            
            cur.execute("""
                UPDATE siparisler SET 
                urun_kodu = %s, cinsi = %s, kalinlik = %s, bekleyen_m2 = %s 
                WHERE id = %s AND durum = 'Bekliyor'
            """, (yeni_urun_kodu, yeni_cinsi, yeni_kalinlik, yeni_m2, siparis_id))
            
            conn.commit(); message = f"✅ Sipariş ID {siparis_id} güncellendi: {yeni_cinsi} {yeni_kalinlik}, {yeni_m2} m²."

        # YENİ EK: Siparişi Kalıcı Silme (İz bırakmaz)
        elif action == 'sil_siparis':
            siparis_id = request.form['siparis_id']
            cur.execute("DELETE FROM siparisler WHERE id = %s", (siparis_id,))
            conn.commit(); message = f"✅ Sipariş ID {siparis_id} veritabanından **kalıcı olarak silindi**."
        
        # Kaldırılan 'iptal_siparis' bloğu
            
        cur.close()
    except psycopg2.IntegrityError: 
        if conn: conn.rollback()
        message = "❌ Hata: Bu sipariş kodu zaten mevcut. Lütfen tekrar deneyin."
    except ValueError as e: 
        if conn: conn.rollback()
        message = f"❌ Giriş Hatası: {str(e)}"
    except Exception as e: 
        if conn: conn.rollback()
        message = f"❌ Veritabanı Hatası: {str(e)}"
    finally: 
        if conn: conn.close()
    return redirect(url_for('index', message=message))

@app.route('/ayarla/kapasite', methods=['POST'])
def ayarla_kapasite():
    """Günlük sıva kapasitesini ayarlar."""
    try:
        kapasite_m2 = int(request.form['kapasite_m2'])
        if kapasite_m2 <= 0: raise ValueError("Kapasite pozitif bir sayı olmalıdır.")
        save_data({"gunluk_siva_m2": kapasite_m2}, KAPASITE_FILE)
        message = f"✅ Günlük sıva kapasitesi {kapasite_m2} m² olarak ayarlandı."
    except ValueError as e: message = f"❌ Hata: {str(e)}"
    except Exception as e: message = f"❌ Kaydetme Hatası: {str(e)}"
    return redirect(url_for('index', message=message))

# YENİ ROTA: Zemin Kalınlığı Ekleme
@app.route('/ayarla/kalinlik', methods=['POST'])
def ayarla_kalinlik():
    """Yeni bir zemin kalınlığı ekler ve stok tablosuna varsayılan girişleri yapar."""
    global KALINLIKLAR
    yeni_kalinlik = request.form['yeni_kalinlik'].strip().upper()
    message = ""
    conn = None
    try:
        if not yeni_kalinlik: raise ValueError("Kalınlık boş olamaz.")
        
        # "1,1" gibi girdileri "1.1 CM" formatına çevirelim
        if ',' in yeni_kalinlik:
            yeni_kalinlik = yeni_kalinlik.replace(',', '.') + ' CM'
        else:
            # "10" gibi girdiler zaten cm olarak kabul edilebilir.
            if not yeni_kalinlik.endswith(' CM'):
                yeni_kalinlik = yeni_kalinlik + ' CM'
        
        # Aynı kalınlık zaten varsa
        if yeni_kalinlik in KALINLIKLAR: 
            message = f"❌ Hata: Kalınlık **{yeni_kalinlik}** zaten mevcut."
            return redirect(url_for('index', message=message))

        # Kalınlıklar listesini güncelle
        KALINLIKLAR.append(yeni_kalinlik)
        save_kalinliklar(KALINLIKLAR)
        
        # Veritabanına stok kayıtlarını ekle
        conn = get_db_connection()
        cur = conn.cursor()
        for cinsi in CINSLER:
            for asama in ['Ham', 'Sivali']:
                cur.execute("""
                    INSERT INTO stok (cinsi, kalinlik, asama, m2) 
                    VALUES (%s, %s, %s, %s) 
                    ON CONFLICT (cinsi, kalinlik, asama) DO NOTHING
                """, (cinsi, yeni_kalinlik, asama, 0))
        
        conn.commit()
        message = f"✅ Yeni kalınlık **{yeni_kalinlik}** başarıyla eklendi ve stok kayıtları oluşturuldu."

    except ValueError as e: 
        message = f"❌ Giriş Hatası: {str(e)}"
    except Exception as e: 
        if conn: conn.rollback()
        message = f"❌ Veritabanı/Kaydetme Hatası: {str(e)}"
    finally: 
        if conn: conn.close()
        
    return redirect(url_for('index', message=message))


@app.route('/ayarla/urun_kodu', methods=['POST'])
def ayarla_urun_kodu():
    """Yeni bir ürün kodu ekler."""
    yeni_kod = request.form['yeni_urun_kodu'].strip().upper()
    cins_kalinlik_key = request.form['cinsi']
    urun_kodlari_map = load_data('urun_kodlari.json')
    message = ""
    try:
        tum_kodlar = [kod for kodlar in urun_kodlari_map.values() for kod in kodlar]
        if yeni_kod in tum_kodlar: message = f"❌ Hata: Ürün kodu **{yeni_kod}** zaten mevcut."
        else:
            if cins_kalinlik_key not in urun_kodlari_map: urun_kodlari_map[cins_kalinlik_key] = []
            urun_kodlari_map[cins_kalinlik_key].append(yeni_kod); urun_kodlari_map[cins_kalinlik_key].sort()
            save_data(urun_kodlari_map, 'urun_kodlari.json')
            message = f"✅ Ürün kodu **{yeni_kod}** ({cins_kalinlik_key}) başarıyla eklendi."
    except Exception as e: message = f"❌ Kaydetme Hatası: {str(e)}"
    return redirect(url_for('index', message=message))

# YENİ EK: TÜM VERİLERİ TEMİZLEME VE SIFIRLAMA ROTASI
@app.route('/temizle', methods=['GET'])
def temizle_veritabani():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Siparişleri sil
        cur.execute("DELETE FROM siparisler")
        # Stokları sil
        cur.execute("DELETE FROM stok")
        
        # YENİ: Kalınlıklar değişmiş olabileceği için VARYANTLAR'ı tekrar oluştur
        global KALINLIKLAR, VARYANTLAR
        KALINLIKLAR = load_kalinliklar()
        VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
        
        # Sıfır miktar ile varsayılan stokları yeniden ekle (init_db mantığı)
        for c, k in VARYANTLAR:
            for asama in ['Ham', 'Sivali']:
                cur.execute("""
                    INSERT INTO stok (cinsi, kalinlik, asama, m2) 
                    VALUES (%s, %s, %s, %s) 
                    ON CONFLICT (cinsi, kalinlik, asama) DO NOTHING
                """, (c, k, asama, 0))
                
        conn.commit()
        return redirect(url_for('index', message="✅ TÜM VERİLER SİLİNDİ ve STOKLAR SIFIRLANDI!"))
        
    except Exception as e:
        if conn: conn.rollback()
        return redirect(url_for('index', message=f"❌ Veritabanı Temizleme Hatası: {str(e)}"))
    finally:
        if conn: conn.close()

# --- 4. MOBİL İÇİN ROTALAR (JSON API ve HTML GÖRÜNÜMÜ) ---

@app.route('/api/stok', methods=['GET'])
def api_stok_verileri():
    """Mobil görünüm için stok, sipariş ve planlama verilerini JSON olarak döndürür."""
    conn = None
    try: # Hata yakalamayı başlat
        conn = get_db_connection()
        cur = conn.cursor()
        
        # YENİ: Kalınlıklar değişmiş olabileceği için VARYANTLAR'ı tekrar oluştur
        global KALINLIKLAR, VARYANTLAR
        KALINLIKLAR = load_kalinliklar()
        VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
        
        toplam_gerekli_siva, gunluk_siva_m2, siva_plan_detay, sevkiyat_plan_detay, stok_map = calculate_planning(conn)
        
        stok_data = {}
        deficit_analysis = {}

        for cinsi, kalinlik in VARYANTLAR:
            key = f"{cinsi} {kalinlik}"
            stok_data[f"{key} (Ham)"] = stok_map.get((cinsi, kalinlik), {}).get('Ham', 0)
            stok_data[f"{key} (Sivali)"] = stok_map.get((cinsi, kalinlik), {}).get('Sivali', 0)
            
            cur.execute(""" SELECT SUM(bekleyen_m2) as toplam_m2 FROM siparisler WHERE durum='Bekliyor' AND cinsi=%s AND kalinlik=%s """, (cinsi, kalinlik))
            bekleyen_m2_raw = cur.fetchone()
            
            gerekli_siparis_m2 = bekleyen_m2_raw['toplam_m2'] if bekleyen_m2_raw and bekleyen_m2_raw['toplam_m2'] else 0
            sivali_stok = stok_map.get((cinsi, kalinlik), {}).get('Sivali', 0)
            ham_stok = stok_map.get((cinsi, kalinlik), {}).get('Ham', 0)
            sivali_eksik = max(0, gerekli_siparis_m2 - sivali_stok)
            ham_eksik = max(0, sivali_eksik - ham_stok)
            
            if gerekli_siparis_m2 > 0:
                deficit_analysis[key] = {
                    'sivali_deficit': sivali_eksik,
                    'ham_deficit': ham_eksik,
                    'ham_coverage': max(0, sivali_eksik - max(0, sivali_eksik - ham_stok)) 
                }

        cur.execute("SELECT * FROM siparisler ORDER BY termin_tarihi ASC, siparis_tarihi DESC")
        siparisler = cur.fetchall()
        
        # Tarih alanlarını JSON uyumlu string'e çevir (KRİTİK DÜZELTME)
        siparis_listesi = []
        for s in siparisler:
            s_dict = dict(s) 
            if 'siparis_tarihi' in s_dict and s_dict['siparis_tarihi']:
                s_dict['siparis_tarihi'] = s_dict['siparis_tarihi'].isoformat()
            if 'termin_tarihi' in s_dict and s_dict['termin_tarihi']:
                s_dict['termin_tarihi'] = s_dict['termin_tarihi'].isoformat()
            siparis_listesi.append(s_dict)

        cur.close()
        conn.close()

        # Mobil arayüzün beklediği tüm veriyi döndür
        return jsonify({
            'stok': stok_data,
            'deficit_analysis': deficit_analysis,
            'siparisler': siparis_listesi,
            'toplam_gerekli_siva': toplam_gerekli_siva,
            'gunluk_siva_m2': gunluk_siva_m2,
            'siva_plan_detay': dict(siva_plan_detay), 
            'sevkiyat_plan_detay': dict(sevkiyat_plan_detay) 
        })
    
    except Exception as e:
        print(f"--- KRİTİK HATA LOGU (api_stok_verileri) ---")
        print(f"Hata Tipi: {type(e).__name__}")
        print(f"Hata Mesajı: {str(e)}")
        # Tarayıcıya 500 hatası döndür, hata detayını API yanıtına ekle.
        return jsonify({'error': 'Sunucu Hatası', 'detail': f"API hatası: {str(e)} - Logları Kontrol Edin"}), 500
    finally:
        if conn: conn.close()


@app.route('/mobil', methods=['GET'])
def mobil_gorunum():
    """
    Telefonlar için tasarlanmış, veri girişi içermeyen 
    stok_goruntule.html şablonunu templates/ klasöründen sunar.
    """
    return render_template('stok_goruntule.html')


# --- HTML ŞABLONU (PC Arayüzü) ---

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="tr">
<head>
    <title>EPS Panel Yönetimi</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f9; color: #333; }
        .container { max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 0 15px rgba(0, 0, 0, 0.1); }
        h1, h2, h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }

        /* --- ÇERÇEVELİ FORM STİLİ --- */
        .form-box { 
            border: 2px solid #007bff; 
            padding: 15px; 
            border-radius: 8px; 
            background-color: #e6f0ff; /* Hafif mavi arka plan */
            margin-bottom: 20px;
        }
        .form-box h2 { 
            margin-top: 0; 
            border-bottom: 2px solid #007bff; 
            color: #007bff;
            font-size: 1.3em;
            padding-bottom: 8px;
        }
        .form-box .form-section { background: none; padding: 0; margin-bottom: 10px; }
        
        /* --- DİĞER STİLLER --- */
        table { width: 100%; border-collapse: collapse; margin-top: 10px; table-layout: fixed; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.9em; word-wrap: break-word; }
        th { background-color: #007bff; color: white; }
        .message { padding: 10px; margin-bottom: 15px; border-radius: 4px; font-weight: bold; }
        .success { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
        .error { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
        .deficit-ham { color: red; font-weight: bold; } 
        .deficit-sivali { color: darkred; font-weight: bold; } 
        
        button { background-color: #007bff; color: white; padding: 8px 12px; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        
        input[type="number"], input[type="text"], input[type="date"], select { 
            padding: 8px; /* Daha dolgun */
            margin: 5px 5px 5px 0;
            border: 1px solid #ccc; 
            border-radius: 4px; 
            box-sizing: border-box; /* Responsive uyum */
        }
        
        .siparis-satir { 
            display: flex; 
            gap: 10px; 
            align-items: center; 
            margin-bottom: 10px;
            padding: 8px;
            border: 1px dotted #ccc;
            border-radius: 4px;
        }
        .siparis-satir button { padding: 4px 8px; font-size: 0.8em; }

        /* Tablo Genişlikleri ve Kaydırma */
        .table-responsive { overflow-x: auto; margin-top: 15px; }
        .siparis-table { min-width: 1100px; table-layout: auto; }
        .siparis-table th:nth-child(10) { width: 250px; } /* İşlem sütununu genişletiyoruz */
    </style>
    <script>
        const CINS_TO_BOYALI_MAP = {{ CINS_TO_BOYALI_MAP | tojson }};

        // KRİTİK DÜZELTME: JINJA2 ile statik seçenekler oluşturuluyor ve JavaScript'e aktarılıyor.
        const CINSLER = {{ CINSLER | tojson }};
        const KALINLIKLAR = {{ KALINLIKLAR | tojson }};
        
        const CINS_OPTIONS = CINSLER.map(c => `<option value="\${c}">\${c}</option>`).join('');
        const KALINLIK_OPTIONS = KALINLIKLAR.map(k => `<option value="\${k}">\${k}</option>`).join('');

        // Satır şablonu (index yerine placeholder kullanıyoruz)
        const ROW_TEMPLATE = (index) => `
            <div class="siparis-satir" data-index="\${index}">
                <select class="cinsi_select" name="cinsi_\${index}" required onchange="filterProductCodes(this)" style="width: 120px;">
                    <option value="">Cins Seçin</option>
                    \${CINS_OPTIONS}
                </select>
                <select class="kalinlik_select" name="kalinlik_\${index}" required onchange="filterProductCodes(this)" style="width: 90px;">
                    <option value="">Kalınlık Seçin</option>
                    \${KALINLIK_OPTIONS}
                </select>
                <select class="urun_kodu_select" name="urun_kodu_\${index}" required style="width: 100px;">
                    <option value="">Ürün Kodu Seçin</option>
                </select>
                <input type="number" name="m2_\${index}" min="1" required placeholder="M²" style="width: 70px;">
                <button type="button" onclick="removeRow(this)" style="background-color: #dc3545; width: auto;">X</button>
            </div>
        `;


        // --- ÜRÜN KODU FİLTRELEME MANTIĞI ---
        function filterProductCodes(selectElement) {
            const container = selectElement.closest('.siparis-satir');
            const cinsiSelect = container.querySelector('.cinsi_select');
            const kalinlikSelect = container.querySelector('.kalinlik_select');
            const urunKoduSelect = container.querySelector('.urun_kodu_select');
            
            const cinsi = cinsiSelect.value;
            const kalinlik = kalinlikSelect.value;
            urunKoduSelect.innerHTML = '<option value="">Ürün Kodu Seçin</option>'; 
            
            if (cinsi && kalinlik) {
                const key = cinsi + ' ' + kalinlik;
                const codes = CINS_TO_BOYALI_MAP[key] || [];
                
                if (codes.length > 0) {
                    codes.forEach(code => {
                        const option = document.createElement('option');
                        option.value = code;
                        option.textContent = code;
                        urunKoduSelect.appendChild(option);
                    });
                } else {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = 'Kod bulunamadı';
                    urunKoduSelect.appendChild(option);
                }
            }
        }

        // --- ÇOKLU SİPARİŞ SATIRI EKLEME/ÇIKARMA MANTIĞI ---
        let siparisSatirIndex = 0;
        
        function addRow(count = 1) {
            const container = document.getElementById('siparis-urun-container');
            for (let i = 0; i < count; i++) {
                const newHtml = ROW_TEMPLATE(siparisSatirIndex);
                container.insertAdjacentHTML('beforeend', newHtml);
                
                // Yeni eklenen satırdaki kodları filtrele (seçenekleri yüklemek için)
                const newRow = container.querySelector(`[data-index="\${siparisSatirIndex}"]`);
                const cinsiSelect = newRow.querySelector('.cinsi_select');
                
                // Başlangıçta boş seçenekler olduğu için otomatik filtrelemeye gerek yok.
                // filterProductCodes(cinsiSelect); 

                siparisSatirIndex++;
            }
        }

        function removeRow(buttonElement) {
            const row = buttonElement.closest('.siparis-satir');
            row.remove();
        }

        // --- DÜZENLEME MODAL FONKSİYONU ---
        function openEditModal(id, cinsi, kalinlik, m2, urun_kodu) {
            const yeni_m2 = prompt(`Sipariş ID ${id} için yeni M² miktarını girin (Mevcut: ${m2}):`);
            
            if (yeni_m2 !== null && !isNaN(parseInt(yeni_m2))) {
                const yeni_urun_kodu = prompt(`Sipariş ID ${id} için yeni Ürün Kodunu girin (Mevcut: ${urun_kodu}):`, urun_kodu);
                
                if (yeni_urun_kodu !== null) {
                    // Cins ve kalınlık bilgileri urun_kodu'ndan otomatik çekileceği için formda göndermeye gerek yok
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = '/siparis';
                    
                    form.innerHTML = `
                        <input type="hidden" name="action" value="duzenle_siparis">
                        <input type="hidden" name="siparis_id" value="${id}">
                        <input type="hidden" name="yeni_m2" value="${parseInt(yeni_m2)}">
                        <input type="hidden" name="yeni_urun_kodu" value="${yeni_urun_kodu}">
                    `;
                    
                    document.body.appendChild(form);
                    form.submit();
                }
            } else if (yeni_m2 !== null) {
                alert('Lütfen geçerli bir M² miktarı girin.');
            }
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            // İlk açılışta 5 satırı otomatik ekle (İstenen Özellik)
            addRow(5); 
            
            // İlk satırdaki Cins ve Kalınlık seçimine göre Ürün Kodlarını yükle (Opsiyonel)
            // const firstRowSelect = document.querySelector('.cinsi_select');
            // if(firstRowSelect) filterProductCodes(firstRowSelect);
        });
    </script>
</head>
<body>
    <div class="container">
        <h1>🏭 EPS Panel Üretim ve Sipariş Yönetimi</h1>
        <p style="font-style: italic;">*Tüm giriş ve çıkışlar Metrekare (m²) cinsindendir.</p>
        <p style="font-weight: bold; color: #007bff;">
            Mobil Görüntüleme Adresi: <a href="{{ url_for('mobil_gorunum') }}">/mobil</a>
            <span style="margin-left: 20px;">
                <a href="{{ url_for('temizle_veritabani') }}" onclick="return confirm('UYARI: Tüm Stok ve Sipariş verileri kalıcı olarak SIFIRLANACAKTIR! Emin misiniz?')" style="color: red; font-weight: bold;">[VERİTABANINI TEMİZLE]</a>
            </span>
        </p>
        {% if message %}
            <div class="message {% if 'Hata' in message or 'Yetersiz' in message %}error{% else %}success{% endif %}">{{ message }}</div>
        {% endif %}
        
        <div class="grid">
            
                        <div class="form-box" style="grid-column: 1 / span 1;">
                <h2>2. Yeni Sipariş Girişi (Çoklu Ürün)</h2>
                <form action="/siparis" method="POST">
                    <input type="hidden" name="action" value="yeni_siparis">
                    
                                        <div class="form-section">
                        <input type="text" name="musteri" required placeholder="Müşteri Adı" style="width: 98%;">
                        <label style="font-size: 0.9em; margin-top: 5px; display: block;">Sipariş Tarihi: <input type="date" name="siparis_tarihi" value="{{ today }}" required style="width: calc(50% - 8px);"></label>
                        <label style="font-size: 0.9em; margin-top: 5px; display: block;">Termin Tarihi: <input type="date" name="termin_tarihi" required style="width: calc(50% - 8px);"></label>
                    </div>
                    
                                        <div style="font-weight: bold; margin-top: 15px; border-bottom: 1px dashed #007bff; padding-bottom: 5px;">Ürün Kodları ve Metraj (M²)</div>
                    <div id="siparis-urun-container" style="margin-top: 10px;">
                                            </div>
                    
                    <button type="button" onclick="addRow(1)" style="background-color: #28a745; margin-bottom: 15px; width: 100%;">+ Ürün Satırı Ekle</button>
                    
                    <button type="submit" style="background-color:#00a359; width: 100%;">Tüm Siparişleri Kaydet</button>
                </form>
            </div>
            
                        <div class="form-box" style="grid-column: 2 / span 1; border-color: #6c757d; background-color: #f8f9fa;">
                <h2>1. Stok Hareketleri</h2>
                <div class="form-section">
                    <div class="kapasite-box">
                        <h3>⚙️ Günlük Sıva Kapasitesi Ayarı</h3>
                        <form action="/ayarla/kapasite" method="POST" style="display:flex; flex-wrap:wrap; align-items:center;">
                            <input type="number" name="kapasite_m2" min="1" required placeholder="M2" value="{{ gunluk_siva_m2 }}" style="width: 80px;">
                            <span style="margin-right: 10px;">m² / Gün</span>
                            <button type="submit" style="background-color:#cc8400;">Kapasiteyi Kaydet</button>
                        </form>
                    </div>
                    
                                        <div class="kapasite-box" style="margin-top: 15px; background-color: #ffe0b2;">
                        <h3>📏 Yeni Zemin Kalınlığı Ekle</h3>
                        <form action="/ayarla/kalinlik" method="POST" style="display:flex; flex-wrap:wrap; align-items:center;">
                            <input type="text" name="yeni_kalinlik" required placeholder="Örn: 1.1 veya 10" style="width: 120px;">
                            <span style="margin-right: 10px;">CM (Otomatik Eklenir)</span>
                            <button type="submit" style="background-color:#e65100;">Kalınlık Ekle</button>
                        </form>
                    </div>
                    
                                        <div class="kapasite-box" style="margin-top: 15px; background-color: #d8f5ff;">
                        <h3>➕ Yeni Ürün Kodu Ekle</h3>
                        <form action="/ayarla/urun_kodu" method="POST" style="display:flex; flex-wrap:wrap; align-items:center;">
                            <input type="text" name="yeni_urun_kodu" required placeholder="Örn: L1709" style="width: 100px;">
                            <select name="cinsi" required style="width: 150px;">
                                {% for c in CINSLER %}
                                    {% for k in KALINLIKLAR %}
                                        {% set key = c + " " + k %}
                                        <option value="{{ key }}">{{ key }}</option>
                                    {% endfor %}
                                {% endfor %}
                            </select>
                            <button type="submit" style="background-color:#17a2b8;">Kodu Ekle</button>
                        </form>
                    </div>
                    <hr style="margin-top: 15px; margin-bottom: 15px;">
                    <h4>Stok İşlemi Gerçekleştir</h4>
                    <form action="/islem" method="POST">
                        <select name="action" required style="width: 100%;">
                            <option value="ham_alim">1 - Ham Panel Alımı (Stoğa Ekle)</option>
                            <option value="siva_uygula">2 - Sıva Uygulama (Ham -> Sıvalı Üretim)</option>
                            <option value="sat_sivali">4 - Sıvalı Panel Satışı</option>
                            <option value="sat_ham">3 - Ham Panel Satışı</option>
                            <option value="iptal_ham_alim">5 - Ham Alımı İptal (Ham Stoktan Çıkar)</option>
                            <option value="iptal_siva">6 - Sıva İşlemi Geri Al (Sıvalı -> Ham)</option>
                            <option value="iptal_sat_ham">7 - Ham Satışını Geri Al (Ham Stoğa Ekle)</option>
                            <option value="iptal_sat_sivali">8 - Sıvalı Satışını Geri Al (Sıvalı Stoğa Ekle)</option>
                        </select>
                        <select name="cinsi" required style="width: 48%;">
                            {% for c in CINSLER %}
                                <option value="{{ c }}">{{ c }}</option>
                            {% endfor %}
                        </select>
                        <select name="kalinlik" required style="width: 48%;">
                            {% for k in KALINLIKLAR %}
                                <option value="{{ k }}">{{ k }}</option>
                            {% endfor %}
                        </select>
                        <input type="number" name="m2" min="1" required placeholder="M2" style="width: 100%;">
                        <button type="submit" style="width: 100%;">İşlemi Kaydet</button>
                    </form>
                </div>
            </div>
            
        </div>
        <hr>
        <h2 class="plan-header">🚀 Üretim Planlama Özeti (Kapasite: {{ gunluk_siva_m2 }} m²/gün)</h2>
        {% if toplam_gerekli_siva > 0 %}
            <p style="font-weight: bold; color: darkred;">Mevcut siparişleri karşılamak için toplam Sıvalı M² eksiği: {{ toplam_gerekli_siva }} m²</p>
        {% else %}
            <p style="font-weight: bold; color: green;">Sıvalı malzeme ihtiyacı stoktan karşılanabiliyor. (Toplam bekleyen sipariş {{(siparisler|selectattr('durum', '==', 'Bekliyor')|map(attribute='bekleyen_m2')|sum)}} m²)</p>
        {% endif %}
        <div class="grid">
            <div class="form-box" style="border-color: #28a745; background-color: #e9fff5;">
                <h3>🧱 Sıva Üretim Planı (Önümüzdeki 5 İş Günü)</h3>
                <table class="plan-table">
                    <tr><th>Gün</th><th>Planlanan M²</th></tr>
                    {% for gun, plan_details in siva_plan_detay.items() %}
                        {% set total_m2 = plan_details|sum(attribute='m2') %}
                        <tr>
                            <td>Gün {{ gun }}</td>
                            <td>
                                <b>{{ total_m2 }} m²</b>
                                <ul style="list-style-type: none; padding-left: 10px; margin: 0;">
                                    {% for item in plan_details %}
                                        <li style="font-size: 0.9em; color: #333;">{{ item.cinsi }}: {{ item.m2 }} m²</li>
                                    {% endfor %}
                                </ul>
                            </td>
                        </tr>
                    {% else %}
                        <tr><td colspan="2">Önümüzdeki 5 gün için Sıva ihtiyacı bulunmamaktadır.</td></tr>
                    {% endfor %}
                </table>
            </div>
            <div class="form-box" style="border-color: #ffc107; background-color: #fff8e6;">
                <h3>🚚 Sevkiyat Planı (Önümüzdeki 5 Takvim Günü)</h3>
                {% if sevkiyat_plan_detay %}
                    {% for tarih, sevkiyatlar in sevkiyat_plan_detay.items() %}
                        <h4 style="margin-top: 10px; margin-bottom: 5px; color: #ffc107;">{{ tarih }} (Toplam: {{ sevkiyatlar|sum(attribute='bekleyen_m2') }} m²)</h4>
                        <ul style="list-style-type: none; padding-left: 10px; margin: 0;">
                            {% for sevkiyat in sevkiyatlar %}
                                <li style="margin: 0 0 3px 0; font-size: 0.9em;">
                                    - **{{ sevkiyat.urun_kodu }}** ({{ sevkiyat.bekleyen_m2 }} m²) -> Müşteri: {{ sevkiyat.musteri }}
                                </li>
                            {% endfor %}
                        </ul>
                    {% endfor %}
                {% else %}
                    <p>Önümüzdeki 5 gün terminli sevkiyat bulunmamaktadır.</p>
                {% endif %}
            </div>
        </div>
        <h2>3. Detaylı Stok Durumu ve Eksik Planlama (M²)</h2>
        <table class="stok-table">
            <tr>
                <th>Cinsi</th>
                <th>Kalınlık</th>
                <th>Ham M²</th>
                <th>Sıvalı M²</th>
                <th style="background-color: #b0e0e6;">Toplam Bekleyen Sipariş M²</th>
                <th style="background-color: #ffcccc;">Sıvalı Eksik (Üretilmesi Gereken M²)</th>
                <th style="background-color: #f08080;">Ham Eksik (Ham Alımı Gereken M²)</th>
            </tr>
            {% for stok in stok_list %}
            <tr>
                <td>{{ stok.cinsi }}</td>
                <td>{{ stok.kalinlik }}</td>
                <td>{{ stok.ham_m2 }}</td>
                <td>{{ stok.sivali_m2 }}</td>
                <td>{{ stok.gerekli_siparis_m2 }}</td>
                <td class="{% if stok.sivali_eksik > 0 %}deficit-sivali{% endif %}">{{ stok.sivali_eksik }}</td>
                <td class="{% if stok.ham_eksik > 0 %}deficit-ham{% endif %}">{{ stok.ham_eksik }}</td>
            </tr>
            {% endfor %}
        </table>
        
        <h2 style="margin-top: 30px;">4. Sipariş Listesi</h2>
        <div class="table-responsive">
        <table class="siparis-table">
            <tr>
                <th>ID</th>
                <th>Kod</th>
                <th>Ürün</th>
                <th>Müşteri</th>
                <th>Sipariş Tarihi</th>
                <th>Termin Tarihi</th>
                <th>Bekleyen M²</th>
                <th>Durum</th>
                <th>Planlanan İş Günü (Sıva)</th>
                <th>İşlem</th>
            </tr>
            {% for siparis in siparisler %}
            <tr class="{{ 'siparis-tamamlandi' if siparis.durum == 'Tamamlandi' else ('siparis-iptal' if siparis.durum == 'Iptal' else '') }}">
                <td>{{ siparis.id }}</td>
                <td>{{ siparis.siparis_kodu }}</td>
                <td>{{ siparis.urun_kodu }} ({{ siparis.cinsi }} {{ siparis.kalinlik }})</td>
                <td>{{ siparis.musteri }}</td>
                <td>{{ siparis.siparis_tarihi }}</td>
                <td>{{ siparis.termin_tarihi }}</td>
                <td>{{ siparis.bekleyen_m2 }}</td>
                <td>{{ siparis.durum }}</td>
                <td>
                    {% if siparis.durum == 'Bekliyor' %}
                        {% if siparis.planlanan_is_gunu == 0 %}
                            <span style="color:green; font-weight:bold;">Hemen Stoktan (0)</span>
                        {% elif siparis.planlanan_is_gunu > 0 %}
                            <span style="color:darkorange; font-weight:bold;">Gün {{ siparis.planlanan_is_gunu }}</span>
                        {% else %}
                            Planlanamaz (Kapasite Yok)
                        {% endif %}
                    {% else %}
                        -
                    {% endif %}
                </td>
                <td>
                    {% if siparis.durum == 'Bekliyor' %}
                                                <button onclick="openEditModal({{ siparis.id }}, '{{ siparis.cinsi }}', '{{ siparis.kalinlik }}', {{ siparis.bekleyen_m2 }}, '{{ siparis.urun_kodu }}')" style="background-color: orange; padding: 4px 8px; margin-right: 5px;">Düzenle</button>
                        
                                                <form action="/siparis" method="POST" style="display:inline-block;" onsubmit="return confirm('Sipariş ID {{ siparis.id }} kalıcı olarak silinecektir. Emin misiniz?');">
                            <input type="hidden" name="action" value="sil_siparis">
                            <input type="hidden" name="siparis_id" value="{{ siparis.id }}">
                            <button type="submit" style="background-color: darkred; padding: 4px 8px; margin-right: 5px;">Kalıcı Sil</button>
                        </form>
                        
                                                <form action="/siparis" method="POST" style="display:inline-block;">
                            <input type="hidden" name="action" value="tamamla_siparis">
                            <input type="hidden" name="siparis_id" value="{{ siparis.id }}">
                            <button type="submit" style="background-color: green; padding: 4px 8px;">Tamamla</button>
                        </form>
                    {% else %}
                        -
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
        </div>
    </div>
</body>
</html>
'''