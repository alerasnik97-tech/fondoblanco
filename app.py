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

# ── funciones de guardado ──
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

# ── flujo principal ──
step = load_step()
items = load_items()

st.title("⬜ FondoBlanco")

with st.sidebar:
    if st.button('↺ Reiniciar todo'):
        for f in [ITEMS_FILE, STEP_FILE, 'img_urls.json', 'procesadas.zip', TOKEN_FILE]:
            if os.path.exists(f): os.remove(f)
        st.session_state.clear()
        st.rerun()

token = get_token()
if not token:
    auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={ML_SCOPES.replace(' ', '%20')}"
    st.link_button("1. Autorizar Mercado Libre", auth_url)
    code = st.text_input("2. Pegá el código TG- aquí:")
    if st.button("Conectar"):
        t = obtener_token_code(code.strip())
        if t: st.rerun()
    st.stop()

# ══ PASOS 1, 2, 3 (Igual a tu archivo) ══
if step == 1:
    archivo = st.file_uploader("Subí tu Excel", type=["xlsx"])
    if archivo:
        df = pd.read_excel(archivo, sheet_name="Publicaciones", header=None)
        nuevos = df.iloc[4:, 1].dropna().astype(str).tolist()
        nuevos = [i for i in nuevos if i.startswith("MLA")]
        if st.button(f"Importar {len(nuevos)} ítems"):
            save_items(nuevos); save_step(2); st.rerun()

elif step == 2:
    if st.button("Obtener fotos de portada"):
        bar = st.progress(0)
        urls = {}
        for i, item_id in enumerate(items):
            r = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                urls[item_id] = r.json()["pictures"][0]["secure_url"]
            bar.progress((i+1)/len(items))
        with open("img_urls.json", "w") as f: json.dump(urls, f)
        st.rerun()
    if os.path.exists("img_urls.json"):
        st.success("Fotos listas")
        if st.button("Ir al paso 3"): save_step(3); st.rerun()

elif step == 3:
    zip_subido = st.file_uploader("Subí el ZIP procesado", type="zip")
    if zip_subido:
        with open("procesadas.zip", "wb") as f: f.write(zip_subido.read())
        save_step(4); st.rerun()

# ══ PASO 4 (EL QUE ESTABA MAL) ══
elif step == 4:
    st.subheader("Paso 4 — Subir a MercadoLibre")
    with zipfile.ZipFile("procesadas.zip") as zf:
        nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]
    
    if st.button("Subir todas las fotos a ML", type="primary"):
        bar = st.progress(0)
        ok, errores = 0, []
        with zipfile.ZipFile("procesadas.zip") as zf:
            for i, nombre in enumerate(nombres):
                item_id = nombre.split("_")[0].split(".")[0]
                try:
                    # 1. Obtener fotos actuales para no borrarlas
                    r_item = requests.get(f"https://api.mercadolibre.com/items/{item_id}", 
                                          headers={"Authorization": f"Bearer {token}"})
                    pics_viejas = [{"id": p["id"]} for p in r_item.json().get("pictures", [])[1:]]

                    # 2. Subir la nueva foto
                    up = requests.post("https://api.mercadolibre.com/pictures/items/upload",
                                       headers={"Authorization": f"Bearer {token}"},
                                       files={"file": (nombre, zf.read(nombre), "image/jpeg")})
                    
                    # AQUÍ ESTÁ EL ARREGLO: Aceptar 200 y 201
                    if up.status_code in (200, 201):
                        nueva_id = up.json()["id"]
                        # 3. Actualizar el ítem
                        requests.put(f"https://api.mercadolibre.com/items/{item_id}",
                                     headers={"Authorization": f"Bearer {token}"},
                                     json={"pictures": [{"id": nueva_id}] + pics_viejas})
                        ok += 1
                    else:
                        errores.append(f"{item_id}: Error {up.status_code}")
                except Exception as e:
                    errores.append(f"{item_id}: {str(e)}")
                bar.progress((i+1)/len(nombres))
        
        st.success(f"Proceso terminado: {ok} actualizadas con éxito.")
        if errores: st.error(f"Errores: {len(errores)}")
        if st.button("Volver al inicio"):
            save_step(1); st.rerun()