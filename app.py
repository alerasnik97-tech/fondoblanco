import streamlit as st
import requests
import os
import json
import pandas as pd
import zipfile
import io
import time
from PIL import Image

# ── CONFIGURACIÓN DE SECRETOS ──
try:
    CLIENT_ID     = st.secrets["CLIENT_ID"]
    CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
except KeyError:
    st.error("Faltan las credenciales en los Secretos (CLIENT_ID o CLIENT_SECRET)")
    st.stop()

REDIRECT_URI  = "https://httpbin.org/get"
ML_SCOPES     = "offline_access read_listings write_listings"
TOKEN_FILE    = "ml_token.json"
ITEMS_FILE    = "items.json"
STEP_FILE     = "step.json"

st.set_page_config(page_title="FondoBlanco", page_icon="⬜", layout="wide")
st.markdown("""
<style>
.main-title{font-size:28px;font-weight:600;margin-bottom:4px}
.sub-title{font-size:15px;color:#888;margin-bottom:24px}
.step-box{border-radius:12px;padding:14px 18px;margin-bottom:10px;border-left:4px solid #444;background:#1e1e1e}
.step-done{border-left-color:#00A650!important;background:#0a1f0f!important}
.step-active{border-left-color:#3483FA!important;background:#0a1020!important}
</style>
""", unsafe_allow_html=True)

# ── helpers ──
def save_step(s):
    with open(STEP_FILE,"w") as f: json.dump(s,f)

def load_step():
    if os.path.exists(STEP_FILE):
        with open(STEP_FILE) as f: return json.load(f)
    return 1

def save_items(items):
    with open(ITEMS_FILE,"w") as f: json.dump(items,f)

def load_items():
    if os.path.exists(ITEMS_FILE):
        with open(ITEMS_FILE) as f: return json.load(f)
    return []

def guardar_token(d):
    d["saved_at"] = time.time()
    with open(TOKEN_FILE,"w") as f: json.dump(d,f)

def token_esta_vencido():
    if not os.path.exists(TOKEN_FILE): return True
    with open(TOKEN_FILE) as f: saved = json.load(f)
    saved_at = saved.get("saved_at", 0)
    expires_in = saved.get("expires_in", 21600)
    return (time.time() - saved_at) > (expires_in - 3600)

