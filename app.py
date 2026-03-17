import streamlit as st
import requests
import zipfile
import io
import time
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="Optimizador ML", layout="wide")

st.title("📦 Optimización de imágenes para Mercado Libre")

# =========================
# 🔐 TOKEN (AJUSTÁ ESTO)
# =========================

TOKEN = "TU_ACCESS_TOKEN"

def get_token():
    return TOKEN

def renovar_token():
    pass  # opcional si usás refresh

# =========================
# 🧠 PROCESAMIENTO
# =========================

def procesar_imagen(nombre, zf, RETRIES, DELAY):
    item_id = nombre.split("_resultado")[0].split(".")[0]

    for intento in range(RETRIES):
        try:
            token_actual = get_token()

            headers = {
                "Authorization": f"Bearer {token_actual}"
            }

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

            canvas_size = 1200
            ocupacion = 0.88
            target_max = int(canvas_size * ocupacion)

            ancho, alto = img.size
            scale = target_max / max(ancho, alto)

            nuevo_ancho = int(ancho * scale)
            nuevo_alto = int(alto * scale)

            img = img.resize((nuevo_ancho, nuevo_alto), Image.Resampling.LANCZOS)

            canvas = Image.new("RGB", (canvas_size, canvas_size), (255,255,255))
            x = (canvas_size - nuevo_ancho) // 2
            y = (canvas_size - nuevo_alto) // 2
            canvas.paste(img, (x, y))

            buf = io.BytesIO()
            canvas.save(buf, format="JPEG", quality=98)
            final_img = buf.getvalue()

            upload = requests.post(
                "https://api.mercadolibre.com/pictures/items/upload",
                headers={"Authorization": f"Bearer {token_actual}"},
                files={"file": (nombre, final_img, "image/jpeg")}
            )

            if upload.status_code not in (200,201):
                raise Exception(f"UPLOAD {upload.status_code}")

            nueva_id = upload.json()["id"]

            update = requests.put(
                f"https://api.mercadolibre.com/items/{item_id}",
                headers={**headers, "Content-Type":"application/json"},
                json={"pictures":[{"id":nueva_id}] + fotos_restantes}
            )

            if update.status_code not in (200,201):
                raise Exception(f"UPDATE {update.status_code}")

            time.sleep(DELAY)
            return ("ok", item_id)

        except Exception as e:
            if intento == RETRIES - 1:
                return ("error", f"{item_id}: {str(e)}")
            time.sleep(1)

# =========================
# 📤 SUBIDA ZIP
# =========================

st.subheader("1️⃣ Subir ZIP de imágenes procesadas")

archivo = st.file_uploader("Subí el ZIP", type=["zip"])

nombres = []

if archivo:
    with zipfile.ZipFile(archivo) as z:
        nombres = z.namelist()
    st.success(f"{len(nombres)} imágenes cargadas")

# =========================
# 🚀 EJECUCIÓN
# =========================

st.subheader("2️⃣ Subir a Mercado Libre")

if st.button("Subir todas las fotos", type="primary") and archivo:

    DELAY = 0.6
    RETRIES = 3
    BATCH_SIZE = 80
    MAX_WORKERS = 3

    bar = st.progress(0)
    ok = 0
    errores = []

    total = len(nombres)

    with zipfile.ZipFile(archivo) as zf:

        for i in range(0, total, BATCH_SIZE):

            lote = nombres[i:i+BATCH_SIZE]
            st.info(f"Lote {i} a {i+len(lote)}")

            futures = []

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for nombre in lote:
                    futures.append(
                        executor.submit(procesar_imagen, nombre, zf, RETRIES, DELAY)
                    )

                completados = 0

                for future in as_completed(futures):
                    resultado, data = future.result()

                    completados += 1
                    progreso = (i + completados) / total
                    bar.progress(progreso)

                    if resultado == "ok":
                        ok += 1
                    else:
                        errores.append(data)

            st.info("Pausa...")
            time.sleep(5)

    bar.progress(1.0)

    st.success(f"✅ {ok} OK")

    if errores:
        st.warning(f"⚠️ {len(errores)} errores")
        with st.expander("Ver errores"):
            for e in errores:
                st.text(e)