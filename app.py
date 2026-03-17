import streamlit as st
import requests
import os
import json
import pandas as pd
import zipfile
import io
import time
from PIL import Image
try:
    from rembg import remove as rembg_remove
    REMBG_DISPONIBLE = True
except ImportError:
    REMBG_DISPONIBLE = False

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
    """Devuelve el token activo. Primero intenta session_state, luego disco, luego renovar."""
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

# ── función fondo blanco ──
def aplicar_fondo_blanco(img_bytes: bytes, canvas_size: int = 1200, ocupacion: float = 0.88) -> bytes:
    """
    Remueve el fondo de una imagen y coloca fondo blanco.
    Retorna los bytes JPEG del resultado.
    Requiere: pip install rembg onnxruntime pillow
    """
    # 1. Remover fondo → imagen RGBA
    resultado_rgba = rembg_remove(img_bytes)
    img = Image.open(io.BytesIO(resultado_rgba)).convert("RGBA")

    # 2. Pegar sobre canvas blanco
    fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fondo.paste(img, mask=img.split()[3])   # usa el canal alpha como máscara
    img_rgb = fondo.convert("RGB")

    # 3. Centrar en canvas cuadrado con margen
    target_max = int(canvas_size * ocupacion)
    ancho, alto = img_rgb.size
    scale = target_max / max(ancho, alto)
    img_rgb = img_rgb.resize((int(ancho * scale), int(alto * scale)), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (canvas_size, canvas_size), (255, 255, 255))
    x = (canvas_size - img_rgb.width) // 2
    y = (canvas_size - img_rgb.height) // 2
    canvas.paste(img_rgb, (x, y))

    # 4. Serializar a JPEG
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=95, subsampling=0, optimize=True)
    return buf.getvalue()

# ── estado desde disco ──
step = load_step()
items = load_items()

# ── header ──
st.markdown('<div class="main-title">⬜ FondoBlanco</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Actualizá las fotos de portada de tus publicaciones de MercadoLibre</div>', unsafe_allow_html=True)

col_r1, col_r2 = st.columns([6,1])
with col_r2:
    if st.button('↺ Reiniciar'):
        for f in ['items.json','step.json','listo_paso2.txt','portadas_descargadas.zip','procesadas.zip', 'img_urls.json']:
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
        auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={ML_SCOPES.replace(' ', '%20')}"
        if st.button("Reconectar con ML"):
            st.session_state.pop("token", None)
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            st.rerun()

