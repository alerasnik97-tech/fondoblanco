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
        st.session_state.clear()
        st.rerun()

# ── login ──
token = get_token()
if not token:
    st.divider()
    st.subheader("Conectar con MercadoLibre")
    auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={ML_SCOPES.replace(' ', '%20')}"
    st.markdown(f"**Paso 1:** [Hacé click acá para autorizar]({auth_url})")
    code = st.text_input("Código TG-", placeholder="TG-XXXXXXXXX")
    if st.button("Conectar", type="primary") and code:
        t = obtener_token_code(code.strip().strip('"'))
        if t:
            st.session_state.token = t
            st.rerun()
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
    st.markdown(f'<div class="step-box {cls}">{icon} <strong>Paso {n}: {title}</strong><br><small style="color:#888">{desc}</small></div>', unsafe_allow_html=True)
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
        st.warning("No hay publicaciones cargadas.")
        if st.button("← Volver al Paso 1"):
            save_step(1); st.rerun()
        st.stop()

    st.write(f"**{len(items)}** publicaciones listas para descargar")
    IMG_URLS_FILE = "img_urls.json"

    if not os.path.exists(IMG_URLS_FILE):
        if st.button("Obtener fotos de portada", type="primary"):
            bar = st.progress(0, text="Consultando Mercado Libre...")
            img_urls, errores = {}, []
            for i, item_id in enumerate(items):
                bar.progress((i+1)/len(items), text=f"Buscando {item_id}...")
                try:
                    r = requests.get(f"https://api.mercadolibre.com/items/{item_id}",
                                     headers={"Authorization": f"Bearer {token}"}, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        pics = data.get("pictures", [])
                        url = pics[0].get("secure_url") if pics else data.get("thumbnail")
                        if url: img_urls[item_id] = url.replace("-I.jpg", "-O.jpg")
                    else:
                        errores.append(f"{item_id}: Error {r.status_code}")
                except:
                    errores.append(f"{item_id}: Error de conexión")
                time.sleep(0.1)
            
            if img_urls:
                with open(IMG_URLS_FILE, "w") as f: json.dump(img_urls, f)
                if errores: st.warning(f"Se omitieron {len(errores)} publicaciones por errores.")
                st.rerun()
            else:
                st.error("❌ No se pudo obtener ninguna foto. Probablemente el Token venció o no tenés permisos.")
                st.info("Hacé clic en 'Reconectar con ML' en el menú de la izquierda.")
        st.stop()

    # Si llegamos acá, las URLs existen
    with open(IMG_URLS_FILE) as f: urls_dict = json.load(f)
    st.success(f"✅ {len(urls_dict)} fotos encontradas.")
    
    # Componente de descarga
    urls_json = json.dumps(urls_dict)
    js_component = f"""
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <button id="btn" onclick="go()" style="background:#3483FA;color:white;border:none;padding:12px 24px;border-radius:8px;cursor:pointer;font-weight:bold">📥 Descargar ZIP de fotos</button>
    <script>
    async function go() {{
      const btn=document.getElementById('btn'); btn.innerText='⏳ Procesando...';
      const zip=new JSZip(); const entries=Object.entries({urls_json});
      for (const [id, url] of entries) {{
        try {{ const r=await fetch(url); const b=await r.blob(); zip.file(id+'.jpg', b); }} catch(e) {{}}
      }}
      const content=await zip.generateAsync({{type:'blob'}});
      const link=document.createElement('a'); link.href=URL.createObjectURL(content);
      link.download='portadas_ml.zip'; link.click();
      btn.innerText='✅ ZIP Descargado';
    }}
    </script>
    """
    st.components.v1.html(js_component, height=100)
    
    if st.button("Ya descargué las fotos — Continuar al Paso 3 →"):
        save_step(3); st.rerun()

# ══ PASO 3 ══
elif step == 3:
    st.subheader("Paso 3 — Subir fotos procesadas")
    zip_file = st.file_uploader("Subí el ZIP con las fotos de fondo blanco", type=["zip"])
    if zip_file:
        with open("procesadas.zip", "wb") as f: f.write(zip_file.read())
        st.success("ZIP cargado correctamente")
        if st.button("Continuar al Paso 4 →", type="primary"):
            save_step(4); st.rerun()

# ══ PASO 4 ══
elif step == 4:
    st.subheader("Paso 4 — Subir a Mercado Libre")
    if st.button("Subir todas las fotos", type="primary"):
        with zipfile.ZipFile("procesadas.zip") as zf:
            nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]
        
        bar = st.progress(0)
        ok, errs = 0, []
        for i, nombre in enumerate(nombres):
            item_id = nombre.split(".")[0].split("_")[0]
            try:
                # 1. Subir imagen
                img_data = zf.read(nombre)
                up = requests.post("https://api.mercadolibre.com/pictures/items/upload",
                                   headers={"Authorization": f"Bearer {token}"},
                                   files={"file": (nombre, img_data, "image/jpeg")})
                
                # CORRECCIÓN: Acepta 201 Created
                if up.status_code in (200, 201):
                    nueva_id = up.json()["id"]
                    # 2. Actualizar ítem
                    r_item = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers={"Authorization": f"Bearer {token}"})
                    pics = [{"id": nueva_id}] + [{"id": p["id"]} for p in r_item.json().get("pictures", [])[1:]]
                    requests.put(f"https://api.mercadolibre.com/items/{item_id}", 
                                 headers={"Authorization": f"Bearer {token}"}, json={"pictures": pics})
                    ok += 1
                else:
                    errs.append(f"{item_id}: Error {up.status_code}")
            except:
                errs.append(f"{item_id}: Error inesperado")
            bar.progress((i+1)/len(nombres))
        
        st.success(f"Proceso terminado. {ok} actualizadas.")
        if errs: st.error(f"Hubo {len(errs)} errores.")
        if st.button("Finalizar"):
            for f in ['items.json','step.json','img_urls.json','procesadas.zip']:
                if os.path.exists(f): os.remove(f)
            save_step(1); st.rerun()