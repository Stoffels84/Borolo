import streamlit as st
from phue import Bridge

BRIDGE_IP = st.secrets.get("BRIDGE_IP", "")
HUE_USERNAME = st.secrets.get("HUE_USERNAME", "")

st.title("Philips Hue • Simpele Besturing")

if not BRIDGE_IP:
    st.error("BRIDGE_IP ontbreekt in Secrets. Voeg die toe in Streamlit Cloud → Settings → Secrets.")
    st.stop()

@st.cache_resource(show_spinner=False)
def get_bridge(ip, username):
    b = Bridge(ip, username=username or None)
    try:
        b.connect()  # eerste keer: druk op de Bridge-knop
    except Exception as e:
        # Als er (nog) geen username is, toont dit een duidelijke hint
        raise RuntimeError(
            "Kan niet verbinden. Druk binnen 30s op de ronde knop op je Hue Bridge "
            "en klik hierboven op 'Rerun'. Als de verbinding lukt, kopieer dan de "
            "gegenereerde username naar je Secrets (HUE_USERNAME)."
        ) from e
    return b

try:
    bridge = get_bridge(BRIDGE_IP, HUE_USERNAME)
except RuntimeError as e:
    st.warning(str(e))
    st.stop()

# Als er nog geen username in secrets stond maar phue er net eentje heeft aangemaakt:
if not HUE_USERNAME and getattr(bridge, 'username', None):
    st.info(
        "✅ Verbonden! Sla deze Hue-username op in je Secrets voor volgende keren:\n\n"
        f"`{bridge.username}`"
    )

# UI
lights = bridge.lights
if not lights:
    st.warning("Geen lampen gevonden op deze Bridge.")
else:
    names = {f"{l.name} (id {l.light_id})": l.light_id for l in lights}
    choice = st.selectbox("Kies lamp", list(names.keys()))
    lid = names[choice]

    col1, col2 = st.columns(2)
    if col1.button("Aan"):
        bridge.set_light(lid, "on", True)
        st.success("Lamp aangezet.")
    if col2.button("Uit"):
        bridge.set_light(lid, "on", False)
        st.success("Lamp uitgezet.")

    bri = st.slider("Helderheid", 0, 254, 180)
    if st.button("Zet helderheid"):
        bridge.set_light(lid, "bri", int(bri))
        st.success(f"Helderheid = {bri}")