def renovar_token():
    if not os.path.exists(TOKEN_FILE): return None
    with open(TOKEN_FILE) as f: saved = json.load(f)
    if "refresh_token" not in saved: return None
    r = requests.post("https://api.mercadolibre.com/oauth/token", data={
        "grant_type":"refresh_token","client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET,"refresh_token":saved["refresh_token"]})
    if r.status_code == 200:
        d = r.json(); guardar_token(d); return d["access_token"]
    return None

def obtener_token_code(code):
    r = requests.post("https://api.mercadolibre.com/oauth/token", data={
        "grant_type":"authorization_code","client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET,"code":code,"redirect_uri":REDIRECT_URI})
    if r.status_code == 200:
        d = r.json(); guardar_token(d); return d["access_token"]
    return None

def get_token():
    if st.session_state.get("token"):
        return st.session_state.token
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            saved = json.load(f)
        t = saved.get("access_token")
        if t:
            st.session_state.token = t
            return t
    t = renovar_token()
    if t:
        st.session_state.token = t
    return t

# ── estado desde disco ──
step = load_step()
items = load_items()

# ── header ──
st.markdown('<div class="main-title">⬜ FondoBlanco</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Actualizá las fotos de portada de tus publicaciones de MercadoLibre</div>', unsafe_allow_html=True)

col_r1, col_r2 = st.columns([6,1])
with col_r2:
    if st.button('↺ Reiniciar'):
        for f in ['items.json','step.json','listo_paso2.txt','portadas_descargadas.zip','procesadas.zip','img_urls.json']:
            if os.path.exists(f): os.remove(f)
        st.rerun()

# ── login ──
token = get_token()
if not token:
    st.divider()
    st.subheader("Conectar con MercadoLibre")
    st.warning("⚠️ No hay sesión activa o el token venció. Volvé a autorizar la app.")
    auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={ML_SCOPES.replace(' ', '%20')}"
    st.markdown(f"**Paso 1:** [Hacé click acá para autorizar]({auth_url})")
    st.markdown("**Paso 2:** Pegá el código `TG-` que aparece en la URL:")
    code = st.text_input("Código TG-", placeholder="TG-XXXXXXXXX")
    if st.button("Conectar", type="primary") and code:
        t = obtener_token_code(code.strip().strip('"'))
        if t:
            st.session_state.token = t
            st.success("Conectado!")
            st.rerun()
        else:
            st.error("Código inválido o vencido.")
    st.stop()
else:
    with st.sidebar:
        st.caption("🔒 Sesión activa")
        if st.button("Reconectar con ML"):
            st.session_state.pop("token", None)
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            st.rerun()

# ── indicador de pasos ──
st.divider()
for n, title, desc in [
    (1,"Importar publicaciones","Subí tu planilla Excel"),
    (2,"Descargar fotos de portada","Se obtienen las fotos actuales"),
    (3,"Procesar fondo blanco","Descargá el ZIP y procesalo"),
    (4,"Subir fotos actualizadas","Se reemplaza la portada en ML"),
]:
    cls = "step-done" if step > n else ("step-active" if step == n else "")
    icon = "✅" if step > n else ("🔵" if step == n else "⭕")
    badge = "Listo" if step > n else ("En curso" if step == n else "Pendiente")
    st.markdown(f'<div class="step-box {cls}">{icon} <strong>Paso {n}: {title}</strong> — <small>{badge}</small><br><small style="color:#888">{desc}</small></div>', unsafe_allow_html=True)
st.divider()

# ══ PASO 1 ══
if step == 1:
    st.subheader("Paso 1 — Importar publicaciones")
    archivo = st.file_uploader("Subí tu planilla de MercadoLibre (.xlsx)", type=["xlsx"])
    if archivo:
        df = pd.read_excel(archivo, sheet_name="Publicaciones", header=None)
        nuevos_items = df.iloc[4:, 1].dropna().astype(str).tolist()
        nuevos_items = [i for i in nuevos_items if i.startswith("MLA")]
        st.success(f"{len(nuevos_items)} publicaciones encontradas")
        if st.button("Continuar al Paso 2 →", type="primary"):
            save_items(nuevos_items)
            save_step(2)
            st.rerun()

# ══ PASO 2 ══
elif step == 2:
    st.subheader("Paso 2 — Descargar fotos de portada")
    if not items:
        st.warning("No hay publicaciones. Volvé al Paso 1.")
        if st.button("← Volver al Paso 1"):
            save_step(1)
            st.rerun()
        st.stop()

    st.write(f"**{len(items)}** publicaciones listas para descargar")

    if os.path.exists("listo_paso2.txt"):
        st.success("✅ Fotos descargadas correctamente.")
        if st.button("Continuar al Paso 3 →", type="primary"):
            for f in ["listo_paso2.txt", "img_urls.json"]:
                if os.path.exists(f): os.remove(f)
            save_step(3)
            st.rerun()
        st.stop()

    IMG_URLS_FILE = "img_urls.json"
    current_token = get_token() or ""

    if not os.path.exists(IMG_URLS_FILE):
        if st.button("Obtener fotos de portada", type="primary"):
            bar = st.progress(0, text="Obteniendo datos...")
            img_urls = {}
            errores = []
            for i, item_id in enumerate(items):
                bar.progress((i+1)/len(items), text=f"{i+1}/{len(items)}: {item_id}")
                try:
                    r = requests.get(
                        f"https://api.mercadolibre.com/items/{item_id}",
                        headers={"Authorization": f"Bearer {current_token}", "User-Agent": "Mozilla/5.0"},
                        timeout=12)
                    if r.status_code == 200:
                        data = r.json()
                        pics = data.get("pictures", [])
                        url = (pics[0].get("secure_url") or pics[0].get("url","")) if pics else \
                              data.get("thumbnail","").replace("-I.jpg","-O.jpg")
                        if url: img_urls[item_id] = url
                    else:
                        errores.append(f"{item_id}: HTTP {r.status_code}")
                except Exception as e:
                    errores.append(f"{item_id}: {str(e)}")
                time.sleep(0.2)
            bar.progress(1.0, text="Listo")
            if img_urls:
                with open(IMG_URLS_FILE, "w") as f: json.dump(img_urls, f)
                st.rerun()
        st.stop()

    with open(IMG_URLS_FILE) as f:
        img_urls = json.load(f)
    
    st.success(f"✅ {len(img_urls)} URLs listas. Descargá el ZIP:")
    urls_json = json.dumps(img_urls)
    js_component = f"""<!DOCTYPE html><html><body style="margin:0;padding:8px 0;background:transparent;font-family:sans-serif">
    <button id="btn" onclick="go()" style="background:#e53935;color:white;border:none;padding:11px 26px;font-size:15px;border-radius:8px;cursor:pointer;font-weight:700">📥 Descargar ZIP de fotos</button>
    <div id="log" style="margin-top:10px;font-size:13px;color:#ccc"></div>
    <div id="link" style="margin-top:12px"></div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <script>
    async function go() {{
      const btn=document.getElementById('btn'); btn.disabled=true; btn.innerText='⏳ Descargando...';
      const zip=new JSZip(); const entries=Object.entries({urls_json});
      for (let i=0;i<entries.length;i++) {{
        const [id,url]=entries[i];
        try {{ const r=await fetch(url); const b=await r.blob(); zip.file(id+'.jpg',b); }} catch(e) {{}}
      }}
      const blob=await zip.generateAsync({{type:'blob'}});
      const u=URL.createObjectURL(blob);
      document.getElementById('link').innerHTML='<a href="'+u+'" download="portadas_ml.zip" style="display:inline-block;background:#3483FA;color:white;padding:10px 22px;border-radius:8px;font-weight:700;text-decoration:none">📥 Guardar portadas_ml.zip</a>';
      btn.innerText='✅ Listo';
    }}
    </script></body></html>"""
    st.components.v1.html(js_component, height=150)

    if st.button("✅ Ya descargué el ZIP — Continuar al Paso 3", type="primary"):
        with open("listo_paso2.txt","w") as f: f.write("ok")
        save_step(3); st.rerun()

# ══ PASO 3 ══
elif step == 3:
    st.subheader("Paso 3 — Subir fotos con fondo blanco")
    zip_file = st.file_uploader("Subí el ZIP procesado", type=["zip"])
    if zip_file:
        zip_bytes = zip_file.read()
        with open("procesadas.zip","wb") as f: f.write(zip_bytes)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]
        st.success(f"{len(nombres)} fotos encontradas")
        if st.button("Continuar al Paso 4 →", type="primary"):
            save_step(4); st.rerun()

# ══ PASO 4 ══
elif step == 4:
    st.subheader("Paso 4 — Subir a MercadoLibre")
    with zipfile.ZipFile("procesadas.zip") as zf:
        nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]
    
    if st.button("Subir todas las fotos a ML", type="primary"):
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        bar = st.progress(0, text="Iniciando...")
        ok, errores_detalle = 0, []
        
        with zipfile.ZipFile("procesadas.zip") as zf:
            for i, nombre in enumerate(nombres):
                item_id = nombre.split("_resultado")[0].split(".")[0]
                bar.progress((i+1)/len(nombres), text=f"Subiendo {i+1}/{len(nombres)}: {item_id}")
                try:
                    # 1. Obtener fotos actuales
                    r = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers=headers)
                    if r.status_code != 200: continue
                    fotos_restantes = [{"id": p["id"]} for p in r.json().get("pictures", [])[1:]]

                    # 2. Subir nueva imagen (CORRECCIÓN AQUÍ: Acepta 200 y 201)
                    img_data = zf.read(nombre)
                    upload = requests.post(
                        "https://api.mercadolibre.com/pictures/items/upload",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": (nombre, img_data, "image/jpeg")}, timeout=30)
                    
                    if upload.status_code not in (200, 201):
                        errores_detalle.append(f"❌ {item_id}: Error {upload.status_code}")
                        continue
                    
                    nueva_id = upload.json()["id"]

                    # 3. Actualizar ítem
                    update = requests.put(
                        f"https://api.mercadolibre.com/items/{item_id}",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"pictures": [{"id": nueva_id}] + fotos_restantes})
                    
                    if update.status_code in (200, 201): ok += 1
                except Exception as e:
                    errores_detalle.append(f"❌ {item_id}: {str(e)}")
                time.sleep(0.5)

        st.success(f"✅ {ok} publicaciones actualizadas")
        if errores_detalle:
            with st.expander("Ver detalles"):
                for e in errores_detalle: st.text(e)
        if st.button("Volver al inicio"):
            st.session_state.clear(); save_step(1); st.rerun()