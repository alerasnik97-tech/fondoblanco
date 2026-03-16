import streamlit as st
import requests
import os
import json
import pandas as pd
import zipfile
import io
import time
from PIL import Image

CLIENT_ID     = "4692870472324774"
CLIENT_SECRET = "TU_CLIENT_SECRET"
REDIRECT_URI  = "https://httpbin.org/get"
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
    if "token" in st.session_state and st.session_state.token:
        return st.session_state.token
    t = renovar_token()
    if t: st.session_state.token = t
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
        for f in ['items.json','step.json','listo_paso2.txt','portadas_descargadas.zip','procesadas.zip']:
            if os.path.exists(f): os.remove(f)
        st.rerun()

# ── login ──
token = get_token()
if not token:
    st.divider()
    st.subheader("Conectar con MercadoLibre")
    auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
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
        st.success("Fotos descargadas. Podés continuar al Paso 3.")
        if st.button("Continuar al Paso 3 →", type="primary"):
            os.remove("listo_paso2.txt")
            save_step(3)
            st.rerun()
        st.stop()

    if st.button("Descargar todas las fotos", type="primary"):
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        bar = st.progress(0, text="Iniciando...")
        fotos = {}
        for i, item_id in enumerate(items):
            bar.progress((i+1)/len(items), text=f"Descargando {i+1}/{len(items)}: {item_id}")
            try:
                r = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers=headers, timeout=10)
                r.raise_for_status()
                data = r.json()
                pics = data.get("pictures", [])
                if pics:
                    img_url = pics[0].get("secure_url") or pics[0].get("url","")
                else:
                    img_url = data.get("thumbnail","").replace("-I.jpg","-O.jpg")
                if img_url:
                    img_r = requests.get(img_url, headers=headers, timeout=15)
                    img_r.raise_for_status()
                    fotos[item_id] = img_r.content
            except: pass
            time.sleep(0.2)

        bar.progress(1.0, text=f"Listo — {len(fotos)} fotos descargadas")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            for iid, content in fotos.items():
                zf.writestr(f"{iid}.jpg", content)
        zip_buf.seek(0)
        zip_bytes = zip_buf.getvalue()

        with open("portadas_descargadas.zip","wb") as f: f.write(zip_bytes)

        st.download_button("⬇ Descargar ZIP con todas las fotos", data=zip_bytes,
                           file_name="portadas_ml.zip", mime="application/zip")
        st.info("Procesá el ZIP en Claude para borrar el fondo, luego continuá.")
        with open("listo_paso2.txt","w") as f: f.write("ok")
        st.rerun()

# ══ PASO 3 ══
elif step == 3:
    st.subheader("Paso 3 — Subir fotos con fondo blanco")
    st.info("Subí el ZIP procesado por Claude. Los archivos deben llamarse: MLA1234567890_resultado.jpg")
    zip_file = st.file_uploader("Subí el ZIP procesado", type=["zip"])
    if zip_file:
        zip_bytes = zip_file.read()
        with open("procesadas.zip","wb") as f: f.write(zip_bytes)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]
        st.success(f"{len(nombres)} fotos procesadas encontradas")
        if nombres:
            cols = st.columns(min(5, len(nombres)))
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for idx, nombre in enumerate(nombres[:5]):
                    with cols[idx]:
                        img = Image.open(io.BytesIO(zf.read(nombre)))
                        st.image(img, caption=nombre.split("_resultado")[0], use_container_width=True)
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

    with zipfile.ZipFile("procesadas.zip") as zf:
        nombres = [n for n in zf.namelist() if n.upper().startswith("MLA")]
    st.write(f"**{len(nombres)}** fotos listas para subir a MercadoLibre")

    if st.button("Subir todas las fotos a ML", type="primary"):
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        bar = st.progress(0, text="Iniciando...")
        ok, errores = 0, 0
        with zipfile.ZipFile("procesadas.zip") as zf:
            for i, nombre in enumerate(nombres):
                item_id = nombre.split("_resultado")[0].split(".")[0]
                bar.progress((i+1)/len(nombres), text=f"Subiendo {i+1}/{len(nombres)}: {item_id}")
                try:
                    r = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers=headers, timeout=10)
                    r.raise_for_status()
                    pictures = r.json().get("pictures", [])
                    fotos_restantes = [{"id": p["id"]} for p in pictures[1:]]
                    img_data = zf.read(nombre)
                    upload = requests.post(
                        "https://api.mercadolibre.com/pictures/items/upload",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": (nombre, img_data, "image/jpeg")}, timeout=30)
                    upload.raise_for_status()
                    nueva_id = upload.json()["id"]
                    update = requests.put(
                        f"https://api.mercadolibre.com/items/{item_id}",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"pictures": [{"id": nueva_id}] + fotos_restantes}, timeout=15)
                    update.raise_for_status()
                    ok += 1
                except: errores += 1
                time.sleep(0.5)

        bar.progress(1.0, text="Completado")
        if ok: st.success(f"✅ {ok} publicaciones actualizadas en MercadoLibre")
        if errores: st.warning(f"⚠️ {errores} errores")
        if st.button("Volver al inicio", type="primary"):
            save_step(1)
            st.rerun()
