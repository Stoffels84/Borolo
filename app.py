from io import BytesIO
from datetime import datetime, date
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from requests.auth import HTTPBasicAuth

st.set_page_config(page_title="Steekkaart", page_icon="🚌", layout="centered")

# ---------------- Secrets ----------------
try:
    BASE_URL = st.secrets["DATA_BASE_URL"].rstrip("/") + "/"
    AUTH = HTTPBasicAuth(st.secrets["HOST_USER"], st.secrets["HOST_PASS"])
    FILE_SUFFIX = st.secrets.get("FILE_SUFFIX", "").strip()
except Exception:
    st.error(
        "Secrets ontbreken of heten anders. Verwacht:\n"
        'HOST_USER = "..."  \n'
        'HOST_PASS = "..."  \n'
        'DATA_BASE_URL = "https://otgent.borolo.be/data/"\n'
        'Optioneel: FILE_SUFFIX = "_steekkaart.xlsx"'
    )
    st.stop()

if not FILE_SUFFIX:
    st.error(
        "FILE_SUFFIX ontbreekt.\n\n"
        "Voeg in Secrets toe:\n"
        'FILE_SUFFIX = "_steekkaart.xlsx"\n\n'
        "Voorbeeld bestandsnaam: 20260126_steekkaart.xlsx"
    )
    st.stop()


def brussels_yyyymmdd() -> str:
    return datetime.now(ZoneInfo("Europe/Brussels")).strftime("%Y%m%d")


@st.cache_data(ttl=60)
def fetch_excel_for_today() -> tuple[str, pd.DataFrame]:
    """
    Verwacht bestandsnaam: YYYYMMDD + FILE_SUFFIX
    vb: 20260126 + _steekkaart.xlsx => 20260126_steekkaart.xlsx
    """
    d = brussels_yyyymmdd()
    filename = f"{d}{FILE_SUFFIX}"
    url = BASE_URL + filename

    r = requests.get(url, auth=AUTH, timeout=30)
    if r.status_code == 404:
        raise FileNotFoundError(f"Bestand niet gevonden: {filename}")
    r.raise_for_status()

    df = pd.read_excel(BytesIO(r.content))
    return filename, df


def guess_column(df: pd.DataFrame, keywords: list[str]) -> str | None:
    cols = [c for c in df.columns if isinstance(c, str)]
    low = {c: c.lower() for c in cols}
    for c, lc in low.items():
        if any(k in lc for k in keywords):
            return c
    return None


# ---------------- UI ----------------
st.title("🚌 Steekkaart")
st.caption("Vul je personeelsnummer in en bekijk je dienst en voertuig.")

today = brussels_yyyymmdd()
st.info(f"Vandaag: **{today}** → verwacht bestand: **{today}{FILE_SUFFIX}**")

with st.spinner("Excel van vandaag ophalen…"):
    try:
        chosen, df = fetch_excel_for_today()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        st.error(f"Kon Excel niet ophalen/inlezen: {e}")
        st.stop()

st.success(f"Gekozen bestand: **{chosen}**")

# Auto-detect kolommen
col_pers = guess_column(df, ["pers", "personeel", "persnr", "personeelsnr", "person"])
col_dienst = guess_column(df, ["dienst", "shift", "ronde", "tour", "dienstcode"])
col_voertuig = guess_column(df, ["voertuig", "bus", "tram", "vehicle", "wagen"])

with st.expander("⚙️ Kolommen (auto-detect)"):
    st.write("Personeelsnummer:", col_pers)
    st.write("Dienst:", col_dienst)
    st.write("Voertuig:", col_voertuig)

if not col_pers:
    st.error("Ik vind geen kolom voor personeelsnummer. Geef me je exacte kolomnaam (header in Excel).")
    st.stop()

persnr = st.text_input("Personeelsnummer", placeholder="bv. 12345").strip()

if persnr:
    s = df[col_pers].astype(str).str.strip()
    match = df[s == persnr]

    if match.empty:
        st.warning("Geen record gevonden voor dit personeelsnummer in het dagbestand.")
    else:
        row = match.iloc[0]
        dienst_val = row[col_dienst] if col_dienst else "(kolom 'dienst' niet gevonden)"
        voertuig_val = row[col_voertuig] if col_voertuig else "(kolom 'voertuig' niet gevonden)"

        st.subheader("Resultaat")
        st.metric("Dienst", str(dienst_val))
        st.metric("Voertuig", str(voertuig_val))

        with st.expander("Bekijk volledige rij"):
            st.dataframe(match, use_container_width=True)
