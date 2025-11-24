# -*- coding: utf-8 -*-
import os
from flask import Flask, render_template_string, request, redirect, url_for, send_file
import sqlite3
import json
from datetime import datetime
from collections import defaultdict

# --- UYGULAMA YAPILANDIRMASI ---
# Render portunu al, yoksa yerel test için 5000 kullan
PORT = int(os.environ.get('PORT', 5000))
app = Flask(__name__)
DATABASE = 'envanter_v5.db' 

# --- 0. SABİT TANIMLAMALAR (Aynı Kaldı) ---
KALINLIKLAR = ['2 CM', '3.6 CM', '3 CM']
CINSLER = ['BAROK', 'YATAY TAŞ', 'DÜZ TUĞLA', 'KAYRAK TAŞ', 'PARKE TAŞ', 'KIRIK TAŞ', 'BUZ TAŞ', 'MERMER', 'LB ZEMİN', 'LA']
VARYANTLAR = [(c, k) for c in CINSLER for k in KALINLIKLAR]
PLATE_M2_MAP = {
    '2 CM': 0.5,    
    '3.6 CM': 0.6,
    '3 CM': 1.0,    
    'MERMER': 1.0, 
    'LA': 1.0,      
    'LB ZEMİN': 1.0,
}
CINS_TO_BOYALI_MAP = {
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
URUN_KODLARI = sorted(list(set(code for codes in CINS_TO_BOYALI_MAP.values() for code in codes)))

# --- 1. VERİTABANI İŞLEMLERİ ---

def get_db_connection():
    """Veritabanı bağlantısını açar. Render uyumu için check_same_thread=False eklenmiştir."""
    conn = sqlite3.connect(DATABASE, check_same_thread=False) 
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stok (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cinsi TEXT NOT NULL,
            kalinlik TEXT NOT NULL,
            asama TEXT NOT NULL,
            m2 INTEGER,
            UNIQUE(cinsi, kalinlik, asama)
        );
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS siparisler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_kodu TEXT NOT NULL UNIQUE,
            urun_kodu TEXT NOT NULL,
            cinsi TEXT NOT NULL,
            kalinlik TEXT NOT NULL,
            musteri TEXT NOT NULL,
            siparis_tarihi DATE NOT NULL,
            termin_tarihi DATE,
            bekleyen_m2 INTEGER,
            durum TEXT NOT NULL
        );
    """)

    for c, k in VARYANTLAR:
        for asama in ['Ham', 'Sivali']:
            conn.execute("INSERT OR IGNORE INTO stok (cinsi, kalinlik, asama, m2) VALUES (?, ?, ?, ?)", (c, k, asama, 0))

    conn.commit()
    conn.close()

with app.app_context():
    init_db()

def get_next_siparis_kodu(conn):
    current_year = datetime.now().year
    prefix = f'S-{current_year}-'
    
    max_code_row = conn.execute("""
        SELECT MAX(siparis_kodu) AS max_code
        FROM siparisler
        WHERE siparis_kodu LIKE ?
    """, (prefix + '%',)).fetchone()
    
    max_code = max_code_row['max_code']
    
    if max_code:
        try:
            current_num = int(max_code.split('-')[-1])
            next_num = current_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:04d}"

# --- 5. HTML ŞABLONU (Aynı Kaldı) ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <title>EPS Panel Yönetimi</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f9; }
        .container { max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0, 0, 0, 0.1); }
        h1, h2 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.9em; }
        th { background-color: #007bff; color: white; }
        .message { padding: 10px; margin-bottom: 15px; border-radius: 4px; font-weight: bold; }
        .success { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
        .error { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
        .form-section { background-color: #e9e9e9; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .karsilama-yes { background-color: #ccffcc; }
        .karsilama-no { background-color: #ffcccc; }
        .deficit-ham { color: red; font-weight: bold; } 
        .deficit-sivali { color: darkred; font-weight: bold; } 
        button { background-color: #007bff; color: white; padding: 8px 12px; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        input[type="number"], input[type="text"], input[type="date"], select { padding: 6px; margin-right: 5px; border: 1px solid #ccc; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏭 EPS Panel Üretim ve Sipariş Yönetimi</h1>
        <p style="font-style: italic;">*Tüm giriş ve çıkışlar Metrekare (m²) cinsindendir.</p>

        {% if message %}
            <div class="message {% if 'Hata' in message or 'Yetersiz' in message %}error{% else %}success{% endif %}">{{ message }}</div>
        {% endif %}
        
        <div class="grid">
            
            <div class="form-section">
                <h2>1. Stok Hareketleri (Üretim/Alım/Satış)</h2>
                <form action="/islem" method="POST">
                    <select name="action" required>
                        <option value="ham_alim">1 - Ham Panel Alımı (m² Stoğa Ekle)</option>
                        <option value="siva_uygula">2 - Sıva Uygulama (Ham -> Sıvalı Üretim)</option>
                        <option value="sat_ham">3 - Ham Panel Satışı</option>
                        <option value="sat_sivali">4 - Sıvalı Panel Satışı</option>
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
                    
                    <input type="number" name="m2" min="1" required placeholder="M2" style="width: 60px;">
                    <button type="submit">İşlemi Kaydet</button>
                </form>
            </div>
            
            <div class="form-section">
                <h2>2. Yeni Sipariş Girişi (Oto Kod: {{ next_siparis_kodu }})</h2>
                <form action="/siparis" method="POST">
                    <input type="hidden" name="action" value="yeni_siparis">
                    
                    <input type="text" name="musteri" required placeholder="Müşteri Adı" style="width: 120px;">
                    
                    <select id="cinsi_select" name="cinsi" required onchange="filterProductCodes()">
                        {% for c in CINSLER %}
                            <option value="{{ c }}">{{ c }}</option>
                        {% endfor %}
                    </select>
                    <select id="kalinlik_select" name="kalinlik" required onchange="filterProductCodes()">
                        {% for k in KALINLIKLAR %}
                            <option value="{{ k }}">{{ k }}</option>
                        {% endfor %}
                    </select>
                    
                    <select id="urun_kodu_select" name="urun_kodu" required>
                        </select>
                    
                    <input type="number" name="m2" min="1" required placeholder="M2" style="width: 60px;">
                    
                    <br><br>
                    <label>Sipariş Tarihi:</label>
                    <input type="date" name="siparis_tarihi" value="{{ today }}" required>
                    <label>Termin Tarihi:</label>
                    <input type="date" name="termin_tarihi" required>
                    
                    <button type="submit" style="background-color:#00a359;">Sipariş Ekle</button>
                </form>
            </div>
            
        </div>
        
        <h2>3. Detaylı Stok Durumu ve Eksik Planlama (M²)</h2>
        <table>
            <tr><th>Cinsi</th><th>Kalınlık</th><th>Aşama</th><th>M² Stok</th><th>Eksik Sipariş M²</th><th>Eksik Ham M²</th></tr>
            {% for item in stok %}
                {% set key = (item['cinsi'], item['kalinlik']) %}
                {% set deficit_info = deficit_analysis.get(key) %}

                {% if item['asama'] == 'Sivali' %}
                    <tr {% if deficit_info and deficit_info.sivali_deficit > 0 %}class="karsilama-no"{% endif %}>
                        <td>{{ item['cinsi'] }}</td>
                        <td>{{ item['kalinlik'] }}</td>
                        <td>{{ item['asama'] }}</td>
                        <td>{{ item['m2'] }} m²</td>
                        <td>
                            {% if deficit_info and deficit_info.sivali_deficit > 0 %}
                                <span class="deficit-sivali">{{ deficit_info.sivali_deficit }} m² EKSİK</span>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                        <td>
                            -
                        </td>
                    </tr>
                {% elif item['asama'] == 'Ham' %}
                    <tr {% if deficit_info and deficit_info.ham_deficit > 0 %}class="karsilama-no"{% endif %}>
                        <td>{{ item['cinsi'] }}</td>
                        <td>{{ item['kalinlik'] }}</td>
                        <td>{{ item['asama'] }}</td>
                        <td>{{ item['m2'] }} m²</td>
                        <td>
                            <span style="color: blue;">(Üretilecek: {{ deficit_info.ham_coverage if deficit_info else 0 }} m²)</span>
                        </td>
                        <td>
                            {% if deficit_info and deficit_info.ham_deficit > 0 %}
                                <span class="deficit-ham">{{ deficit_info.ham_deficit }} m² EKSİK</span>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                    </tr>
                {% endif %}
            {% endfor %}
        </table>

        <br>
        
        <h2>4. Bekleyen ve Tamamlanan Siparişler (M²)</h2>
        <table>
            <tr><th>ID</th><th>Sipariş Kodu</th><th>Müşteri</th><th>Ürün (Boyalı Kod)</th><th>Cins/Kalınlık</th><th>Sipariş Tarihi</th><th>Termin Tarihi</th><th>Bekleyen M²</th><th>Durum</th><th>İşlem</th></tr>
            {% for s in siparisler %}
                <tr>
                    <td>{{ s['id'] }}</td>
                    <td>{{ s['siparis_kodu'] }}</td>
                    <td>{{ s['musteri'] }}</td>
                    <td>{{ s['urun_kodu'] }}</td>
                    <td>{{ s['cinsi'] }} {{ s['kalinlik'] }}</td>
                    <td>{{ s['siparis_tarihi'] }}</td>
                    <td><b>{{ s['termin_tarihi'] }}</b></td>
                    <td>{{ s['bekleyen_m2'] }} m²</td>
                    <td>
                        {% if s['durum'] == 'Bekliyor' %}
                            <span style="color:red; font-weight:bold;">BEKLİYOR</span>
                        {% else %}
                            <span style="color:green;">{{ s['durum'] }}</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if s['durum'] == 'Bekliyor' %}
                            <form action="/siparis" method="POST" style="display:inline;">
                                <input type="hidden" name="action" value="siparis_karsila">
                                <input type="hidden" name="siparis_id" value="{{ s['id'] }}">
                                <button type="submit" style="background-color:#cc8400;">UV Baskı & Tamamla</button>
                            </form>
                        {% endif %}
                    </td>
                </tr>
            {% endfor %}
        </table>

    </div>
    
    <script>
        // Python haritası, JavaScript'e aktarılır
        const CINS_TO_BOYALI_MAP_JS = JSON.parse('{{ cins_to_boyali_map | tojson }}');
        
        function filterProductCodes() {
            const cinsiSelect = document.getElementById('cinsi_select');
            const kalinlikSelect = document.getElementById('kalinlik_select');
            const urunKoduSelect = document.getElementById('urun_kodu_select');
            
            const selectedCinsi = cinsiSelect.value;
            const selectedKalinlik = kalinlikSelect.value;
            const key = selectedCinsi + " " + selectedKalinlik;
            
            urunKoduSelect.innerHTML = ''; // Seçim kutusunu temizle
            
            const validCodes = CINS_TO_BOYALI_MAP_JS[key] || [];
            
            if (validCodes.length === 0) {
                const defaultOption = document.createElement('option');
                defaultOption.text = 'Bu varyant için Boyalı Ürün Kodu Yok';
                urunKoduSelect.add(defaultOption);
            } else {
                validCodes.forEach(code => {
                    const option = document.createElement('option');
                    option.value = code;
                    option.text = code;
                    urunKoduSelect.add(option);
                });
            }
        }
        
        // Sayfa yüklendiğinde filtrelemeyi başlat
        window.onload = function() {
            filterProductCodes();
        };
    </script>
</body>
</html>
"""

