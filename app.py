import streamlit as st
import streamlit.components.v1 as components
from urllib.parse import urlencode

NEW_BASE_URL = "https://opzoeken-voertuig.vercel.app/"

# Optioneel: kleine melding (wordt meestal maar héél kort zichtbaar)
st.set_page_config(page_title="Doorsturen…", layout="centered")
st.write("Je wordt doorgestuurd naar de nieuwe website…")

# Neem bestaande query parameters mee (bv. ?id=123)
params = dict(st.query_params)  # Streamlit >= 1.30
qs = urlencode(params, doseq=True)

target_url = f"{NEW_BASE_URL}?{qs}" if qs else NEW_BASE_URL

# Client-side redirect
components.html(
    f"""
    <script>
      window.location.replace("{target_url}");
    </script>
    <noscript>
      <meta http-equiv="refresh" content="0; url={target_url}">
    </noscript>
    """,
    height=0,
)

# Stop verdere rendering
st.stop()
