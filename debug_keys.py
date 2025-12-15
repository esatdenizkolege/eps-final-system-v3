
import json

def load_json(name):
    with open(name, 'r', encoding='utf-8') as f:
        return json.load(f)

cinsler = load_json('cin_listesi.json')['cinsler']
kalinliklar = load_json('kalinliklar.json')['kalinliklar']
kodlar = load_json('urun_kodlari.json')

print("--- CHECKING KEYS ---")
for c in cinsler:
    for k in kalinliklar:
        key = f"{c} {k}"
        if key in kodlar:
            print(f"MATCH: '{key}'")
        else:
            print(f"MISSING: '{key}'")
            # Try to find close match
            for existing in kodlar.keys():
                if c in existing and k in existing:
                    print(f"  -> Found similar: '{existing}'")
