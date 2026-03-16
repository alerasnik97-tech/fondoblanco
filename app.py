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

    test_token = get_token()
    if not test_token:
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
                    if r.status_code == 403:
                        new_t = renovar_token()
                        if new_t:
                            current_token = new_t
                            st.session_state.token = new_t
                            r = requests.get(
                                f"https://api.mercadolibre.com/items/{item_id}",
                                headers={"Authorization": f"Bearer {current_token}", "User-Agent": "Mozilla/5.0"},
                                timeout=12)
                    if r.status_code == 200:
                        data = r.json()
                        pics = data.get("pictures", [])
                        url = (pics[0].get("secure_url") or pics[0].get("url","")) if pics else \
                              data.get("thumbnail","").replace("-I.jpg","-O.jpg")
                        if url:
                            img_urls[item_id] = url
                        else:
                            errores.append(f"{item_id}: sin URL")
                    else:
                        errores.append(f"{item_id}: HTTP {r.status_code} — {r.text[:120]}")
                except Exception as e:
                    errores.append(f"{item_id}: {str(e)}")
                time.sleep(0.2)
            bar.progress(1.0, text="Listo")
            if errores:
                with st.expander(f"⚠️ {len(errores)} ítems con error"):
                    for e in errores: st.text(e)
            if img_urls:
                with open(IMG_URLS_FILE, "w") as f: json.dump(img_urls, f)
                st.success(f"✅ {len(img_urls)} URLs obtenidas. Ahora descargá el ZIP.")
                st.rerun()
            else:
                st.error("❌ Error de permisos (access_denied). Tu app de MercadoLibre no tiene el scope `read_listings` habilitado.")
                st.warning("""**Para solucionarlo:**
1. Entrá a https://developers.mercadolibre.com.ar/devcenter
2. Abrí tu app → sección **Scopes/Permisos**
3. Habilitá **read_listings** y **write_listings** → Guardá
4. Volvé acá y hacé click en **Reconectar con ML** (botón del sidebar izquierdo)""")
        st.stop()

    with open(IMG_URLS_FILE) as f:
        img_urls = json.load(f)
    st.success(f"✅ {len(img_urls)} URLs listas. Descargá el ZIP:")

    urls_json = json.dumps(img_urls)
    js_component = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:8px 0;background:transparent;font-family:sans-serif">
<button id="btn" onclick="go()" style="background:#e53935;color:white;border:none;
  padding:11px 26px;font-size:15px;border-radius:8px;cursor:pointer;font-weight:700">
  📥 Descargar ZIP de fotos
</button>
<div id="log" style="margin-top:10px;font-size:13px;color:#ccc;min-height:18px"></div>
<div id="bw" style="display:none;margin-top:8px;background:#444;border-radius:5px;height:7px;width:98%">
  <div id="bar" style="background:#3483FA;height:7px;border-radius:5px;width:0%"></div>
</div>
<div id="link" style="margin-top:12px"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"
  integrity="sha512-XMVd28F1oH/O71fzwBnV7HucLxVwtxf26XV8P4wPk26EDxuGZ91N8bsOttmnomcCD3CS5ZMRL50H0GgOHvegtg=="
  crossorigin="anonymous"></script>