# ── indicador de pasos ──
st.divider()
for n, title, desc in [
    (1,"Importar publicaciones","Subí tu planilla Excel"),
    (2,"Descargar y procesar fotos","Se descargan y quita el fondo automáticamente"),
    (3,"Vista previa","Revisá todas las fotos antes de subir"),
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
    st.subheader("Paso 2 — Descargar y procesar fotos")
    if not items:
        st.warning("No hay publicaciones. Volvé al Paso 1.")
        if st.button("← Volver al Paso 1"):
            save_step(1)
            st.rerun()
        st.stop()

    current_token = get_token()
    if not current_token:
        st.error("❌ Tu sesión de MercadoLibre venció. Reconectate sin perder las publicaciones importadas:")
        auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={ML_SCOPES.replace(' ', '%20')}"
        st.markdown(f"**1.** [Hacé click acá para re-autorizar]({auth_url})")
        st.markdown("**2.** Pegá el nuevo código `TG-`:")
        new_code = st.text_input("Nuevo código TG-", placeholder="TG-XXXXXXXXX", key="reconectar_code")
        if st.button("Reconectar", type="primary", key="reconectar_btn") and new_code:
            t = obtener_token_code(new_code.strip().strip('"'))
            if t:
                st.session_state.token = t
                st.success("✅ Reconectado!")
                st.rerun()
            else:
                st.error("Código inválido o vencido.")
        st.stop()

    if not REMBG_DISPONIBLE:
        st.error("❌ La librería `rembg` no está instalada. Agregala al requirements.txt y reiniciá la app.")
        st.stop()

    # Si procesadas.zip ya existe, mostrar opción de continuar
    if os.path.exists("procesadas.zip"):
        with zipfile.ZipFile("procesadas.zip") as zf:
            cant = len([n for n in zf.namelist() if n.upper().startswith("MLA")])
        st.success(f"✅ {cant} fotos ya procesadas.")
        col1, col2 = st.columns([2, 1])
        with col1:
            if st.button("Continuar al Paso 3 →", type="primary"):
                save_step(3)
                st.rerun()
        with col2:
            if st.button("↺ Reprocesar desde cero"):
                if os.path.exists("procesadas.zip"): os.remove("procesadas.zip")
                st.rerun()
        st.stop()

    st.info(f"Se van a descargar y procesar **{len(items)}** fotos directamente desde MercadoLibre. Esto puede tardar unos minutos.")

    if st.button("🧹 Borrar fondo ahora", type="primary"):
        bar = st.progress(0, text="Iniciando...")
        errores = []
        zip_out_buf = io.BytesIO()

        with zipfile.ZipFile(zip_out_buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for i, item_id in enumerate(items):
                bar.progress((i + 1) / len(items), text=f"{i+1}/{len(items)}: {item_id}")
                try:
                    # 1. Obtener URL de portada desde ML API
                    r = requests.get(
                        f"https://api.mercadolibre.com/items/{item_id}",
                        headers={"Authorization": f"Bearer {current_token}", "User-Agent": "Mozilla/5.0"},
                        timeout=12)
                    if r.status_code == 403:
                        new_t = renovar_token()
                        if new_t:
                            current_token = new_t
                            st.session_state.token = new_t
                            r = requests.get(
                                f"https://api.mercadolibre.com/items/{item_id}",
                                headers={"Authorization": f"Bearer {current_token}", "User-Agent": "Mozilla/5.0"},
                                timeout=12)
                    if r.status_code != 200:
                        errores.append(f"{item_id}: HTTP {r.status_code}")
                        continue
                    data = r.json()
                    pics = data.get("pictures", [])
                    url = (pics[0].get("secure_url") or pics[0].get("url", "")) if pics else \
                          data.get("thumbnail", "").replace("-I.jpg", "-O.jpg")
                    if not url:
                        errores.append(f"{item_id}: sin URL de imagen")
                        continue

                    # 2. Descargar la imagen
                    img_r = requests.get(url, timeout=20)
                    if img_r.status_code != 200 or len(img_r.content) < 500:
                        errores.append(f"{item_id}: error descargando imagen")
                        continue

                    # 3. Aplicar fondo blanco
                    resultado_bytes = aplicar_fondo_blanco(img_r.content)
                    zf_out.writestr(f"{item_id}_resultado.jpg", resultado_bytes)

                except Exception as e:
                    errores.append(f"{item_id}: {str(e)}")
                time.sleep(0.1)

        bar.progress(1.0, text="✅ Completado")

        zip_out_bytes = zip_out_buf.getvalue()
        with open("procesadas.zip", "wb") as f:
            f.write(zip_out_bytes)

        if errores:
            with st.expander(f"⚠️ {len(errores)} errores"):
                for e in errores: st.text(e)

        st.success(f"✅ {len(items) - len(errores)} fotos procesadas con fondo blanco")
        st.rerun()

# ══ PASO 3 ══
elif step == 3:
    st.subheader("Paso 3 — Vista previa de fotos procesadas")
    if st.button("← Volver al Paso 2"):
        save_step(2)
        st.rerun()

    if not os.path.exists("procesadas.zip"):
        st.warning("No hay fotos procesadas. Volvé al Paso 2.")
        st.stop()

    with open("procesadas.zip", "rb") as f:
        zip_bytes = f.read()

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        nombres_prev = [n for n in zf.namelist() if n.upper().startswith("MLA")]

    st.success(f"✅ {len(nombres_prev)} fotos listas para subir")
    st.download_button(
        label="💾 Descargar ZIP procesado (opcional)",
        data=zip_bytes,
        file_name="procesadas_fondo_blanco.zip",
        mime="application/zip"
    )
    st.divider()
    st.write(f"**Vista previa de las {len(nombres_prev)} fotos procesadas:**")

    COLS = 5
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for fila_start in range(0, len(nombres_prev), COLS):
            fila = nombres_prev[fila_start:fila_start + COLS]
            cols = st.columns(COLS)
            for idx, nombre in enumerate(fila):
                with cols[idx]:
                    img = Image.open(io.BytesIO(zf.read(nombre)))
                    st.image(img, caption=nombre.split("_resultado")[0], use_container_width=True)

    st.divider()
    if st.button("Continuar al Paso 4 →", type="primary"):
        save_step(4)
        st.rerun()

# ══ PASO 4 ══
elif step == 4:
    st.subheader("Paso 4 — Subir a MercadoLibre")

    if not os.path.exists("procesadas.zip"):
        st.warning("No hay fotos procesadas. Volvé al Paso 3.")
        if st.button("← Volver al Paso 3"):
            save_step(3)
            st.rerun()
        st.stop()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def procesar_imagen(nombre, zf, token, RETRIES, DELAY):
        item_id = nombre.split("_resultado")[0].split(".")[0]

        for intento in range(RETRIES):
            try:
                headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}

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
                canvas.save(buf, format="JPEG", quality=98, subsampling=0, optimize=True)
                img_data_final = buf.getvalue()

                upload = requests.post(
                    "https://api.mercadolibre.com/pictures/items/upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (nombre, img_data_final, "image/jpeg")},
                    timeout=30
                )

                if upload.status_code not in (200,201):
                    raise Exception(f"UPLOAD {upload.status_code}")

                nueva_id = upload.json()["id"]

                update = requests.put(
                    f"https://api.mercadolibre.com/items/{item_id}",
                    headers={**headers, "Content-Type":"application/json"},
                    json={"pictures":[{"id":nueva_id}] + fotos_restantes},
                    timeout=15
                )

                if update.status_code not in (200,201):
                    raise Exception(f"UPDATE {update.status_code}")

                time.sleep(DELAY)
                return ("ok", item_id)

            except Exception as e:
                if intento == RETRIES - 1:
                    return ("error", f"{item_id}: {str(e)}")
                time.sleep(1)

    with zipfile.ZipFile("procesadas.zip") as zf:
        nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]

    st.write(f"**{len(nombres)}** fotos listas para subir a MercadoLibre")

    if st.button("Subir todas las fotos a ML", type="primary"):

        DELAY = 0.6
        RETRIES = 3
        BATCH_SIZE = 80
        MAX_WORKERS = 3

        bar = st.progress(0, text="Iniciando...")

        ok = 0
        errores_detalle = []

        total = len(nombres)

        with zipfile.ZipFile("procesadas.zip") as zf:

            for i in range(0, total, BATCH_SIZE):

                lote = nombres[i:i+BATCH_SIZE]
                st.info(f"Procesando lote {i} a {i+len(lote)}")

                futures = []

                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    for nombre in lote:
                        futures.append(executor.submit(
                            procesar_imagen, nombre, zf, token, RETRIES, DELAY
                        ))

                    completados = 0

                    for future in as_completed(futures):
                        resultado, data = future.result()

                        completados += 1
                        progreso_global = (i + completados) / total

                        bar.progress(progreso_global, text=f"{i+completados}/{total}")

                        if resultado == "ok":
                            ok += 1
                        else:
                            errores_detalle.append(data)

                st.info("⏸️ Pausa entre lotes...")
                time.sleep(5)

        bar.progress(1.0, text="Completado")

        if ok:
            st.success(f"✅ {ok} publicaciones actualizadas")

        if errores_detalle:
            st.warning(f"⚠️ {len(errores_detalle)} errores")
            with st.expander("Ver detalle"):
                for e in errores_detalle:
                    st.text(e)

        if st.button("↺ Volver al inicio"):
            for f in [
                'items.json',
                'step.json',
                'listo_paso2.txt',
                'portadas_descargadas.zip',
                'procesadas.zip',
                'img_urls.json'
            ]:
                if os.path.exists(f):
                    os.remove(f)
            st.session_state.clear()
            save_step(1)
            st.rerun()