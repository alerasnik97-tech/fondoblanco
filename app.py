import streamlit as st
import requests
import os
import json
import pandas as pd
import zipfile
import io
import time
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── CONFIGURACIÓN DE SECRETOS ──
try:
    CLIENT_ID     = st.secrets["CLIENT_ID"]
    CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
except KeyError:
    st.error("Faltan las credenciales en los Secretos")
    st.stop()

REDIRECT_URI  = "https://httpbin.org/get"
ML_SCOPES     = "offline_access read_listings write_listings"
TOKEN_FILE    = "ml_token.json"
ITEMS_FILE    = "items.json"
STEP_FILE     = "step.json"

st.set_page_config(page_title="FondoBlanco", layout="wide")

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

def renovar_token():
    if not os.path.exists(TOKEN_FILE): return None
    with open(TOKEN_FILE) as f: saved = json.load(f)
    r = requests.post("https://api.mercadolibre.com/oauth/token", data={
        "grant_type":"refresh_token",
        "client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET,
        "refresh_token":saved["refresh_token"]
    })
    if r.status_code == 200:
        d = r.json()
        guardar_token(d)
        return d["access_token"]
    return None

def get_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            saved = json.load(f)
            return saved.get("access_token")
    return renovar_token()

# ── WORKER PARALELO ──
def procesar_imagen(nombre, zf, RETRIES, DELAY):
    item_id = nombre.split("_resultado")[0].split(".")[0]

    for intento in range(RETRIES):
        try:
            token = get_token()

            headers = {"Authorization": f"Bearer {token}"}

            r = requests.get(
                f"https://api.mercadolibre.com/items/{item_id}",
                headers=headers,
                timeout=10
            )

            if r.status_code != 200:
                raise Exception(f"GET {r.status_code}")

            pictures = r.json().get("pictures", [])
            fotos_restantes = [{"id": p["id"]} for p in pictures[1:]]

            img_data = zf.read(nombre)
            img = Image.open(io.BytesIO(img_data)).convert("RGB")

            canvas = Image.new("RGB", (1200,1200), (255,255,255))

            scale = 1050 / max(img.size)
            img = img.resize(
                (int(img.width*scale), int(img.height*scale)),
                Image.Resampling.LANCZOS
            )

            x = (1200 - img.width)//2
            y = (1200 - img.height)//2
            canvas.paste(img, (x,y))

            buf = io.BytesIO()
            canvas.save(buf, format="JPEG", quality=98)
            img_final = buf.getvalue()

            upload = requests.post(
                "https://api.mercadolibre.com/pictures/items/upload",
                headers=headers,
                files={"file": (nombre, img_final, "image/jpeg")}
            )

            if upload.status_code not in (200,201):
                raise Exception("UPLOAD")

            nueva_id = upload.json()["id"]

            update = requests.put(
                f"https://api.mercadolibre.com/items/{item_id}",
                headers={**headers, "Content-Type":"application/json"},
                json={"pictures":[{"id":nueva_id}] + fotos_restantes}
            )

            if update.status_code not in (200,201):
                raise Exception("UPDATE")

            time.sleep(DELAY)
            return ("ok", item_id)

        except Exception as e:
            if intento == RETRIES - 1:
                return ("error", f"{item_id}: {str(e)}")
            time.sleep(1)

# ── UI ──
step = load_step()
items = load_items()

st.title("⬜ Fondo Blanco ML")

# PASO 1
if step == 1:
    archivo = st.file_uploader("Subí Excel", type=["xlsx"])
    if archivo:
        df = pd.read_excel(archivo, header=None)
        nuevos_items = df.iloc[4:,1].dropna().astype(str).tolist()
        save_items(nuevos_items)
        save_step(2)
        st.rerun()

# PASO 2 (simplificado)
elif step == 2:
    st.write(f"{len(items)} items cargados")
    if st.button("Continuar"):
        save_step(3)
        st.rerun()

# PASO 3
elif step == 3:
    zip_file = st.file_uploader("Subí ZIP procesado", type=["zip"])
    if zip_file:
        with open("procesadas.zip","wb") as f:
            f.write(zip_file.read())
        save_step(4)
        st.rerun()

# PASO 4 (🔥 PRO)
elif step == 4:

    with zipfile.ZipFile("procesadas.zip") as zf:
        nombres = [n for n in zf.namelist() if n.startswith("MLA")]

    st.write(f"{len(nombres)} imágenes")

    DELAY = 0.6
    RETRIES = 3
    BATCH_SIZE = 80
    MAX_WORKERS = 3

    if st.button("Subir todo"):

        bar = st.progress(0)
        ok = 0
        errores = []

        total = len(nombres)

        with zipfile.ZipFile("procesadas.zip") as zf:

            for i in range(0, total, BATCH_SIZE):

                lote = nombres[i:i+BATCH_SIZE]

                futures = []

                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

                    for nombre in lote:
                        futures.append(executor.submit(
                            procesar_imagen, nombre, zf, RETRIES, DELAY
                        ))

                    done = 0

                    for future in as_completed(futures):
                        res, data = future.result()
                        done += 1

                        bar.progress((i+done)/total)

                        if res == "ok":
                            ok += 1
                        else:
                            errores.append(data)

                time.sleep(5)

        st.success(f"OK: {ok}")

        if errores:
            st.warning(f"Errores: {len(errores)}")
            for e in errores:
                st.text(e)