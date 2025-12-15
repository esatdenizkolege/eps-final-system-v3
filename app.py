# -*- coding: utf-8 -*-

import os

from flask import Flask, render_template_string, request, redirect, url_for, jsonify, render_template, flash
import traceback

# PostgreSQL'e bağlanmak için psycopg2 kütüphanesini kullanıyoruz.
import psycopg2 
from psycopg2.extras import RealDictCursor 

# Yerel geliştirme için SQLite
import sqlite3
 

import json
import unicodedata

from datetime import datetime, timedelta

from collections import defaultdict

import math

from flask_cors import CORS 

# --- UYGULAMA YAPILANDIRMASI ---

# Render'ın kullandığı PORT'u alır, yerelde 5000 kullanılır.
PORT = int(os.environ.get('PORT', 5000)) 
app = Flask(__name__)
# Flash mesajları için gerekli
app.secret_key = 'super_secret_key_change_me' 

# Mobil erişim (CORS) için gereklidir.
CORS(app) 

# PostgreSQL bağlantı URL'sini ortam değişkeninden oku. 
DATABASE_URL = os.environ.get("DATABASE_URL")

# JSON dosyaları hala yerel diskte tutuluyor.
KAPASITE_FILE = 'kapasite.json' 
KALINLIK_FILE = 'kalinliklar.json' # Kalınlıkları tutmak için dosya
CINS_FILE = 'cin_listesi.json' # Cins listesini dinamik tutmak için dosya
# Önbellekleme (caching) sorunlarını azaltmak için ayar.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0 

# --- 0. SABİT TANIMLAMALAR VE DİNAMİK YÜKLEME ---

# Varsayılanlar ve ZORUNLU EKLENEN CİNSLERİ İÇEREN LİSTE
DEFAULT_KALINLIKLAR = ['2 CM', '3.6 CM', '3 CM', '4 CM'] # 4 CM'yi zorla ekledik
DEFAULT_CINSLER = ['BAROK', 'YATAY TAŞ', 'DÜZ TUĞLA', 'KAYRAK TAŞ', 'PARKE TAŞ', 'KIRIK TAŞ', 'BUZ TAŞ', 'MERMER', 'LB ZEMİN', 'LA', 'LBX', 'LATA LB'] # Yeni cinsleri zorla ekledik

# --- JSON/KAPASITE/ÜRÜN KODU YÖNETİMİ ---

def save_data(data, filename):
    """JSON verisini kaydeder."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def normalize_nfc(text):
    """Metni NFC formuna (composed) normalize eder."""
    if isinstance(text, str):
        return unicodedata.normalize('NFC', text)
    return text

def load_data(filename):
    """JSON verisini yükler ve yoksa varsayılan değerleri döndürür."""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                # Normalize string data immediately upon load
                if filename == 'urun_kodlari.json':
                    return {normalize_nfc(k): [normalize_nfc(v) for v in vals] for k, vals in data.items()}
                if filename == CINS_FILE:
                    return {'cinsler': [normalize_nfc(c) for c in data.get('cinsler', [])]}
                if filename == KALINLIK_FILE:
                    return {'kalinliklar': [normalize_nfc(k) for k in data.get('kalinliklar', [])]}
                return data
            except json.JSONDecodeError as e:
                # KRİTİK DÜZELTME: JSON okuma hatasını yakala ve logla
                print(f"KRİTİK HATA: {filename} dosyasinda JSONDecodeError: {e}")
                if filename == 'urun_kodlari.json': return load_data_from_app_defaults(filename)
                if filename == KALINLIK_FILE: return {'kalinliklar': DEFAULT_KALINLIKLAR}
                if filename == CINS_FILE: return {'cinsler': DEFAULT_CINSLER}
                if filename == KAPASITE_FILE: return {"gunluk_siva_m2": 600}
                return {} # Varsayılan boş değer döndür
    
    # Yoksa varsayılan veriyi döndür
    return load_data_from_app_defaults(filename)

def load_data_from_app_defaults(filename):
    """Dosya diskte yoksa veya JSON hatası varsa uygulamanın varsayılanlarını döndürür."""
    if filename == KAPASITE_FILE:
        return {"gunluk_siva_m2": 600}
    
    if filename == CINS_FILE:
        save_data({'cinsler': DEFAULT_CINSLER}, CINS_FILE)
        return {'cinsler': DEFAULT_CINSLER}

    if filename == 'urun_kodlari.json':
        urun_kodlari_data = {
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
            'LBX 4 CM': ['LBX-E-001', 'LBX-E-002', 'LBX-E-003'], 
            'LATA LB 4 CM': ['LATA-E-001', 'LBX-E-002', 'LATA-E-003'],
        }
        # Not: Bu, sadece dosya yoksa/bozuksa varsayılanı yükler. 
        # Diskte bir JSON hatası yoksa, yukarıdaki load_data() başarılı olacaktır.
        return urun_kodlari_data
    
    if filename == KALINLIK_FILE:
        save_data({'kalinliklar': DEFAULT_KALINLIKLAR}, KALINLIK_FILE)
        return DEFAULT_KALINLIKLAR

    return {}

def load_kalinliklar():
    """Kalınlık listesini JSON'dan yükler, yoksa varsayılanı kullanır ve kaydeder."""
    data = load_data(KALINLIK_FILE)
    return data.get('kalinliklar', DEFAULT_KALINLIKLAR)

def save_kalinliklar(kalinliklar):
    """Kalınlık listesini JSON'a kaydeder."""
    save_data({'kalinliklar': kalinliklar}, KALINLIK_FILE)

def load_cinsler():
    """Cins listesini JSON'dan yükler."""
    return load_data(CINS_FILE).get('cinsler', DEFAULT_CINSLER)

def save_cinsler(cinsler):
    """Cins listesini JSON'a kaydeder."""
    save_data({'cinsler': cinsler}, CINS_FILE)
    
