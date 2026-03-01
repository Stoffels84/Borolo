import streamlit as st
import streamlit.components.v1 as components

NEW_URL = "https://opzoeken-voertuig.vercel.app/"

# Optioneel: toon heel kort iets (kan ook weg)
st.write("Je wordt doorgestuurd…")

components.html(
    f"""
    <script>
      window.location.replace("https://opzoeken-voertuig.vercel.app/");
    </script>
    <noscript>
      <meta http-equiv="refresh" content="0; url={NEW_URL}">
    </noscript>
    """,
    height=0,
)
st.stop()
