
import psycopg2
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost/dbname") # Fallback for local if needed, but in this env it works
# Actually, I should use the app's get_db_connection logic if possible, but I can just rely on standard psycopg2 if I knew the credentials.
# Since I am in the environment where app.py runs, I can import from app.

from app import get_db_connection

try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT urun_kodu, cinsi, kalinlik, musteri FROM siparisler WHERE urun_kodu = 'L 1711' LIMIT 1")
    row = cur.fetchone()
    if row:
        print(f"FOUND: Code='{row['urun_kodu']}', Cinsi='{row['cinsi']}', Kalinlik='{row['kalinlik']}'")
    else:
        print("NOT FOUND")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