# --- 2. WEB ARAYÜZÜ ROUTE'LARI ---

@app.route('/', methods=['GET', 'POST'])
def index():
    conn = get_db_connection()
    stok_raw = conn.execute("SELECT * FROM stok ORDER BY cinsi, kalinlik, asama").fetchall()
    siparisler = conn.execute("SELECT * FROM siparisler ORDER BY termin_tarihi ASC").fetchall()
    
    deficit_analysis = calculate_deficit(conn) 
    next_siparis_kodu = get_next_siparis_kodu(conn)
    conn.close()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    html_content = render_template_string(HTML_TEMPLATE, 
                                          stok=stok_raw, 
                                          siparisler=siparisler,
                                          urun_kodlari=URUN_KODLARI,
                                          varyantlar=VARYANTLAR,
                                          KALINLIKLAR=KALINLIKLAR,
                                          CINSLER=CINSLER,
                                          deficit_analysis=deficit_analysis,
                                          today=today,
                                          next_siparis_kodu=next_siparis_kodu,
                                          cins_to_boyali_map=CINS_TO_BOYALI_MAP,
                                          message=request.args.get('message'))
    return html_content

@app.route('/islem', methods=['POST'])
def islem():
    conn = get_db_connection()
    try:
        action = request.form['action']
        m2 = int(request.form['m2']) 
        cinsi = request.form.get('cinsi')
        kalinlik = request.form.get('kalinlik')
        
        if m2 <= 0:
            raise ValueError("M2 değeri pozitif bir sayı olmalıdır.")

        if action == 'ham_alim':
            message = process_ham_alim(conn, cinsi, kalinlik, m2)
        elif action == 'siva_uygula':
            message = process_siva(conn, cinsi, kalinlik, m2)
        elif action == 'sat_ham':
            message = process_sale(conn, cinsi, kalinlik, 'Ham', m2)
        elif action == 'sat_sivali':
            message = process_sale(conn, cinsi, kalinlik, 'Sivali', m2)
        
        conn.commit()
        return redirect(url_for('index', message=message))

    except Exception as e:
        conn.close()
        return redirect(url_for('index', message=f"Hata: {e}"))

