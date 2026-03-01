import streamlit as st
from urllib.parse import urlencode

TARGET_BASE = "https://opzoeken-voertuig.vercel.app/"

st.set_page_config(page_title="Doorsturen…", layout="centered")

# Neem query params mee (werkt ook op oudere Streamlit-versies)
try:
    params = st.query_params  # nieuw
except Exception:
    params = st.experimental_get_query_params()  # oud

# params kan dict zijn met lists -> urlencode met doseq
qs = urlencode(params, doseq=True) if params else ""
target_url = f"{TARGET_BASE}?{qs}" if qs else TARGET_BASE

# Toon iets voor de gebruiker + fallback knop
st.write("Je wordt doorgestuurd naar de nieuwe website…")
st.link_button("Klik hier als het niet automatisch werkt", target_url)

# Redirect in de TOP pagina (niet in een iframe)
st.markdown(
    f"""
    <meta http-equiv="refresh" content="0; url={target_url}">
    <script>
      // Probeer top-level redirect
      window.top.location.href = "{target_url}";
    </script>
    """,
    unsafe_allow_html=True,
)

st.stop()