# Dinamik olarak yükle (Uygulama başlatıldığında güncel kalınlıklar ve cinsler yüklenir)
KALINLIKLAR = load_kalinliklar()
CINSLER = load_cinsler() 
VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]

# Veri haritalarını yükle
CINS_TO_BOYALI_MAP = load_data('urun_kodlari.json')
URUN_KODLARI = sorted(list(set(code for codes in CINS_TO_BOYALI_MAP.values() for code in codes)))


# --- 1. VERİTABANI İŞLEMLERİ VE BAŞLANGIÇ (POSTGRESQL + SQLITE) ---

class SQLiteCursorWrapper:
    """
    SQLite cursor'ını sarar ve PostgreSQL tarzı (%s) sorguları SQLite tarzına (?) çevirir.
    Ayrıca fetch işlemlerini yönetir.
    """
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        # Postgres %s yer tutucularını SQLite ? ile değiştir
        sql_sqlite = sql.replace('%s', '?')
        
        # PostgreSQL SERIAL -> SQLite INTEGER PRIMARY KEY AUTOINCREMENT
        if "SERIAL PRIMARY KEY" in sql_sqlite.upper():
            sql_sqlite = sql_sqlite.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        
        # PostgreSQL ILIKE -> SQLite LIKE (Yerel geliştirme için yeterli)
        sql_sqlite = sql_sqlite.replace(' ILIKE ', ' LIKE ')
        
        # Helper to convert params if necessary (e.g. Booleans to 0/1 if SQLite doesn't handle them automatically)
        # SQLite handles True/False as 1/0 usually, but safer to force if needed.
        # psycopg2 adapts automatically. sqlite3 default adapter works for standard types.
        
        try:
            return self.cursor.execute(sql_sqlite, params if params is not None else ())
        except Exception as e:
            print(f"SQLite Execute Error: {e} | SQL: {sql_sqlite}")
            raise e

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()
        
    @property
    def rowcount(self):
        return self.cursor.rowcount
        
    @property
    def description(self):
        return self.cursor.description

class SQLiteConnectionWrapper:
    """SQLite bağlantısını sarar ve cursor() çağrıldığında wrapper döndürür."""
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return SQLiteCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

def get_db_connection():
    """Veritabanı bağlantısını açar (Render'da Postgres, Yerelde SQLite)."""
    
    if DATABASE_URL:
        # Render / Production (PostgreSQL)
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            return conn
        except Exception as e:
            print(f"PostgreSQL Bağlantı Hatası: {e}")
            raise e
    else:
        # Yerel Geliştirme (SQLite)
        # RealDictCursor gibi davranması için row_factory tanımlıyoruz
        def dict_factory(cursor, row):
            d = {}
            for idx, col in enumerate(cursor.description):
                d[col[0]] = row[idx]
            return d

        conn = sqlite3.connect('envanter.db') # Yerel dosya
        conn.row_factory = dict_factory
        return SQLiteConnectionWrapper(conn)

def init_db():
    """Veritabanını ve tabloları oluşturur."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Stok Tablosu
        # Not: Wrapper sınıfı SERIAL -> INTEGER PRIMARY KEY dönüşümünü halleder.
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
        # Siparişler Tablosu
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

        # Sipariş Geçmişi Tablosu (Kısmi Tamamlama Logları)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS siparis_gecmisi (
                id SERIAL PRIMARY KEY,
                siparis_id INTEGER NOT NULL,
                islem_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                islem_tipi TEXT NOT NULL, -- 'Kismi', 'GeriAl' vb.
                miktar INTEGER NOT NULL,
                FOREIGN KEY (siparis_id) REFERENCES siparisler(id) ON DELETE CASCADE
            );
        """)

        # YENİ: Cinsler ve Kalınlıklar değişebileceği için VARYANTLAR'ı yeniden hesapla
        global KALINLIKLAR, CINSLER, VARYANTLAR
        KALINLIKLAR = load_kalinliklar()
        CINSLER = load_cinsler()
        VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
        
        # Varsayılan stok girişleri (EĞER YOKSA ekle)
        for c, k in VARYANTLAR:
            temiz_c = c.strip().upper()
            temiz_k = k.strip().upper()
            for asama in ['Ham', 'Sivali']:
                cur.execute("""
                    INSERT INTO stok (cinsi, kalinlik, asama, m2) 
                    VALUES (%s, %s, %s, %s) 
                    ON CONFLICT (cinsi, kalinlik, asama) DO NOTHING
                """, (temiz_c, temiz_k, asama, 0))
        
        conn.commit()
        cur.close()
        conn.close()
        print("Veritabanı başarıyla başlatıldı (Mod: " + ("PostgreSQL" if DATABASE_URL else "SQLite") + ").")
    except Exception as e:
        print(f"Veritabanı Başlatma Hatası: {e}")

