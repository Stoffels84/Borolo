import pandas as pd
import requests
import streamlit as st

from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
from requests.auth import HTTPBasicAuth

st.set_page_config(page_title="Steekkaart", page_icon="🚌", layout="centered")

# ---------------- Secrets ----------------
try:
    BASE_URL = st.secrets["DATA_BASE_URL"].rstrip("/") + "/"
    AUTH = HTTPBasicAuth(st.secrets["HOST_USER"], st.secrets["HOST_PASS"])
except Exception:
    st.error(
        "Secrets ontbreken of heten anders. Verwacht:\n"
        'HOST_USER = "Christoff"  \n'
        'HOST_PASS = "29076"  \n'
        'DATA_BASE_URL = "https://otgent.borolo.be/data/"'
    )
    st.stop()


def brussels_yyyymmdd() -> str:
    return datetime.now(ZoneInfo("Europe/Brussels")).strftime("%Y%m%d")


def http_get(url: str, timeout: int = 30) -> requests.Response:
    return requests.get(url, auth=AUTH, timeout=timeout)


@st.cache_data(ttl=60)
def read_latest_txt() -> tuple[str | None, dict]:
    """
    Leest BASE_URL/latest.txt.
    Inhoud: 1 regel met de volledige bestandsnaam (bv. '20260126 steekkaart v3.xlsx')
    """
    latest_url = BASE_URL + "latest.txt"
    dbg = {"latest_url": latest_url}

    try:
        r = http_get(latest_url, timeout=15)
        dbg["status_code"] = r.status_code
        if r.status_code != 200:
            return None, dbg

        txt = (r.text or "").strip()
        line = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
        if not line:
            dbg["error"] = "latest.txt is leeg"
            return None, dbg

        # als er per ongeluk een volledige URL in staat, pak enkel de bestandsnaam
        filename = line.split("/")[-1]
        dbg["filename"] = filename
        return filename, dbg

    except Exception as e:
        dbg["exception"] = str(e)
        return None, dbg


@st.cache_data(ttl=300)
def fetch_excel(filename: str) -> pd.DataFrame:
    """
    Haalt excel op met Basic Auth.
    URL-encode filename (voor spaties/speciale tekens).
    """
    encoded = quote(filename)
    url = BASE_URL + encoded

    r = http_get(url, timeout=30)
    if r.status_code == 404:
        raise FileNotFoundError(f"Bestand niet gevonden: {filename}")
    r.raise_for_status()

    return pd.read_excel(BytesIO(r.content))


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
st.info(f"Vandaag: **{today}**")

with st.spinner("Bestand bepalen…"):
    latest_fn, latest_dbg = read_latest_txt()

chosen = None
method = None

if latest_fn:
    chosen = latest_fn
    method = "latest.txt"
else:
    st.warning(
        "Ik kan de bestandsnaam niet automatisch vinden omdat de tekst na de datum variabel is "
        "en directory listing uit staat.\n\n"
        "✅ Oplossing: zet `latest.txt` in dezelfde map met de bestandsnaam van vandaag.\n"
        "➡️ Tijdelijk kan je hieronder manueel de bestandsnaam invullen."
    )
    chosen = st.text_input("Bestandsnaam (.xlsx)", placeholder="bv. 20260126 steekkaart v3.xlsx").strip()
    method = "manueel" if chosen else None

with st.expander("🔎 Diagnostiek"):
    st.write("BASE_URL:", BASE_URL)
    st.write("latest.txt probe:", latest_dbg)

if not chosen:
    st.stop()

st.success(f"Gekozen bestand ({method}): **{chosen}**")

with st.spinner("Excel inlezen…"):
    try:
        df = fetch_excel(chosen)
    except Exception as e:
        st.error(f"Kon Excel niet ophalen/inlezen: {e}")
        st.stop()

# Auto-detect kolommen (pas aan indien nodig)
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
        st.warning("Geen record gevonden voor dit personeelsnummer in dit bestand.")
    else:
        row = match.iloc[0]
        dienst_val = row[col_dienst] if col_dienst else "(kolom 'dienst' niet gevonden)"
        voertuig_val = row[col_voertuig] if col_voertuig else "(kolom 'voertuig' niet gevonden)"

        st.subheader("Resultaat")
        st.metric("Dienst", str(dienst_val))
        st.metric("Voertuig", str(voertuig_val))

        with st.expander("Bekijk volledige rij"):
            st.dataframe(match, use_container_width=True)