@app.route('/siparis', methods=['POST'])
def siparis_islem():
    conn = get_db_connection()
    try:
        action = request.form['action']
        
        if action == 'yeni_siparis':
            
            siparis_kodu = get_next_siparis_kodu(conn)
            
            urun_kodu = request.form['urun_kodu']
            cinsi = request.form['cinsi']
            kalinlik = request.form['kalinlik']
            m2 = int(request.form['m2']) 
            musteri = request.form['musteri']
            siparis_tarihi = request.form['siparis_tarihi']
            termin_tarihi = request.form['termin_tarihi']
            
            message = add_siparis(conn, siparis_kodu, urun_kodu, cinsi, kalinlik, m2, musteri, siparis_tarihi, termin_tarihi)
        
        elif action == 'siparis_karsila':
            siparis_id = int(request.form['siparis_id'])
            message = fulfill_siparis(conn, siparis_id)
            
        conn.commit()
        return redirect(url_for('index', message=message))
        
    except Exception as e:
        conn.close()
        return redirect(url_for('index', message=f"Hata: {e}"))

# --- 3. İŞLEM MANTIKLARI (Aynı Kaldı) ---

def calculate_deficit(conn):
    bekleyen_siparis = conn.execute("""
        SELECT cinsi, kalinlik, SUM(bekleyen_m2) as total_required 
        FROM siparisler WHERE durum='Bekliyor' GROUP BY cinsi, kalinlik
    """).fetchall()

    deficit_results = {}
    
    for req in bekleyen_siparis:
        key = (req['cinsi'], req['kalinlik'])
        total_required = req['total_required']
        
        stok_ham_row = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", key).fetchone()
        stok_sivali_row = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", key).fetchone()

        S = stok_sivali_row['m2'] if stok_sivali_row else 0 
        H = stok_ham_row['m2'] if stok_ham_row else 0 
        
        sivali_deficit = max(0, total_required - S)
        
        ham_coverage = min(sivali_deficit, H)
        ham_deficit = max(0, sivali_deficit - H)
        
        deficit_results[key] = {
            'total_required': total_required,
            'sivali_deficit': sivali_deficit,
            'ham_coverage': ham_coverage, 
            'ham_deficit': ham_deficit 
        }
        
    return deficit_results