with app.app_context():
    init_db()
    
    # Başlangıçta JSON dosyalarının varlığını kontrol et ve yoksa varsayılanı yükle
    if not os.path.exists(KAPASITE_FILE):
        save_data({"gunluk_siva_m2": 600}, KAPASITE_FILE)
    if not os.path.exists('urun_kodlari.json'):
        save_data(CINS_TO_BOYALI_MAP, 'urun_kodlari.json')
    if not os.path.exists(CINS_FILE): 
        save_data({'cinsler': DEFAULT_CINSLER}, CINS_FILE)
    if not os.path.exists(KALINLIK_FILE):
        save_data({'kalinliklar': DEFAULT_KALINLIKLAR}, KALINLIK_FILE)


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
        
        # STOK ANAHTAR OLUŞTURMA: Her zaman temiz (strip, upper)
        for row in stok_raw:
            key = (row['cinsi'].strip().upper(), row['kalinlik'].strip().upper())
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
        # Mevcut sıvalı stoğun bir kopyasını al, siparişleri karşılarken bu kopyayı azaltacağız
        temp_stok_sivali = {k: v.get('Sivali', 0) for k, v in stok_map.items()}
        
        for siparis in bekleyen_siparisler:
            
            # YENİ EK GÜVENLİK: Sorgu sonucunu döngüden hemen önce Python'da zorla temizle
            siparis['cinsi'] = siparis['cinsi'].strip().upper()
            siparis['kalinlik'] = siparis['kalinlik'].strip().upper()
            
            # SİPARİŞ ANAHTAR OLUŞTURMA: Her zaman temiz (KeyError'ı engellemek ve eşleşmeyi sağlamak için)
            temiz_cinsi = siparis['cinsi'].strip().upper()
            temiz_kalinlik = siparis['kalinlik'].strip().upper()
            key = (temiz_cinsi, temiz_kalinlik)
            
            # Key'in stok haritasında var olmasını kontrol ediyoruz
            stok_sivali_available = temp_stok_sivali.get(key, 0)
            gerekli_m2 = siparis['bekleyen_m2']
            
            # 1. Sıvalı Stoku Tüket
            karsilanan_sivali = min(gerekli_m2, stok_sivali_available)
            kalan_ihtiyac = gerekli_m2 - karsilanan_sivali
            
            # Sıvalı stoğu azalt
            if key in temp_stok_sivali:
                temp_stok_sivali[key] -= karsilanan_sivali

            # 2. Üretim İhtiyacını Hesapla (Ham Stoku Dikkate Almadan, sadece Sıva)
            eksik_sivali = kalan_ihtiyac 
            
            if eksik_sivali > 0:
                # KRİTİK DÜZELTME: Aynı ürünün ihtiyaçlarını birleştirmek için kontrol
                found = False
                for item in siva_uretim_ihtiyaci:
                    if item['key'] == f"{temiz_cinsi} {temiz_kalinlik}":
                        item['m2'] += eksik_sivali
                        found = True
                        break
                if not found:
                    siva_uretim_ihtiyaci.append({
                        'key': f"{temiz_cinsi} {temiz_kalinlik}",
                        'm2': eksik_sivali
                    })
                
            toplam_gerekli_siva += eksik_sivali 
            
            # Planlanan İş Günü hesaplaması
            current_total_siva_needed = sum(item['m2'] for item in siva_uretim_ihtiyaci)
            is_gunu = math.ceil(current_total_siva_needed / kapasite) if kapasite > 0 else -1
            planlama_sonuclari[siparis['id']] = is_gunu if current_total_siva_needed > 0 else 0 

        # Hesaplanan iş günlerini veritabanına kaydet
        for siparis_id, is_gunu in planlama_sonuclari.items():
            cur.execute("UPDATE siparisler SET planlanan_is_gunu = %s WHERE id = %s", (is_gunu, siparis_id))
        conn.commit()
        
        # --- Kapasiteyi Ürün Bazında Dağıtma ---
        
        # siva_uretim_sirasli_ihtiyac: Sipariş sırasını koruyan, henüz sıvanmamış ihtiyacı tutar.
        siva_uretim_sirasli_ihtiyac = []
        temp_sivali_stok_kopyasi = {k: v.get('Sivali', 0) for k, v in stok_map.items()}

        for siparis in bekleyen_siparisler:
            
            # YENİ EK GÜVENLİK: Burada da siparişi temizlenmiş haliyle kullanıyoruz
            temiz_cinsi = siparis['cinsi'].strip().upper()
            temiz_kalinlik = siparis['kalinlik'].strip().upper()
            key = (temiz_cinsi, temiz_kalinlik)
            
            stok_sivali_available = temp_sivali_stok_kopyasi.get(key, 0)
            gerekli_m2 = siparis['bekleyen_m2']
            
            # Stoktan karşılanan miktarı düş
            karsilanan_sivali = min(gerekli_m2, stok_sivali_available)
            kalan_ihtiyac = gerekli_m2 - karsilanan_sivali
            
            if key in temp_sivali_stok_kopyasi:
                temp_sivali_stok_kopyasi[key] -= karsilanan_sivali
            
            if kalan_ihtiyac > 0:
                siva_uretim_sirasli_ihtiyac.append({
                    'key': f"{temiz_cinsi} {temiz_kalinlik}",
                    'm2': kalan_ihtiyac
                })

        siva_plan_detay = defaultdict(list) 
        ihtiyac_index = 0
        
        for gun in range(1, 6): # Önümüzdeki 5 gün için planlama
            kalan_kapasite_bugun = kapasite
            # KRİTİK DÜZELTME: O gün üretilecek ürünleri birleştirmek için geçici sözlük
            gunluk_uretim_birlesik = defaultdict(int)
            
            while kalan_kapasite_bugun > 0 and ihtiyac_index < len(siva_uretim_sirasli_ihtiyac):
                ihtiyac = siva_uretim_sirasli_ihtiyac[ihtiyac_index]
                key = ihtiyac['key']
                m2_gerekli = ihtiyac['m2']
                
                m2_yapilacak = min(m2_gerekli, kalan_kapasite_bugun)
                
                # DÜZELTME: Plan detayına tek tek eklemek yerine, önce günlük toplamı topla
                gunluk_uretim_birlesik[key] += m2_yapilacak
                
                ihtiyac['m2'] -= m2_yapilacak
                kalan_kapasite_bugun -= m2_yapilacak
                
                if ihtiyac['m2'] <= 0:
                    ihtiyac_index += 1
                
            # GÜNCEL DÜZELTME: Gün sonunda birleştirilmiş sonuçları ana plan detayına ekle
            for cinsi_key, m2_total in gunluk_uretim_birlesik.items():
                if m2_total > 0:
                    siva_plan_detay[gun].append({
                        'cinsi': cinsi_key,
                        'm2': m2_total
                    })

            if ihtiyac_index >= len(siva_uretim_sirasli_ihtiyac):
                break 
        
        # 5 Günlük Sevkiyat Detay Planı (Termin tarihine göre)
        bugun = datetime.now().date()
        sevkiyat_plan_detay = {} 
        for i in range(0, 5): 
            plan_tarihi = (bugun + timedelta(days=i)).strftime('%Y-%m-%d')
            cur.execute("""
                SELECT siparis_kodu, musteri, urun_kodu, bekleyen_m2 
                FROM siparisler 
                WHERE durum='Bekliyor' AND termin_tarihi = %s
                ORDER BY musteri ASC, urun_kodu ASC
            """, (plan_tarihi,))
            sevkiyatlar = cur.fetchall()
            
            if sevkiyatlar:
                # Müşteri bazlı gruplama
                gunluk_plan = defaultdict(list)
                for s in sevkiyatlar:
                    gunluk_plan[s['musteri']].append(s)
                
                sevkiyat_plan_detay[plan_tarihi] = dict(gunluk_plan)
        
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
    
    # *** KRİTİK DÜZELTME: JSON verilerini ve değişkenleri HER SAYFA YÜKLEMEDE ZORLA YENİDEN YÜKLE ***
    global KALINLIKLAR, CINSLER, VARYANTLAR, CINS_TO_BOYALI_MAP, URUN_KODLARI
    
    # 1. JSON'dan verileri yükle (Güncel listeleri al)
    KALINLIKLAR = load_kalinliklar()
    CINSLER = load_cinsler()
    VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
    CINS_TO_BOYALI_MAP = load_data('urun_kodlari.json')
    print(f"DEBUG: Loaded Map Keys Count: {len(CINS_TO_BOYALI_MAP)}") # DEBUG
    if len(CINS_TO_BOYALI_MAP) > 0:
        print(f"DEBUG: Sample Key: {list(CINS_TO_BOYALI_MAP.keys())[0]}")
        
    URUN_KODLARI = sorted(list(set(code for codes in CINS_TO_BOYALI_MAP.values() for code in codes)))
    
    # Yeni eklenen Cins/Kalınlıkların Stok tablosuna otomatik girmesini sağla
    with app.app_context():
        init_db() 

    # 2. Planlama ve Stok Haritasını Hesapla
    toplam_gerekli_siva, kapasite, siva_plan_detay, sevkiyat_plan_detay, stok_map = calculate_planning(conn)
    
    # 3. Stok ve Eksik Analizi Listesini Oluştur
    stok_list = []
    for cinsi_raw, kalinlik_raw in VARYANTLAR:
        
        cinsi = cinsi_raw.strip().upper()
        kalinlik = kalinlik_raw.strip().upper()
        key = (cinsi, kalinlik)
        
        ham_m2 = stok_map.get(key, {}).get('Ham', 0)
        sivali_m2 = stok_map.get(key, {}).get('Sivali', 0)
        
        cur.execute(""" 
            SELECT COALESCE(SUM(bekleyen_m2), 0) as toplam_m2 
            FROM siparisler 
            WHERE durum='Bekliyor' 
            AND cinsi ILIKE %s 
            AND kalinlik ILIKE %s 
        """, (cinsi, kalinlik))
        
        bekleyen_m2_raw = cur.fetchone()
        
        gerekli_siparis_m2 = bekleyen_m2_raw['toplam_m2']

        sivali_eksik = max(0, gerekli_siparis_m2 - sivali_m2)
        ham_eksik = max(0, sivali_eksik - ham_m2)
        
        stok_list.append({'cinsi': cinsi, 'kalinlik': kalinlik, 'ham_m2': ham_m2, 'sivali_m2': sivali_m2, 'gerekli_siparis_m2': gerekli_siparis_m2, 'sivali_eksik': sivali_eksik, 'ham_eksik': ham_eksik})
    
    cur.execute("SELECT * FROM siparisler ORDER BY termin_tarihi ASC, siparis_tarihi DESC")
    siparisler = cur.fetchall() 
    next_siparis_kodu = get_next_siparis_kodu(conn)
    today = datetime.now().strftime('%Y-%m-%d')
    
    # TOPLAM BEKLEYEN SİPARİŞ M2'Yİ HESAPLA
    toplam_bekleyen_siparis_m2 = sum(s['bekleyen_m2'] for s in siparisler if s['durum'] == 'Bekliyor')
    
    # Tarih nesnelerini HTML uyumlu string'e çevir
    siparis_listesi = []
    for s in siparisler:
        # DEBUG LOGGING FOR STATUS
        print(f"DEBUG: Siparis ID: {s['id']}, Durum: '{s['durum']}', Bekleyen: {s['bekleyen_m2']}, Musteri: {s['musteri']}")
        s_dict = dict(s) 
        if 'siparis_tarihi' in s_dict and s_dict['siparis_tarihi']:
            s_dict['siparis_tarihi'] = s_dict['siparis_tarihi'].isoformat()
        if 'termin_tarihi' in s_dict and s_dict['termin_tarihi']:
            s_dict['termin_tarihi'] = s_dict['termin_tarihi'].isoformat()
        siparis_listesi.append(s_dict)
    
    cur.close()
    conn.close()
    
    return render_template('dashboard.html', stok_list=stok_list, siparisler=siparis_listesi, CINSLER=CINSLER, KALINLIKLAR=KALINLIKLAR, next_siparis_kodu=next_siparis_kodu, today=today, message=message, gunluk_siva_m2=gunluk_siva_m2, toplam_gerekli_siva=toplam_gerekli_siva, siva_plan_detay=siva_plan_detay, sevkiyat_plan_detay=sevkiyat_plan_detay, CINS_TO_BOYALI_MAP=CINS_TO_BOYALI_MAP, toplam_bekleyen_siparis_m2=toplam_bekleyen_siparis_m2)

