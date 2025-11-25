# -*- coding: utf-8 -*-
import os
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, render_template
import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict
import math
from flask_cors import CORS 

# --- UYGULAMA YAPILANDIRMASI ---
# Render'ın kullandığı PORT'u alır, yerelde 5000 kullanılır.
PORT = int(os.environ.get('PORT', 5000)) 
app = Flask(__name__)
# Mobil erişim (CORS) için gereklidir. Önceki hataları çözmek için bu önemlidir.
CORS(app) 
DATABASE = 'envanter_v5.db'
KAPASITE_FILE = 'kapasite.json'
# Önbellekleme (caching) sorunlarını azaltmak için ayar.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0 

# --- 0. SABİT TANIMLAMALAR ---
KALINLIKLAR = ['2 CM', '3.6 CM', '3 CM']
CINSLER = ['BAROK', 'YATAY TAŞ', 'DÜZ TUĞLA', 'KAYRAK TAŞ', 'PARKE TAŞ', 'KIRIK TAŞ', 'BUZ TAŞ', 'MERMER', 'LB ZEMİN', 'LA']
VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]

# --- JSON/KAPASİTE/ÜRÜN KODU YÖNETİMİ ---

def load_data(filename):
    """JSON verisini yükler ve yoksa varsayılan değerleri döndürür."""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    if filename == KAPASITE_FILE:
        return {"gunluk_siva_m2": 600}
    
    # Varsayılan urun_kodlari.json verisini ekledik (kullanıcının orijinal kodundan alınmıştır).
    if filename == 'urun_kodlari.json':
        return {
            'BAROK 2 CM': ['B001', 'B002', 'B003', 'B004', 'B005', 'B006', 'B007', 'B008', 'B009', 'B010', 'B011', 'B012', 'B013', 'B014', 'B015', 'B016', 'B017', 'B018', 'B019', 'B020', 'B021', 'B022', 'B023', 'B024', 'B025', 'B026', 'B027', 'B028', 'B029', 'B030', 'B031', 'B032', 'B033', 'B034', 'B035', 'B036', 'B037', 'B038', 'B039', 'B040'],
            'PARKE TAŞ 2 CM': ['PT001', 'PT002', 'PT003', 'PT004', 'PT005', 'PT006', 'PT007', 'PT008', 'PT009', 'PT010', 'PT011', 'PT012', 'PT013', 'PT014', 'PT015', 'PT016', 'PT017', 'PT018', 'PT019', 'PT020', 'PT021', 'PT022', 'PT023', 'PT024', 'PT025', 'PT026', 'PT027', 'PT028', 'PT029', 'PT030'],
            'KIRIK TAŞ 2 CM': ['KR001', 'KR002', 'KR003', 'KR004', 'KR005', 'KR006', 'KR007', 'KR008', 'KR009', 'KR010', 'KR011', 'KR012'],
            'YATAY TAŞ 2 CM': ['YT011', 'YT012', 'YT013', 'YT014', 'YT015', 'YT016'],
            'KAYRAK TAŞ 2 CM': ['KY001', 'KY002', 'KY003', 'KY004', 'KY005', 'KY006', 'KY007', 'KY008', 'KY009', 'KY010', 'KY011', 'KY012', 'KY013', 'KY014'],
            'DÜZ TUĞLA 2 CM': ['DT101', 'DT102', 'DT103', 'DT104', 'DT105', 'DT106', 'DT107', 'DT108', 'DT109', 'DT110', 'DT111', 'DT112', 'DT113', 'DT114', 'DT115', 'DT116', 'DT117', 'DT118', 'DT119', 'DT120'],
            'DÜZ TUĞLA 3.6 CM': ['DT301', 'DT302', 'DT303', 'DT304', 'DT305', 'DT306', 'DT307', 'DT308', 'DT309', 'DT310', 'DT311', 'DT312', 'DT313', 'DT314', 'DT315', 'DT316', 'DT317', 'DT318', 'DT319', 'DT320'],
            'BUZ TAŞ 2 CM': ['BZ001', 'BZ002', 'BZ003', 'BZ004', 'BZ005', 'BZ006', 'BZ007', 'BZ008', 'BZ009', 'BZ010'],
            'BUZ TAŞ 3.6 CM': ['BZ101', 'BZ102', 'BZ103', 'BZ104', 'BZ105', 'BZ106', 'BZ107', 'BZ108', 'BZ109', 'BZ110'],
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


# --- 1. VERİTABANI İŞLEMLERİ VE BAŞLANGIÇ ---

def get_db_connection():
    """Veritabanı bağlantısını açar."""
    # check_same_thread=False ile Flask'ın varsayılan çoklu iş parçacığı (multi-threading) ortamında SQLite'ın sorunsuz çalışması sağlanır.
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Veritabanını ve tabloları oluşturur."""
    conn = get_db_connection()
    conn.execute(""" CREATE TABLE IF NOT EXISTS stok ( id INTEGER PRIMARY KEY AUTOINCREMENT, cinsi TEXT NOT NULL, kalinlik TEXT NOT NULL, asama TEXT NOT NULL, m2 INTEGER, UNIQUE(cinsi, kalinlik, asama) ); """)
    conn.execute(""" CREATE TABLE IF NOT EXISTS siparisler ( id INTEGER PRIMARY KEY AUTOINCREMENT, siparis_kodu TEXT NOT NULL UNIQUE, urun_kodu TEXT NOT NULL, cinsi TEXT NOT NULL, kalinlik TEXT NOT NULL, musteri TEXT NOT NULL, siparis_tarihi DATE NOT NULL, termin_tarihi DATE, bekleyen_m2 INTEGER, durum TEXT NOT NULL, planlanan_is_gunu INTEGER ); """)
    for c, k in VARYANTLAR:
        for asama in ['Ham', 'Sivali']:
            conn.execute("INSERT OR IGNORE INTO stok (cinsi, kalinlik, asama, m2) VALUES (?, ?, ?, ?)", (c, k, asama, 0))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()
    if not os.path.exists(KAPASITE_FILE):
        save_data({"gunluk_siva_m2": 600}, KAPASITE_FILE)
    if not os.path.exists('urun_kodlari.json'):
        save_data(CINS_TO_BOYALI_MAP, 'urun_kodlari.json')


# --- 2. YARDIMCI FONKSİYONLAR VE PLANLAMA MANTIĞI ---

def get_next_siparis_kodu(conn):
    """Bir sonraki sipariş kodunu oluşturur."""
    current_year = datetime.now().strftime('%Y')
    last_code_row = conn.execute(f""" SELECT siparis_kodu FROM siparisler WHERE siparis_kodu LIKE 'S-{current_year}-%' ORDER BY siparis_kodu DESC LIMIT 1 """).fetchone()
    if last_code_row:
        last_code = last_code_row['siparis_kodu']
        try:
            last_number = int(last_code.split('-')[-1])
            new_number = last_number + 1
        except ValueError:
            new_number = 1 
    else:
        new_number = 1
    return f"S-{current_year}-{new_number:04}"

def calculate_planning(conn):
    """Sıva planı ve sevkiyat planı için 5 günlük detayları hesaplar (Termin Tarihi Öncelikli)."""
    kapasite = load_data(KAPASITE_FILE)['gunluk_siva_m2']
    stok_map = {}
    stok_raw = conn.execute("SELECT cinsi, kalinlik, asama, m2 FROM stok").fetchall()
    for row in stok_raw:
        key = (row['cinsi'], row['kalinlik'])
        if key not in stok_map: stok_map[key] = {'Ham': 0, 'Sivali': 0}
        stok_map[key][row['asama']] = row['m2']

    # KRİTİK KISIM: Termin tarihine göre sıralama
    bekleyen_siparisler = conn.execute("""
        SELECT id, cinsi, kalinlik, bekleyen_m2, termin_tarihi 
        FROM siparisler 
        WHERE durum='Bekliyor' 
        ORDER BY termin_tarihi ASC, siparis_tarihi ASC 
    """).fetchall()

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
            # İş günü hesabı: Toplam eksiği günlük kapasiteye bölerek kaçıncı günde yetişeceğini bulur.
            is_gunu = math.ceil(toplam_gerekli_siva / kapasite) if kapasite > 0 else -1
            planlama_sonuclari[siparis['id']] = is_gunu
        else:
            planlama_sonuclari[siparis['id']] = 0 # Stoktan karşılanabilir (0 iş günü)

    # Hesaplanan iş günlerini veritabanına kaydet
    for siparis_id, is_gunu in planlama_sonuclari.items():
        conn.execute("UPDATE siparisler SET planlanan_is_gunu = ? WHERE id = ?", (is_gunu, siparis_id))
    conn.commit()
    
    # 5 Günlük Sıva Üretim Detay Planı
    siva_plan_detay = defaultdict(int) 
    kalan_siva_m2 = toplam_gerekli_siva
    for i in range(1, 6): # Önümüzdeki 5 gün için
        siva_yapilacak = min(kalan_siva_m2, kapasite)
        if siva_yapilacak > 0:
            siva_plan_detay[i] = siva_yapilacak
            kalan_siva_m2 -= siva_yapilacak
        else: break
            
    # 5 Günlük Sevkiyat Detay Planı (Termin tarihine göre)
    bugun = datetime.now().date()
    sevkiyat_plan_detay = defaultdict(list)
    for i in range(0, 5): # Bugün ve sonraki 4 gün
        plan_tarihi = (bugun + timedelta(days=i)).strftime('%Y-%m-%d')
        sevkiyatlar = conn.execute("""
            SELECT siparis_kodu, musteri, urun_kodu, bekleyen_m2 
            FROM siparisler 
            WHERE durum='Bekliyor' AND termin_tarihi = ?
            ORDER BY termin_tarihi ASC
        """, (plan_tarihi,)).fetchall()
        if sevkiyatlar:
            sevkiyat_plan_detay[plan_tarihi] = [dict(s) for s in sevkiyatlar]

    return toplam_gerekli_siva, kapasite, siva_plan_detay, sevkiyat_plan_detay, stok_map


# --- 3. ROTALAR (PC Arayüzü ve İşlemler) ---

@app.route('/', methods=['GET'])
def index():
    """Ana PC arayüzünü (veri giriş ve kapsamlı tablolar) gösterir."""
    conn = get_db_connection()
    message = request.args.get('message')
    gunluk_siva_m2 = load_data(KAPASITE_FILE)['gunluk_siva_m2']
    toplam_gerekli_siva, kapasite, siva_plan_detay, sevkiyat_plan_detay, stok_map = calculate_planning(conn)
    
    stok_list = []
    for cinsi, kalinlik in VARYANTLAR:
        ham_m2 = stok_map.get((cinsi, kalinlik), {}).get('Ham', 0)
        sivali_m2 = stok_map.get((cinsi, kalinlik), {}).get('Sivali', 0)
        bekleyen_m2_raw = conn.execute(""" SELECT SUM(bekleyen_m2) as toplam_m2 FROM siparisler WHERE durum='Bekliyor' AND cinsi=? AND kalinlik=? """, (cinsi, kalinlik)).fetchone()
        gerekli_siparis_m2 = bekleyen_m2_raw['toplam_m2'] if bekleyen_m2_raw['toplam_m2'] else 0
        sivali_eksik = max(0, gerekli_siparis_m2 - sivali_m2)
        ham_eksik = max(0, sivali_eksik - ham_m2)
        stok_list.append({'cinsi': cinsi, 'kalinlik': kalinlik, 'ham_m2': ham_m2, 'sivali_m2': sivali_m2, 'gerekli_siparis_m2': gerekli_siparis_m2, 'sivali_eksik': sivali_eksik, 'ham_eksik': ham_eksik})
    
    siparisler = conn.execute("SELECT * FROM siparisler ORDER BY termin_tarihi ASC, siparis_tarihi DESC").fetchall()
    next_siparis_kodu = get_next_siparis_kodu(conn)
    today = datetime.now().strftime('%Y-%m-%d')
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
    conn = get_db_connection()
    message = ""
    success = True
    try:
        if action == 'ham_alim': conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Ham stoğuna {m2} m² eklendi."
        elif action == 'siva_uygula':
            ham_stok = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (cinsi, kalinlik)).fetchone()['m2']
            if ham_stok < m2: success = False; message = f"❌ Hata: {cinsi} {kalinlik} Ham stoğu yetersiz ({ham_stok} m²). {m2} m² Sıva uygulanamadı."
            else: conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik)); conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} için {m2} m² Sıva Uygulandı (Ham -> Sıvalı)."
        elif action == 'sat_sivali':
            sivali_stok = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (cinsi, kalinlik)).fetchone()['m2']
            if sivali_stok < m2: success = False; message = f"❌ Hata: {cinsi} {kalinlik} Sıvalı stoğu yetersiz ({sivali_stok} m²). {m2} m² Satış yapılamadı."
            else: conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Sıvalı stoğundan {m2} m² Satıldı."
        elif action == 'sat_ham':
            ham_stok = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (cinsi, kalinlik)).fetchone()['m2']
            if ham_stok < m2: success = False; message = f"❌ Hata: {cinsi} {kalinlik} Ham stoğu yetersiz ({ham_stok} m²). {m2} m² Satış yapılamadı."
            else: conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Ham stoğundan {m2} m² Satıldı."
        elif action == 'iptal_ham_alim':
            ham_stok = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (cinsi, kalinlik)).fetchone()['m2']
            if ham_stok < m2: success = False; message = f"❌ Hata: {cinsi} {kalinlik} Ham stoğu yetersiz ({ham_stok} m²). Ham alımı iptal edilemedi."
            else: conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Ham alımı iptal edildi ({m2} m² stoktan çıkarıldı)."
        elif action == 'iptal_siva':
            sivali_stok = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (cinsi, kalinlik)).fetchone()['m2']
            if sivali_stok < m2: success = False; message = f"❌ Hata: {cinsi} {kalinlik} Sıvalı stoğu yetersiz ({sivali_stok} m²). Sıva Geri Alınamadı."
            else: conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (m2, cinsi, kalinlik)); conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Sıva işlemi geri alındı ({m2} m² Sıvalı -> Ham)."
        elif action == 'iptal_sat_sivali': conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Sıvalı satış iptal edildi ({m2} m² stoğa eklendi)."
        elif action == 'iptal_sat_ham': conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik)); message = f"✅ {cinsi} {kalinlik} Ham satış iptal edildi ({m2} m² stoğa eklendi)."

        if success: conn.commit()
    except Exception as e: conn.rollback(); message = f"❌ Veritabanı Hatası: {str(e)}"
    finally: conn.close()
    return redirect(url_for('index', message=message))

@app.route('/siparis', methods=['POST'])
def handle_siparis_islem():
    """Sipariş ekler, tamamlar veya iptal eder."""
    action = request.form['action']
    conn = get_db_connection()
    message = ""
    try:
        if action == 'yeni_siparis':
            siparis_kodu = get_next_siparis_kodu(conn); urun_kodu = request.form['urun_kodu']; cinsi = request.form['cinsi']; kalinlik = request.form['kalinlik']; musteri = request.form['musteri']; siparis_tarihi = request.form['siparis_tarihi']; termin_tarihi = request.form['termin_tarihi']; m2 = int(request.form['m2'])
            conn.execute(""" INSERT INTO siparisler (siparis_kodu, urun_kodu, cinsi, kalinlik, musteri, siparis_tarihi, termin_tarihi, bekleyen_m2, durum, planlanan_is_gunu) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) """, (siparis_kodu, urun_kodu, cinsi, kalinlik, musteri, siparis_tarihi, termin_tarihi, m2, 'Bekliyor', 0))
            conn.commit(); message = f"✅ Sipariş {siparis_kodu} ({urun_kodu}) {m2} m² olarak {musteri} adına eklendi."
        elif action == 'tamamla_siparis':
            siparis_id = request.form['siparis_id']; conn.execute("UPDATE siparisler SET durum = 'Tamamlandi', bekleyen_m2 = 0, planlanan_is_gunu = 0 WHERE id = ?", (siparis_id,)); conn.commit(); message = f"✅ Sipariş ID {siparis_id} tamamlandı olarak işaretlendi."
        elif action == 'iptal_siparis':
            siparis_id = request.form['siparis_id']; conn.execute("UPDATE siparisler SET durum = 'Iptal', bekleyen_m2 = 0, planlanan_is_gunu = -1 WHERE id = ?", (siparis_id,)); conn.commit(); message = f"✅ Sipariş ID {siparis_id} iptal edildi olarak işaretlendi."
    except sqlite3.IntegrityError: conn.rollback(); message = "❌ Hata: Bu sipariş kodu zaten mevcut. Lütfen tekrar deneyin."
    except Exception as e: conn.rollback(); message = f"❌ Veritabanı Hatası: {str(e)}"
    finally: conn.close()
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


# --- 4. MOBİL İÇİN ROTALAR (JSON API ve HTML GÖRÜNÜMÜ) ---

@app.route('/api/stok', methods=['GET'])
def api_stok_verileri():
    """Mobil görünüm için stok, sipariş ve planlama verilerini JSON olarak döndürür."""
    conn = get_db_connection()
    
    # Tüm analiz ve planlama verilerini hesaplar
    toplam_gerekli_siva, gunluk_siva_m2, siva_plan_detay, sevkiyat_plan_detay, stok_map = calculate_planning(conn)
    
    stok_data = {}
    deficit_analysis = {}

    for cinsi, kalinlik in VARYANTLAR:
        key = f"{cinsi} {kalinlik}"
        stok_data[f"{key} (Ham)"] = stok_map.get((cinsi, kalinlik), {}).get('Ham', 0)
        stok_data[f"{key} (Sivali)"] = stok_map.get((cinsi, kalinlik), {}).get('Sivali', 0)
        
        bekleyen_m2_raw = conn.execute(""" SELECT SUM(bekleyen_m2) as toplam_m2 FROM siparisler WHERE durum='Bekliyor' AND cinsi=? AND kalinlik=? """, (cinsi, kalinlik)).fetchone()
        gerekli_siparis_m2 = bekleyen_m2_raw['toplam_m2'] if bekleyen_m2_raw['toplam_m2'] else 0
        sivali_stok = stok_map.get((cinsi, kalinlik), {}).get('Sivali', 0)
        ham_stok = stok_map.get((cinsi, kalinlik), {}).get('Ham', 0)
        sivali_eksik = max(0, gerekli_siparis_m2 - sivali_stok)
        ham_eksik = max(0, sivali_eksik - ham_stok)
        
        if gerekli_siparis_m2 > 0:
            deficit_analysis[key] = {
                'sivali_deficit': sivali_eksik,
                'ham_deficit': ham_eksik,
                # Üretim Planı kapsayabileceği ham miktarı hesaplar
                'ham_coverage': max(0, sivali_eksik - max(0, sivali_eksik - ham_stok)) 
            }

    siparisler = conn.execute("SELECT * FROM siparisler ORDER BY termin_tarihi ASC, siparis_tarihi DESC").fetchall()
    siparis_listesi = [dict(row) for row in siparisler]
    
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


@app.route('/mobil', methods=['GET'])
def mobil_gorunum():
    """
    Telefonlar için tasarlanmış, veri girişi içermeyen 
    stok_goruntule.html şablonunu templates/ klasöründen sunar.
    """
    # templates/stok_goruntule.html dosyasını yükler
    return render_template('stok_goruntule.html')


# --- HTML ŞABLONU (PC Arayüzü) ---
# Orijinal PC arayüzü şablonunuz.

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="tr">
<head>
    <title>EPS Panel Yönetimi</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f9; color: #333; }
        .container { max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0, 0, 0, 0.1); }
        h1, h2, h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } input, select, button { width: 100%; margin-bottom: 8px; box-sizing: border-box; } }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; table-layout: fixed; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.9em; word-wrap: break-word; }
        th { background-color: #007bff; color: white; }
        .message { padding: 10px; margin-bottom: 15px; border-radius: 4px; font-weight: bold; }
        .success { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
        .error { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
        .form-section { background-color: #e9e9e9; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .deficit-ham { color: red; font-weight: bold; } 
        .deficit-sivali { color: darkred; font-weight: bold; } 
        button { background-color: #007bff; color: white; padding: 8px 12px; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        input[type="number"], input[type="text"], input[type="date"], select { padding: 6px; margin-right: 5px; border: 1px solid #ccc; border-radius: 4px; }
        .kapasite-box { background-color: #ffcc99; padding: 10px; border-radius: 5px; margin-top: 10px; }
        .plan-header { color: #00a359; }
        .plan-table td:nth-child(2) { font-weight: bold; }
        .siparis-tamamlandi { background-color: #e0f7e0; color: green; }
        .siparis-iptal { background-color: #ffe0e0; color: darkred; }
        .stok-table th:nth-child(1) { width: 15%; } .stok-table th:nth-child(2) { width: 10%; } .stok-table th:nth-child(3) { width: 10%; } .stok-table th:nth-child(4) { width: 10%; } .stok-table th:nth-child(5) { width: 10%; } .stok-table th:nth-child(6) { width: 10%; }
        .siparis-table th:nth-child(1) { width: 5%; } .siparis-table th:nth-child(4), .siparis-table th:nth-child(5) { width: 10%; } .siparis-table th:nth-child(7), .siparis-table th:nth-child(8) { width: 10%; } .siparis-table th:nth-child(10) { width: 10%; }
    </style>
    <script>
        const CINS_TO_BOYALI_MAP = {{ CINS_TO_BOYALI_MAP | tojson }};
        function filterProductCodes() {
            const cinsi = document.getElementById('cinsi_select').value;
            const kalinlik = document.getElementById('kalinlik_select').value;
            const urunKoduSelect = document.getElementById('urun_kodu_select');
            urunKoduSelect.innerHTML = ''; 
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
        document.addEventListener('DOMContentLoaded', filterProductCodes);
    </script>
</head>
<body>
    <div class="container">
        <h1>🏭 EPS Panel Üretim ve Sipariş Yönetimi</h1>
        <p style="font-style: italic;">*Tüm giriş ve çıkışlar Metrekare (m²) cinsindendir.</p>
        <p style="font-weight: bold; color: #007bff;">
            Mobil Görüntüleme Adresi: <a href="{{ url_for('mobil_gorunum') }}">/mobil</a>
        </p>
        {% if message %}
            <div class="message {% if 'Hata' in message or 'Yetersiz' in message %}error{% else %}success{% endif %}">{{ message }}</div>
        {% endif %}
        <div class="grid">
            <div class="form-section">
                <h2>1. Stok Hareketleri (Üretim/Alım/Satış/İptal)</h2>
                <div class="kapasite-box">
                    <h3>⚙️ Günlük Sıva Kapasitesi Ayarı</h3>
                    <form action="/ayarla/kapasite" method="POST" style="display:flex; flex-wrap:wrap; align-items:center;">
                        <input type="number" name="kapasite_m2" min="1" required placeholder="M2" value="{{ gunluk_siva_m2 }}" style="width: 80px;">
                        <span style="margin-right: 10px;">m² / Gün</span>
                        <button type="submit" style="background-color:#cc8400;">Kapasiteyi Kaydet</button>
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
                <form action="/islem" method="POST">
                    <select name="action" required>
                        <option value="ham_alim">1 - Ham Panel Alımı (Stoğa Ekle)</option>
                        <option value="siva_uygula">2 - Sıva Uygulama (Ham -> Sıvalı Üretim)</option>
                        <option value="sat_ham">3 - Ham Panel Satışı</option>
                        <option value="sat_sivali">4 - Sıvalı Panel Satışı</option>
                        <option value="iptal_ham_alim">5 - Ham Alımı İptal (Ham Stoktan Çıkar)</option>
                        <option value="iptal_siva">6 - Sıva İşlemi Geri Al (Sıvalı -> Ham)</option>
                        <option value="iptal_sat_ham">7 - Ham Satışını Geri Al (Ham Stoğa Ekle)</option>
                        <option value="iptal_sat_sivali">8 - Sıvalı Satışını Geri Al (Sıvalı Stoğa Ekle)</option>
                    </select>
                    <select name="cinsi" required>
                        {% for c in CINSLER %}
                            <option value="{{ c }}">{{ c }}</option>
                        {% endfor %}
                    </select>
                    <select name="kalinlik" required>
                        {% for k in KALINLIKLAR %}
                            <option value="{{ k }}">{{ k }}</option>
                        {% endfor %}
                    </select>
                    <input type="number" name="m2" min="1" required placeholder="M2" style="width: 80px;">
                    <button type="submit">İşlemi Kaydet</button>
                </form>
            </div>
            <div class="form-section">
                <h2>2. Yeni Sipariş Girişi (Oto Kod: {{ next_siparis_kodu }})</h2>
                <form action="/siparis" method="POST">
                    <input type="hidden" name="action" value="yeni_siparis">
                    <input type="text" name="musteri" required placeholder="Müşteri Adı" style="width: 120px;">
                    <select id="cinsi_select" name="cinsi" required onchange="filterProductCodes()" style="width: 120px;">
                        {% for c in CINSLER %}
                            <option value="{{ c }}">{{ c }}</option>
                        {% endfor %}
                    </select>
                    <select id="kalinlik_select" name="kalinlik" required onchange="filterProductCodes()" style="width: 100px;">
                        {% for k in KALINLIKLAR %}
                            <option value="{{ k }}">{{ k }}</option>
                        {% endfor %}
                    </select>
                    <select id="urun_kodu_select" name="urun_kodu" required style="width: 100px;">
                        </select>
                    <input type="number" name="m2" min="1" required placeholder="M2" style="width: 80px;">
                    <br><br>
                    <label>Sipariş Tarihi:</label>
                    <input type="date" name="siparis_tarihi" value="{{ today }}" required>
                    <label>Termin Tarihi:</label>
                    <input type="date" name="termin_tarihi" required>
                    <button type="submit" style="background-color:#00a359;">Sipariş Ekle</button>
                </form>
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
            <div class="form-section" style="background-color: #e9fff5;">
                <h3>Sıva Üretim Planı (Önümüzdeki 5 İş Günü)</h3>
                <table class="plan-table">
                    <tr><th>Gün</th><th>Planlanan M²</th></tr>
                    {% for gun, m2 in siva_plan_detay.items() %}
                        <tr><td>Gün {{ gun }}</td><td>{{ m2 }} m²</td></tr>
                    {% else %}
                        <tr><td colspan="2">Önümüzdeki 5 gün için Sıva ihtiyacı bulunmamaktadır.</td></tr>
                    {% endfor %}
                </table>
            </div>
            <div class="form-section" style="background-color: #f5f5ff;">
                <h3>Sevkiyat Planı (Önümüzdeki 5 Takvim Günü)</h3>
                {% if sevkiyat_plan_detay %}
                    {% for tarih, sevkiyatlar in sevkiyat_plan_detay.items() %}
                        <h4 style="margin-top: 10px; margin-bottom: 5px; color: #0056b3;">{{ tarih }} (Toplam: {{ sevkiyatlar|sum(attribute='bekleyen_m2') }} m²)</h4>
                        {% for sevkiyat in sevkiyatlar %}
                            <p style="margin: 0 0 3px 10px; font-size: 0.9em;">
                                - **{{ sevkiyat.urun_kodu }}** ({{ sevkiyat.bekleyen_m2 }} m²) -> Müşteri: {{ sevkiyat.musteri }}
                            </p>
                        {% endfor %}
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
                        <form action="/siparis" method="POST" style="display:inline-block;">
                            <input type="hidden" name="action" value="tamamla_siparis">
                            <input type="hidden" name="siparis_id" value="{{ siparis.id }}">
                            <button type="submit" style="background-color: green; padding: 4px 8px;">Tamamla</button>
                        </form>
                        <form action="/siparis" method="POST" style="display:inline-block;">
                            <input type="hidden" name="action" value="iptal_siparis">
                            <input type="hidden" name="siparis_id" value="{{ siparis.id }}">
                            <button type="submit" style="background-color: darkred; padding: 4px 8px;">İptal Et</button>
                        </form>
                    {% else %}
                        -
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
'''