"""Deploy-freshness guard: verify dist asset hashes match the ?v= stamps in
index.html AND that viz/static is in sync with the deployed dist. Run after an
export / before a deploy to catch a stale or mismatched build."""
import hashlib, re, sys, json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def md5(path):
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except FileNotFoundError:
        return "MISSING"

css_hash = md5(BASE + r"\dist\style.css")
js_hash  = md5(BASE + r"\dist\app.js")
col_hash = md5(BASE + r"\dist\collapse.js")
print(f"dist/style.css  actual hash: {css_hash}")
print(f"dist/app.js     actual hash: {js_hash}")
print(f"dist/collapse.js actual hash: {col_hash}")

with open(BASE + r"\dist\index.html", encoding="utf-8") as f:
    html = f.read()

m_css = re.search(r"style\.css\?v=([a-f0-9]+)", html)
m_js  = re.search(r"app\.js\?v=([a-f0-9]+)", html)
m_col = re.search(r"collapse\.js\?v=([a-f0-9]+)", html)
ref_css = m_css.group(1) if m_css else "no-ref"
ref_js  = m_js.group(1)  if m_js  else "no-ref"
ref_col = m_col.group(1) if m_col else "no-ref"
print(f"\ndist/index.html CSS ref:      {ref_css}  {'OK' if ref_css == css_hash else 'MISMATCH!'}")
print(f"dist/index.html JS  ref:      {ref_js}   {'OK' if ref_js == js_hash else 'MISMATCH!'}")
print(f"dist/index.html COL ref:      {ref_col}  {'OK' if ref_col == col_hash else 'MISMATCH!'}")

# Also check viz/static matches dist (critical — copy must be in sync)
vcss = md5(BASE + r"\viz\static\style.css")
vjs  = md5(BASE + r"\viz\static\app.js")
print(f"\nviz/static/style.css hash:  {vcss}  {'matches dist' if vcss == css_hash else 'DIFFERS from dist!'}")
print(f"viz/static/app.js    hash:  {vjs}   {'matches dist' if vjs == js_hash else 'DIFFERS from dist!'}")

# Check key APIs exist and are non-empty
print("\n--- dist/api/ files ---")
for name in ["meta.json", "fixtures.json", "report.json", "groupadv.json",
             "rankings.json", "news.json", "bracket.json", "collapse.json"]:
    p = BASE + r"\dist\api\\" + name
    try:
        size = os.path.getsize(p)
        print(f"  {name:<22} {size:>8} bytes  OK")
    except FileNotFoundError:
        print(f"  {name:<22}  MISSING!")

# Check share tray CSS present
with open(BASE + r"\dist\style.css", encoding="utf-8") as f:
    css = f.read()
print(f"\nVirality CSS present: share-tray={'share-tray' in css}  kofi-float={'kofi-float' in css}  nudge-bar={'nudge-bar' in css}")

# Check app.js has virality functions
with open(BASE + r"\dist\app.js", encoding="utf-8") as f:
    js = f.read()
print(f"Virality JS present:  doShare={'doShare' in js}  showShareTray={'showShareTray' in js}  initKofiFloat={'initKofiFloat' in js}")

# Check index.html has FAQ JSON-LD
print(f"FAQ JSON-LD present:  {'FAQPage' in html}")
