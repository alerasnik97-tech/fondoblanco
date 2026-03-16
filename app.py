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

# ── FUNCIONES DE LIMPIEZA TOTAL ──
def borrar_sesion_completa():
    archivos_a_borrar = [TOKEN_FILE, ITEMS_FILE, STEP_FILE, 'img_urls.json', 'listo_paso2.txt', 'procesadas.zip']
    for f in archivos_a_borrar:
        if os.path.exists(f):
            os.remove(f)
    st.session_state.clear()

# ── HELPERS ──
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

def obtener_token_code(code):
    r = requests.post("https://api.mercadolibre.com/oauth/token", data={
        "grant_type":"authorization_code","client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET,"code":code,"redirect_uri":REDIRECT_URI})
    if r.status_code == 200:
        d = r.json()
        guardar_token(d)
        return d["access_token"]
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
    return None

# ── HEADER Y DISEÑO ──
st.markdown('<h1 style="color:#3483FA;">⬜ FondoBlanco</h1>', unsafe_allow_html=True)

with st.sidebar:
    st.title("Configuración")
    if st.button("🔴 CERRAR SESIÓN Y RECONECTAR", help="Borra el token viejo para poner uno nuevo"):
        borrar_sesion_completa()
        st.rerun()
    
    if st.button("↺ Reiniciar pasos"):
        if os.path.exists(STEP_FILE): os.remove(STEP_FILE)
        st.rerun()

# ── LOGICA DE LOGIN ──
token = get_token()
if not token:
    st.info("### Paso 0: Conectar con Mercado Libre")
    auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={ML_SCOPES.replace(' ', '%20')}"
    st.markdown(f"1. [Hacé clic aquí para Autorizar la App]({auth_url})")
    code = st.text_input("2. Pegá el código TG- aquí:", placeholder="TG-XXXXXXXXX")
    if st.button("Vincular Cuenta", type="primary") and code:
        t = obtener_token_code(code.strip().strip('"'))
        if t:
            st.session_state.token = t
            st.success("¡Conectado con éxito!")
            st.rerun()
        else:
            st.error("El código es inválido. Asegurate de copiar todo desde 'TG-'")
    st.stop()

# ── PASOS ──
step = load_step()
items = load_items()

# ══ PASO 1 ══
if step == 1:
    st.subheader("Paso 1: Cargar Excel")
    archivo = st.file_uploader("Subí tu planilla", type=["xlsx"])
    if archivo:
        df = pd.read_excel(archivo, sheet_name="Publicaciones", header=None)
        nuevos_items = df.iloc[4:, 1].dropna().astype(str).tolist()
        nuevos_items = [i for i in nuevos_items if i.startswith("MLA")]
        if st.button(f"Importar {len(nuevos_items)} publicaciones"):
            save_items(nuevos_items)
            save_step(2)
            st.rerun()

# ══ PASO 2 ══
elif step == 2:
    st.subheader("Paso 2: Descargar Fotos")
    st.write(f"Publicaciones: {len(items)}")
    
    if st.button("Obtener fotos de portada", type="primary"):
        bar = st.progress(0)
        img_urls, errores = {}, []
        for i, item_id in enumerate(items):
            bar.progress((i+1)/len(items))
            r = requests.get(f"https://api.mercadolibre.com/items/{item_id}",
                             headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                data = r.json()
                pics = data.get("pictures", [])
                if pics: img_urls[item_id] = pics[0]["secure_url"].replace("-I.jpg", "-O.jpg")
            else:
                errores.append(f"{item_id}: Error {r.status_code}")
        
        if img_urls:
            with open("img_urls.json", "w") as f: json.dump(img_urls, f)
            st.rerun()
        else:
            st.error("❌ No se pudo obtener ninguna foto. Los permisos fallaron.")
            if st.button("Forzar reconexión ahora"):
                borrar_sesion_completa()
                st.rerun()

    if os.path.exists("img_urls.json"):
        with open("img_urls.json") as f: urls = json.load(f)
        st.success(f"Se encontraron {len(urls)} fotos.")
        
        # JS para descargar
        js = f"""
        <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
        <button onclick="descargar()" style="background:#3483FA;color:white;padding:10px;border:none;border-radius:5px;cursor:pointer">📥 Descargar ZIP</button>
        <script>
        async function descargar() {{
            const zip = new JSZip();
            const URLS = {json.dumps(urls)};
            for (const [id, url] of Object.entries(URLS)) {{
                const r = await fetch(url);
                const b = await r.blob();
                zip.file(id+".jpg", b);
            }}
            const content = await zip.generateAsync({{type:"blob"}});
            const a = document.createElement("a");
            a.href = URL.createObjectURL(content);
            a.download = "fotos.zip";
            a.click();
        }}
        </script>
        """
        st.components.v1.html(js, height=50)
        if st.button("Ir al Paso 3"):
            save_step(3); st.rerun()

# ══ PASO 3 ══
elif step == 3:
    st.subheader("Paso 3: Subir procesadas")
    subido = st.file_uploader("Subí el ZIP de Claude", type="zip")
    if subido:
        with open("procesadas.zip", "wb") as f: f.write(subido.read())
        save_step(4); st.rerun()

# ══ PASO 4 ══
elif step == 4:
    st.subheader("Paso 4: Subir a ML")
    if st.button("Iniciar subida final"):
        with zipfile.ZipFile("procesadas.zip") as zf:
            nombres = [n for n in zf.namelist() if "MLA" in n.upper()]
        
        ok = 0
        bar = st.progress(0)
        for i, n in enumerate(nombres):
            item_id = n.split(".")[0].split("_")[0]
            # 1. Upload foto
            up = requests.post("https://api.mercadolibre.com/pictures/items/upload",
                               headers={"Authorization": f"Bearer {token}"},
                               files={"file": (n, zf.read(n), "image/jpeg")})
            
            if up.status_code in (200, 201):
                nueva_id = up.json()["id"]
                # 2. Get item para no borrar el resto de fotos
                item_data = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers={"Authorization": f"Bearer {token}"}).json()
                viejas = [{"id": p["id"]} for p in item_data.get("pictures", [])[1:]]
                # 3. Update
                requests.put(f"https://api.mercadolibre.com/items/{item_id}",
                             headers={"Authorization": f"Bearer {token}"},
                             json={"pictures": [{"id": nueva_id}] + viejas})
                ok += 1
            bar.progress((i+1)/len(nombres))
        st.success(f"¡Listo! {ok} fotos actualizadas.")
        if st.button("Finalizar y limpiar"):
            borrar_sesion_completa()
            st.rerun()