<script>
const URLS = {urls_json};
const L = t => document.getElementById('log').innerText = t;
const B = p => {{ document.getElementById('bw').style.display='block'; document.getElementById('bar').style.width=p+'%'; }};
async function go() {{
  const btn=document.getElementById('btn');
  btn.disabled=true; btn.innerText='⏳ Descargando...';
  const zip=new JSZip(); let ok=0, errs=[];
  const entries=Object.entries(URLS);
  for (let i=0;i<entries.length;i++) {{
    const [id,url]=entries[i];
    L((i+1)+'/'+entries.length+': '+id); B(Math.round(i/entries.length*90));
    try {{
      const r=await fetch(url);
      if (!r.ok) {{ errs.push(id+': '+r.status); continue; }}
      const b=await r.blob();
      if (b.size<500) {{ errs.push(id+': muy pequeña'); continue; }}
      zip.file(id+'.jpg',b); ok++;
    }} catch(e) {{ errs.push(id+': '+e.message); }}
  }}
  if (!ok) {{ L('❌ '+errs.join(' | ')); btn.disabled=false; btn.innerText='↺ Reintentar'; return; }}
  L('Generando ZIP...'); B(96);
  const blob=await zip.generateAsync({{type:'blob',compression:'DEFLATE'}});
  B(100); L('✅ '+ok+' fotos'+(errs.length?' ('+errs.length+' errores)':''));
  btn.innerText='✅ Listo';
  const u=URL.createObjectURL(blob);
  document.getElementById('link').innerHTML=
    '<a href="'+u+'" download="portadas_ml.zip" style="display:inline-block;background:#3483FA;'+
    'color:white;padding:10px 22px;border-radius:8px;font-weight:700;font-size:14px;text-decoration:none">'+
    '📥 Descargar portadas_ml.zip</a>'+
    (errs.length?'<div style="margin-top:6px;font-size:11px;color:#f88">Errores: '+errs.join(', ')+'</div>':'');
}}
</script></body></html>"""

    st.components.v1.html(js_component, height=150, scrolling=False)
    st.divider()
    st.caption("1️⃣ Botón rojo → descarga imágenes  |  2️⃣ Link azul → guardá el ZIP  |  3️⃣ Continuá")
    col1, col2 = st.columns([2,1])
    with col1:
        if st.button("✅ Ya descargué el ZIP — Continuar al Paso 3", type="primary"):
            with open("listo_paso2.txt","w") as f: f.write("ok")
            save_step(3); st.rerun()
    with col2:
        if st.button("↺ Reintentar desde cero"):
            if os.path.exists(IMG_URLS_FILE): os.remove(IMG_URLS_FILE)
            st.rerun()

# ══ PASO 3 ══
elif step == 3:
    st.subheader("Paso 3 — Subir fotos con fondo blanco")
    if st.button("← Volver al Paso 2 (descargar fotos de nuevo)"):
        save_step(2)
        st.rerun()
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
        ok, errores_detalle = 0, []

        with zipfile.ZipFile("procesadas.zip") as zf:
            for i, nombre in enumerate(nombres):

                item_id = nombre.split("_resultado")[0].split(".")[0]
                bar.progress((i+1)/len(nombres), text=f"Subiendo {i+1}/{len(nombres)}: {item_id}")

                try:

                    # 1. Obtener fotos actuales del ítem
                    r = requests.get(
                        f"https://api.mercadolibre.com/items/{item_id}",
                        headers=headers,
                        timeout=10
                    )

                    if r.status_code != 200:
                        errores_detalle.append(f"❌ {item_id}: GET item → {r.status_code} {r.text[:150]}")
                        continue

                    pictures = r.json().get("pictures", [])
                    fotos_restantes = [{"id": p["id"]} for p in pictures[1:]]

                    # 2. Preparar imagen optimizada para ML
                    img_data = zf.read(nombre)

                    img = Image.open(io.BytesIO(img_data)).convert("RGB")
                    ancho, alto = img.size

                    canvas_size = 1200

                    # Si la imagen es más grande la reducimos (nunca la agrandamos)
                    if max(ancho, alto) > canvas_size:
                        scale = canvas_size / max(ancho, alto)
                        nuevo_ancho = int(ancho * scale)
                        nuevo_alto = int(alto * scale)
                        img = img.resize((nuevo_ancho, nuevo_alto), Image.Resampling.LANCZOS)
                        ancho, alto = img.size

                    # Crear fondo blanco
                    canvas = Image.new("RGB", (canvas_size, canvas_size), (255, 255, 255))

                    # Centrar imagen
                    x = (canvas_size - ancho) // 2
                    y = (canvas_size - alto) // 2
                    canvas.paste(img, (x, y))

                    # Guardar con máxima calidad
                    buf = io.BytesIO()
                    canvas.save(
                        buf,
                        format="JPEG",
                        quality=97,
                        subsampling=0,
                        optimize=True
                    )

                    img_data_final = buf.getvalue()

                    # 3. Subir imagen a ML
                    upload = requests.post(
                        "https://api.mercadolibre.com/pictures/items/upload",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": (nombre, img_data_final, "image/jpeg")},
                        timeout=30
                    )

                    if upload.status_code not in (200, 201):
                        errores_detalle.append(f"❌ {item_id}: UPLOAD foto → {upload.status_code} {upload.text[:150]}")
                        continue

                    nueva_id = upload.json()["id"]

                    # 4. Actualizar publicación
                    update = requests.put(
                        f"https://api.mercadolibre.com/items/{item_id}",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"pictures": [{"id": nueva_id}] + fotos_restantes},
                        timeout=15
                    )

                    if update.status_code not in (200, 201):
                        errores_detalle.append(f"❌ {item_id}: PUT item → {update.status_code} {update.text[:150]}")
                        continue

                    ok += 1

                except Exception as e:
                    errores_detalle.append(f"❌ {item_id}: excepción → {str(e)}")

                time.sleep(0.5)

        bar.progress(1.0, text="Completado")

        if ok:
            st.success(f"✅ {ok} publicaciones actualizadas en MercadoLibre")

        if errores_detalle:
            st.warning(f"⚠️ {len(errores_detalle)} errores")
            with st.expander("Ver detalle de errores"):
                for e in errores_detalle:
                    st.text(e)

        if st.button("Volver al inicio", type="primary"):
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