# --- KRİTİK VERİ KURTARMA ROTASI ---
@app.route('/admin/data_repair', methods=['GET'])
def repair_data_integrity():
    """Veritabanındaki cinsi ve kalinlik kolonlarındaki boşlukları ve küçük harfleri düzeltir."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("UPDATE stok SET cinsi = TRIM(UPPER(cinsi)), kalinlik = TRIM(UPPER(kalinlik))")
        cur.execute("UPDATE siparisler SET cinsi = TRIM(UPPER(cinsi)), kalinlik = TRIM(UPPER(kalinlik))")
        
        conn.commit()
        return redirect(url_for('index', message="✅ KRİTİK VERİ KURTARMA BAŞARILI! Stok ve Sipariş Cinsi/Kalınlık verileri temizlendi."))
        
    except Exception as e:
        if conn: conn.rollback()
        return redirect(url_for('index', message=f"❌ Veri Kurtarma Hatası: {str(e)}"))
    finally:
        if conn: conn.close()
# -----------------------------------------------------------------------------

# --- STOK VE YÖNETİM ROTLARI (DEĞİŞİKLİK YOK) ---
@app.route('/islem', methods=['POST'])
def handle_stok_islem():
    action = request.form['action']
    cinsi = request.form['cinsi'].strip().upper()
    kalinlik = request.form['kalinlik'].strip().upper()
    m2 = int(request.form['m2'])
    conn = None
    message = ""
    success = True
    try:
        conn = get_db_connection() 
        cur = conn.cursor()
        
        # ... (Stok İşlemleri Mantığı) ...
        # (Bu kısım uzun olduğu için burada kısaltıldı, ancak nihai kodunuzda kalmalıdır.)
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

@app.route('/api/urun_kodlari')
def get_urun_kodlari_api():
    """Ürün kodları haritasını JSON olarak döndürür."""
    global CINS_TO_BOYALI_MAP
    # Ensure map is loaded
    if not CINS_TO_BOYALI_MAP:
        CINS_TO_BOYALI_MAP = load_data('urun_kodlari.json')
    return jsonify(CINS_TO_BOYALI_MAP)


# --- SİPARİŞ ROTLARI (TERMİN TARİHİ DÜZELTMESİ BURADA) ---
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
            # ... (Yeni Sipariş Ekleme Mantığı) ...
            musteri = request.form['musteri']
            siparis_tarihi = request.form['siparis_tarihi']
            termin_tarihi = request.form['termin_tarihi']
            
            new_siparis_codes = []
            all_keys = list(request.form.keys())
            indices = sorted(list(set([int(k.split('_')[-1]) for k in all_keys if k.startswith('urun_kodu_')])))

            for i in indices:
                urun_kodu_key = f'urun_kodu_{i}'
                m2_key = f'm2_{i}'
                
                urun_kodu = request.form.get(urun_kodu_key, '').strip()
                m2_str = request.form.get(m2_key, '').strip() 
                
                if urun_kodu and m2_str:
                    try: m2 = int(m2_str)
                    except ValueError: m2 = 0 
                        
                    if m2 > 0:
                        siparis_kodu = get_next_siparis_kodu(conn)
                        cins_kalinlik_key = next((key for key, codes in CINS_TO_BOYALI_MAP.items() if urun_kodu in codes), None)
                        if not cins_kalinlik_key:
                            raise ValueError(f"Ürün kodu {urun_kodu} için cins/kalınlık bulunamadı. Lütfen ürün kodlarını kontrol edin.")
                            
                        parts = cins_kalinlik_key.rsplit(' ', 2) 
                        if len(parts) == 3:
                            cinsi_raw = parts[0]
                            kalinlik_raw = f"{parts[1]} {parts[2]}" 
                        elif len(parts) == 2:
                            cinsi_raw = parts[0]
                            kalinlik_raw = parts[1]
                        else:
                            raise ValueError(f"Ürün kodu {urun_kodu} için cins/kalınlık formatı hatalı: {cins_kalinlik_key}")

                        cinsi = cinsi_raw.strip().upper() 
                        kalinlik = kalinlik_raw.strip().upper() 
                        
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
            
        # KRİTİK DÜZELTME: SİPARİŞİ DÜZENLEME (Termin Tarihi Eklendi)
        elif action == 'duzenle_siparis':
            siparis_id = request.form['siparis_id']
            yeni_musteri = request.form['yeni_musteri'] # YENİ ALAN: Müşteri Adı
            yeni_urun_kodu = request.form['yeni_urun_kodu']
            yeni_m2 = int(request.form['yeni_m2'])
            yeni_termin_tarihi = request.form['yeni_termin_tarihi'] # YENİ ALAN
            
            # Ürün kodundan cins/kalınlık tespiti
            # Check existing order first
            cur.execute("SELECT urun_kodu, cinsi, kalinlik FROM siparisler WHERE id = %s", (siparis_id,))
            current_order = cur.fetchone()
            
            yeni_cinsi = None
            yeni_kalinlik = None

            if current_order and current_order['urun_kodu'] == yeni_urun_kodu:
                # Code unchanged, keep existing Cins/Kalinlik (preserve legacy codes)
                yeni_cinsi = current_order['cinsi']
                yeni_kalinlik = current_order['kalinlik']
            else:
                # Code changed, validation required
                cins_kalinlik_key = next((key for key, codes in CINS_TO_BOYALI_MAP.items() if yeni_urun_kodu in codes), None)
                if not cins_kalinlik_key:
                     # Fallback: If not in map, just accept it (for flexibility) but log warning
                     # Or better: raise error only if it's a NEW code not in map.
                     # But for now, let's keep validation strictly for NEW codes.
                     raise ValueError(f"Ürün kodu {yeni_urun_kodu} için cins/kalınlık bulunamadı.")
                
                parts = cins_kalinlik_key.rsplit(' ', 2)
                if len(parts) == 3:
                     yeni_cinsi = parts[0].strip().upper()
                     yeni_kalinlik = f"{parts[1]} {parts[2]}".strip().upper()
                elif len(parts) == 2:
                     yeni_cinsi = parts[0].strip().upper()
                     yeni_kalinlik = parts[1].strip().upper()
                else:
                     raise ValueError(f"Ürün kodu {yeni_urun_kodu} için cins/kalınlık formatı hatalı")

            print(f"DEBUG: Editing Order {siparis_id}. New Customer: {yeni_musteri}, Code: {yeni_urun_kodu}, Date: {yeni_termin_tarihi}") # DEBUG LOG

            cur.execute("""
                UPDATE siparisler SET 
                musteri = %s, urun_kodu = %s, cinsi = %s, kalinlik = %s, bekleyen_m2 = %s, termin_tarihi = %s
                WHERE id = %s 
            """, (yeni_musteri, yeni_urun_kodu, yeni_cinsi, yeni_kalinlik, yeni_m2, yeni_termin_tarihi, siparis_id))
            
            conn.commit(); message = f"✅ Sipariş ID {siparis_id} güncellendi: {yeni_musteri}, {yeni_cinsi} {yeni_kalinlik}, {yeni_m2} m². Yeni Termin: {yeni_termin_tarihi}"

        # YENİ EK: Kısmi Tamamlama
        elif action == 'kismi_tamamla':
            siparis_id = request.form['siparis_id']
            hazirlanan_m2 = int(request.form['hazirlanan_m2'])
            
            cur.execute("SELECT bekleyen_m2 FROM siparisler WHERE id = %s", (siparis_id,))
            row = cur.fetchone()
            
            if row:
                current_bekleyen = row['bekleyen_m2']
                yeni_bekleyen = current_bekleyen - hazirlanan_m2
                
                if yeni_bekleyen <= 0:
                    # Tamamen bitti
                    cur.execute("UPDATE siparisler SET durum = 'Tamamlandi', bekleyen_m2 = 0, planlanan_is_gunu = 0 WHERE id = %s", (siparis_id,))
                    message = f"✅ Sipariş ID {siparis_id} TAMAMLANDI. ({hazirlanan_m2} m² düşüldü, kalan sıfırlandı)."
                
                    # Log to History
                    cur.execute("INSERT INTO siparis_gecmisi (siparis_id, islem_tipi, miktar) VALUES (%s, 'Kismi', %s)", (siparis_id, hazirlanan_m2))

                else:
                    # Kısmi bitti
                    cur.execute("UPDATE siparisler SET bekleyen_m2 = %s WHERE id = %s", (yeni_bekleyen, siparis_id))
                    message = f"✅ Sipariş ID {siparis_id} güncellendi. {hazirlanan_m2} m² düşüldü. KALAN: {yeni_bekleyen} m²."
                    
                    # Log to History
                    cur.execute("INSERT INTO siparis_gecmisi (siparis_id, islem_tipi, miktar) VALUES (%s, 'Kismi', %s)", (siparis_id, hazirlanan_m2))

                conn.commit()
            else:
                raise ValueError("Sipariş bulunamadı.")

        # YENİ: Geçmişten Kısmi İşlemi Geri Alma
        elif action == 'geri_al_kismi':
            gecmis_id = request.form['gecmis_id']
            
            # Geçmiş kaydını bul
            cur.execute("SELECT siparis_id, miktar FROM siparis_gecmisi WHERE id = %s", (gecmis_id,))
            gecmis_row = cur.fetchone()
            
            if gecmis_row:
                siparis_id = gecmis_row['siparis_id']
                miktar = gecmis_row['miktar']
                
                # Siparişi bul ve miktarı geri ekle
                cur.execute("SELECT bekleyen_m2, durum FROM siparisler WHERE id = %s", (siparis_id,))
                siparis_row = cur.fetchone()
                
                if siparis_row:
                    yeni_bekleyen = siparis_row['bekleyen_m2'] + miktar
                    
                    # Eğer sipariş 'Tamamlandi' ise tekrar 'Bekliyor'a çek
                    if siparis_row['durum'] == 'Tamamlandi':
                        cur.execute("UPDATE siparisler SET durum = 'Bekliyor', bekleyen_m2 = %s WHERE id = %s", (yeni_bekleyen, siparis_id))
                    else:
                        cur.execute("UPDATE siparisler SET bekleyen_m2 = %s WHERE id = %s", (yeni_bekleyen, siparis_id))
                    
                    # Geçmiş kaydını sil
                    cur.execute("DELETE FROM siparis_gecmisi WHERE id = %s", (gecmis_id,))
                    conn.commit()
                    message = f"✅ Kısmi işlem geri alındı: {miktar} m² siparişe geri eklendi."
                else:
                    raise ValueError("Bağlı sipariş bulunamadı.")
            else:
                raise ValueError("Geçmiş kaydı bulunamadı.")


        # YENİ EK: Tamamlanan Siparişi Geri Alma (Undo)
        elif action == 'geri_al_tamamla':
            siparis_id = request.form['siparis_id']
            geri_alinacak_m2 = int(request.form['geri_alinacak_m2'])
            
            if geri_alinacak_m2 <= 0:
                raise ValueError("Geri alınacak miktar 0'dan büyük olmalıdır.")

            cur.execute("SELECT durum FROM siparisler WHERE id = %s", (siparis_id,))
            row = cur.fetchone()
            
            if row and row['durum'] == 'Tamamlandi':
                cur.execute("""
                    UPDATE siparisler 
                    SET durum = 'Bekliyor', bekleyen_m2 = %s, planlanan_is_gunu = 0 
                    WHERE id = %s
                """, (geri_alinacak_m2, siparis_id))
                conn.commit()
                message = f"✅ Sipariş ID {siparis_id} geri alındı. Bekleyen Miktar: {geri_alinacak_m2} m²."
            else:
                raise ValueError("Bu sipariş zaten tamamlanmamış veya bulunamadı.")

        # YENİ EK: Siparişi Kalıcı Silme (İz bırakmaz)
        elif action == 'sil_siparis':
            siparis_id = request.form['siparis_id']
            cur.execute("DELETE FROM siparisler WHERE id = %s", (siparis_id,))
            conn.commit(); message = f"✅ Sipariş ID {siparis_id} veritabanından **kalıcı olarak silindi**."
            
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

# YENİ ROTA: Sipariş Geçmişi
@app.route('/api/siparis_gecmisi/<int:siparis_id>', methods=['GET'])
def get_siparis_gecmisi(siparis_id):
    """Siparişin geçmiş işlemlerini JSON olarak döndürür."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, islem_tarihi, miktar, islem_tipi FROM siparis_gecmisi WHERE siparis_id = %s ORDER BY islem_tarihi DESC", (siparis_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    # Datetime nesnelerini stringe çevir
    history = []
    for row in rows:
        history.append({
            'id': row['id'],
            'tarih': row['islem_tarihi'].strftime('%d.%m.%Y %H:%M'),
            'miktar': row['miktar'],
            'tip': row['islem_tipi']
        })
    return jsonify(history)

# YENİ ROTA: Zemin Kalınlığı ve Cins Ekleme
@app.route('/ayarla/kalinlik', methods=['POST'])
def ayarla_kalinlik():
    """Yeni bir kalınlık ve/veya cins ekler ve stok tablosuna varsayılan girişleri yapar."""
    global KALINLIKLAR, CINSLER
    yeni_kalinlik_input = request.form['yeni_kalinlik'].strip()
    yeni_cins_input = request.form['yeni_cins'].strip().upper() 
    message = ""
    conn = None
    try:
        if not yeni_kalinlik_input or not yeni_cins_input: 
            raise ValueError("Cins ve Kalınlık alanları boş olamaz.")
        
        temp_kalinlik = yeni_kalinlik_input.replace(',', '.').upper()
        if not temp_kalinlik.endswith(' CM'):
            yeni_kalinlik = temp_kalinlik + ' CM'
        else:
            yeni_kalinlik = temp_kalinlik

        yeni_cins = yeni_cins_input
        if yeni_cins not in CINSLER:
            CINSLER.append(yeni_cins)
            save_cinsler(CINSLER)
            cins_mesaji = f"Yeni Cins **{yeni_cins}** eklendi."
        else:
            cins_mesaji = f"Mevcut Cins **{yeni_cins}** kullanıldı."

        if yeni_kalinlik not in KALINLIKLAR: 
            KALINLIKLAR.append(yeni_kalinlik)
            save_kalinliklar(KALINLIKLAR)
            kalinlik_mesaji = f"Yeni Kalınlık **{yeni_kalinlik}** eklendi."
        else:
            kalinlik_mesaji = f"Mevcut Kalınlık **{yeni_kalinlik}** kullanıldı."

        conn = get_db_connection()
        cur = conn.cursor()
        
        updated_cinsler = load_cinsler()
        updated_kalinliklar = load_kalinliklar()
        
        new_variants_to_add = set()
        
        if yeni_kalinlik in updated_kalinliklar:
            for c in updated_cinsler:
                new_variants_to_add.add((c, yeni_kalinlik))
            
        if yeni_cins in updated_cinsler:
            for k in updated_kalinliklar:
                new_variants_to_add.add((yeni_cins, k))
        
        for c, k in new_variants_to_add:
            temiz_c = c.strip().upper()
            temiz_k = k.strip().upper()
            for asama in ['Ham', 'Sivali']:
                cur.execute("""
                    INSERT INTO stok (cinsi, kalinlik, asama, m2) 
                    VALUES (%s, %s, %s, %s) 
                    ON CONFLICT (cinsi, kalinlik, asama) DO NOTHING
                """, (temiz_c, temiz_k, asama, 0))
        
        conn.commit()
        
        global VARYANTLAR, CINS_TO_BOYALI_MAP, URUN_KODLARI
        VARYANTLAR = [(c, k) for c in updated_cinsler for k in updated_kalinliklar]
        CINS_TO_BOYALI_MAP = load_data('urun_kodlari.json')
        URUN_KODLARI = sorted(list(set(code for codes in CINS_TO_BOYALI_MAP.values() for code in codes)))
        
        message = f"✅ Kombinasyon **{yeni_cins} {yeni_kalinlik}** başarıyla hazırlandı. ({cins_mesaji} / {kalinlik_mesaji})"

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
            
            global CINS_TO_BOYALI_MAP
            CINS_TO_BOYALI_MAP = urun_kodlari_map 
            
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
        
        cur.execute("DELETE FROM siparisler")
        cur.execute("DELETE FROM stok")
        
        global KALINLIKLAR, CINSLER, VARYANTLAR
        KALINLIKLAR = load_kalinliklar()
        CINSLER = load_cinsler()
        VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR] 

        for c, k in VARYANTLAR:
            temiz_c = c.strip().upper()
            temiz_k = k.strip().upper()
            for asama in ['Ham', 'Sivali']:
                cur.execute("""
                    INSERT INTO stok (cinsi, kalinlik, asama, m2) 
                    VALUES (%s, %s, %s, %s) 
                    ON CONFLICT (cinsi, kalinlik, asama) DO NOTHING
                """, (temiz_c, temiz_k, asama, 0))
                
        conn.commit()
        
        with app.app_context():
            init_db() 
            
        return redirect(url_for('index', message="✅ TÜM VERİLER SİLİNDİ ve GÜNCEL STOKLAR SIFIRLANDI!"))
        
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
    try: 
        conn = get_db_connection()
        cur = conn.cursor()
        
        global KALINLIKLAR, CINSLER, VARYANTLAR
        KALINLIKLAR = load_kalinliklar()
        CINSLER = load_cinsler()
        VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
        
        toplam_gerekli_siva, gunluk_siva_m2, siva_plan_detay, sevkiyat_plan_detay, stok_map = calculate_planning(conn)
        
        stok_data = {}
        deficit_analysis = {}

        for cinsi_raw, kalinlik_raw in VARYANTLAR:
            
            cinsi = cinsi_raw.strip().upper()
            kalinlik = kalinlik_raw.strip().upper()
            key = f"{cinsi} {kalinlik}"
            stok_key = (cinsi, kalinlik)
            
            stok_data[f"{key} (Ham)"] = stok_map.get(stok_key, {}).get('Ham', 0)
            stok_data[f"{key} (Sivali)"] = stok_map.get(stok_key, {}).get('Sivali', 0)
            
            cur.execute(""" 
                SELECT COALESCE(SUM(bekleyen_m2), 0) as toplam_m2 
                FROM siparisler 
                WHERE durum='Bekliyor' 
                AND cinsi ILIKE %s 
                AND kalinlik ILIKE %s 
            """, (cinsi, kalinlik))
            
            bekleyen_m2_raw = cur.fetchone()
            
            gerekli_siparis_m2 = bekleyen_m2_raw['toplam_m2']

            sivali_stok = stok_map.get(stok_key, {}).get('Sivali', 0)
            ham_stok = stok_map.get(stok_key, {}).get('Ham', 0)
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
        
        siparis_listesi = []
        for s in siparisler:
            s_dict = dict(s) 
            if 'siparis_tarihi' in s_dict and s_dict['siparis_tarihi']:
                s_dict['siparis_tarihi'] = s_dict['siparis_tarihi'].isoformat()
            if 'termin_tarihi' in s_dict and s_dict['termin_tarihi']:
                s_dict['termin_tarihi'] = s_dict['termin_tarihi'].isoformat()
            s_dict['id'] = str(s_dict['id']) 
            siparis_listesi.append(s_dict)

        cur.close()
        conn.close()

        formatted_sevkiyat_plan_detay = {}
        for tarih, musteriler in sevkiyat_plan_detay.items():
            formatted_musteriler = {}
            for musteri, urunler in musteriler.items():
                formatted_urunler = []
                for item in urunler:
                    item_dict = dict(item)
                    if 'termin_tarihi' in item_dict and item_dict['termin_tarihi']:
                        item_dict['termin_tarihi'] = item_dict['termin_tarihi'].isoformat()
                    formatted_urunler.append(item_dict)
                formatted_musteriler[musteri] = formatted_urunler
            formatted_sevkiyat_plan_detay[tarih] = formatted_musteriler
            
        toplam_bekleyen_siparis_m2_api = sum(s['bekleyen_m2'] for s in siparis_listesi if s['durum'] == 'Bekliyor')

        return jsonify({
            'stok': stok_data,
            'deficit_analysis': deficit_analysis,
            'siparisler': siparis_listesi,
            'toplam_gerekli_siva': toplam_gerekli_siva,
            'gunluk_siva_m2': gunluk_siva_m2,
            'siva_plan_detay': dict(siva_plan_detay), 
            'sevkiyat_plan_detay': formatted_sevkiyat_plan_detay,
            'toplam_bekleyen_siparis_m2': toplam_bekleyen_siparis_m2_api
        })
        
    except Exception as e:
        print(f"--- KRİTİK HATA LOGU (api_stok_verileri) ---")
        print(f"Hata Tipi: {type(e).__name__}")
        print(f"Hata Mesajı: {str(e)}")
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