def process_ham_alim(conn, cinsi, kalinlik, m2):
    conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik))
    return f"✅ {cinsi} {kalinlik} Ham Panel stoğa {m2} m² eklendi."

def process_siva(conn, cinsi, kalinlik, m2):
    ham_row = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (cinsi, kalinlik)).fetchone()
    if not ham_row or ham_row['m2'] < m2:
        raise Exception(f"Yetersiz Ham Stok: İşlem için sadece {ham_row['m2'] if ham_row else 0} m² Ham Panel mevcut.")
        
    conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Ham'", (m2, cinsi, kalinlik))
    conn.execute("UPDATE stok SET m2 = m2 + ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (m2, cinsi, kalinlik))
    return f"✅ {m2} m² {cinsi} {kalinlik} panel SIVALI aşamasına geçti."

def process_sale(conn, cinsi, kalinlik, asama, m2):
    stok_row = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = ?", (cinsi, kalinlik, asama)).fetchone()
    if not stok_row or stok_row['m2'] < m2:
        raise Exception(f"Yetersiz {asama} Stok: Satış için {m2} m² gerekiyor, sadece {stok_row['m2'] if stok_row else 0} mevcut.")
        
    conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = ?", (m2, cinsi, kalinlik, asama))
    return f"✅ {m2} m² {cinsi} {kalinlik} {asama} Panel başarıyla SATILDI."

def add_siparis(conn, siparis_kodu, urun_kodu, cinsi, kalinlik, m2, musteri, siparis_tarihi, termin_tarihi):
    conn.execute("""
        INSERT INTO siparisler (siparis_kodu, urun_kodu, cinsi, kalinlik, bekleyen_m2, durum, musteri, siparis_tarihi, termin_tarihi)
        VALUES (?, ?, ?, ?, ?, 'Bekliyor', ?, ?, ?)
    """, (siparis_kodu, urun_kodu, cinsi, kalinlik, m2, musteri, siparis_tarihi, termin_tarihi))
    return f"✅ Sipariş {siparis_kodu} ({urun_kodu}) {m2} m² olarak {musteri} adına eklendi."
    
def fulfill_siparis(conn, siparis_id):
    siparis = conn.execute("SELECT * FROM siparisler WHERE id = ?", (siparis_id,)).fetchone()
    if not siparis or siparis['durum'] == 'Tamamlandi':
        raise Exception("Geçersiz veya zaten tamamlanmış sipariş.")
        
    cinsi = siparis['cinsi']
    kalinlik = siparis['kalinlik']
    m2 = siparis['bekleyen_m2']
    
    sivali_row = conn.execute("SELECT m2 FROM stok WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (cinsi, kalinlik)).fetchone()
    if not sivali_row or sivali_row['m2'] < m2:
        raise Exception(f"Yetersiz Sıvalı Stok: Bu sipariş için {m2} m² Sıvalı Panel gerekiyor, sadece {sivali_row['m2'] if sivali_row else 0} mevcut.")
        
    conn.execute("UPDATE stok SET m2 = m2 - ? WHERE cinsi = ? AND kalinlik = ? AND asama = 'Sivali'", (m2, cinsi, kalinlik))
    
    conn.execute("UPDATE siparisler SET durum = 'Tamamlandi', bekleyen_m2 = 0 WHERE id = ?", (siparis_id,))
    
    return f"🎉 Sipariş {siparis['siparis_kodu']} ({siparis['urun_kodu']}) başarıyla tamamlandı ve {m2} m² Sıvalı Stok düşüldü."
    
# --- 4. MOBİL İÇİN API UÇ NOKTASI (Veritabanı Try/Finally ile güvenli hale getirildi) ---

@app.route('/api/stok')
def api_stok():
    conn = get_db_connection()
    try:
        # Mobil görünüm için gerekli verileri çekiyoruz
        stok = conn.execute("SELECT cinsi, kalinlik, asama, m2 FROM stok").fetchall()
        
        # Sizin HTML'inizin beklediği basit {Aşama: Adet} formatına çeviriyoruz (Tüm aşamaları birleştirip listeliyoruz)
        # Basit stok toplamını döndürme:
        stok_data = {}
        for row in stok:
            key = f"{row['cinsi']} {row['kalinlik']} ({row['asama']})"
            stok_data[key] = row['m2']
            
        return json.dumps(stok_data)

    except Exception as e:
        print(f"API Hata Detayı: {e}")
        # Hata durumunda 500 kodu ile JSON hata mesajı döndürüyoruz.
        return json.dumps({"error": "Veritabanı erişim hatası"}), 500
    finally:
        conn.close()


# --- 5. MOBİL GÖRÜNTÜLEME HTML DOSYASINI SUNMA (Render Sorununu Çözen Yol) ---

@app.route('/stok_goruntule.html')
def mobil_goruntuleme():
    """stok_goruntule.html dosyasını tarayıcıya sunar."""
    # Dosyanın aynı dizinde olduğunu varsayarak gönderiyoruz
    return send_file('stok_goruntule.html')

# Yerel çalıştırma kısmı (Render'da Gunicorn kullanıldığı için bu satırlar kullanılmaz)
if __name__ == '__main__':
    # Flask sunucusunu yerel ağda başlat (Test için)
    app.run(host='0.0.0.0', port=PORT, debug=True)