@app.route('/api/siparis_analizi')
def api_siparis_analizi():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Query active orders from 'siparisler' table
        cur.execute("""
            SELECT musteri, bekleyen_m2, urun_kodu, siparis_tarihi, termin_tarihi
            FROM siparisler
            WHERE durum = 'Bekliyor'
        """)
        rows = cur.fetchall()
        
        cur.close()
        conn.close()

        # REVERSE LOOKUP MAP (Code -> "Type Thickness")
        # Reuse global or reload to be safe
        global CINS_TO_BOYALI_MAP
        if not CINS_TO_BOYALI_MAP:
             CINS_TO_BOYALI_MAP = load_data('urun_kodlari.json')
        
        code_to_desc = {}
        for desc, codes in CINS_TO_BOYALI_MAP.items():
            for c in codes:
                code_to_desc[c] = desc

        # Aggregation Logic
        analysis = {} 

        for row in rows:
            # Handle row access (dict or tuple)
            if isinstance(row, dict):
                 musteri = row['musteri']
                 bekleyen = row['bekleyen_m2']
                 kod = row['urun_kodu']
                 s_tarih = row['siparis_tarihi']
                 t_tarih = row['termin_tarihi']
            else:
                 # Ensure order matches SELECT
                 musteri, bekleyen, kod, s_tarih, t_tarih = row
            
            # Normalize Code
            if not kod:
                kod = "BİLİNMEYEN"
            kod = kod.strip().upper()

            # Ensure numeric
            try:
                bekleyen_val = float(bekleyen) if bekleyen else 0
            except:
                bekleyen_val = 0

            if bekleyen_val <= 0.01: continue 

            if kod not in analysis:
                # Find description
                aciklama = code_to_desc.get(kod, "")
                
                analysis[kod] = {
                    "urun_kodu": kod,
                    "aciklama": aciklama, # NEW FIELD
                    "toplam_bekleyen": 0.0,
                    "detaylar": []
                }
            
            analysis[kod]["toplam_bekleyen"] += bekleyen_val
            
            # Format dates
            s_str = s_tarih.isoformat() if hasattr(s_tarih, 'isoformat') else str(s_tarih) if s_tarih else "-"
            t_str = t_tarih.isoformat() if hasattr(t_tarih, 'isoformat') else str(t_tarih) if t_tarih else "-"

            analysis[kod]["detaylar"].append({
                "musteri": musteri,
                "bekleyen_m2": round(bekleyen_val, 2),
                "siparis_tarihi": s_str,
                "termin_tarihi": t_str
            })

        # Convert to list and Sort by Total Pending Descending
        result = list(analysis.values())
        result.sort(key=lambda x: x['toplam_bekleyen'], reverse=True)
        
        # Round final totals
        for item in result:
             item['toplam_bekleyen'] = round(item['toplam_bekleyen'], 2)

        return jsonify(result)

    except Exception as e:
        print(f"Error in Analysis API: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)