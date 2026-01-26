import re
from io import BytesIO
from datetime import datetime, date

import pandas as pd
import requests
import streamlit as st
from requests.auth import HTTPBasicAuth

st.set_page_config(page_title="Steekkaart", page_icon="🚌", layout="centered")

BASE_URL = st.secrets["steekkaart"]["base_url"].rstrip("/") + "/"
AUTH = HTTPBasicAuth(
    st.secrets["steekkaart"]["username"],
    st.secrets["steekkaart"]["password"],
)

DATE_PREFIX_RE = re.compile(r"(\d{8})")  # jjjjmmdd ergens in bestandsnaam


def brussels_today() -> date:
    # Streamlit draait niet altijd in BE timezone; we nemen "vandaag" op basis van datum-only
    # (als je écht timezone-nauwkeurig wil: pytz/zoneinfo toevoegen)
    return datetime.utcnow().date()  # meestal ok voor bestandskeuze per dag


@st.cache_data(ttl=300)
def list_xlsx_files() -> list[str]:
    """
    Probeert directory listing (HTML) op te halen via Basic Auth en haalt .xlsx links eruit.
    Werkt als de server directory-indexing toont voor geauthenticeerde users.
    """
    r = requests.get(BASE_URL, auth=AUTH, timeout=20)
    r.raise_for_status()

    html = r.text
    # Pak alle href="...xlsx"
    links = re.findall(r'href="([^"]+\.xlsx)"', html, flags=re.IGNORECASE)
    # Normaliseer (sommige servers geven volledige padjes)
    files = [link.split("/")[-1] for link in links]
    # uniek + sort
    return sorted(set(files))


def pick_file_for_today(files: list[str]) -> str | None:
    """
    Kiest het bestand met datumprefix jjjjmmdd dat het meest recent is <= vandaag.
    """
    today = brussels_today()

    candidates = []
    for fn in files:
        m = DATE_PREFIX_RE.search(fn)
        if not m:
            continue
        yyyymmdd = m.group(1)
        try:
            d = datetime.strptime(yyyymmdd, "%Y%m%d").date()
        except ValueError:
            continue
        if d <= today:
            candidates.append((d, fn))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


@st.cache_data(ttl=300)
def fetch_excel_as_df(filename: str) -> pd.DataFrame:
    url = BASE_URL + filename
    r = requests.get(url, auth=AUTH, timeout=30)
    r.raise_for_status()
    bio = BytesIO(r.content)
    df = pd.read_excel(bio)
    return df


def guess_column(df: pd.DataFrame, keywords: list[str]) -> str | None:
    cols = [c for c in df.columns if isinstance(c, str)]
    low = {c: c.lower() for c in cols}
    for c, lc in low.items():
        if any(k in lc for k in keywords):
            return c
    return None


st.title("🚌 Steekkaart")
st.caption("Vul je personeelsnummer in en bekijk je dienst en voertuig (zonder inloggen).")

with st.spinner("Bestanden ophalen…"):
    try:
        files = list_xlsx_files()
    except Exception as e:
        st.error(
            "Ik kan de map niet uitlezen (directory listing). "
            "Als je hosting geen bestandslijst toont, is de oplossing: "
            "maak een vast bestand zoals `latest.txt` dat de juiste bestandsnaam bevat."
        )
        st.stop()

chosen = pick_file_for_today(files)
if not chosen:
    st.error("Geen geschikt .xlsx-bestand gevonden met een jjjjmmdd prefix (<= vandaag).")
    st.stop()

st.success(f"Gekozen bestand: **{chosen}**")

with st.spinner("Excel inlezen…"):
    try:
        df = fetch_excel_as_df(chosen)
    except Exception as e:
        st.error(f"Kon Excel niet inlezen: {e}")
        st.stop()

# Auto-detect kolommen (pas keywords aan aan jouw echte headers)
col_pers = guess_column(df, ["pers", "personeel", "persnr", "personeelsnr", "person"])
col_dienst = guess_column(df, ["dienst", "shift", "ronde", "tour", "dienstcode"])
col_voertuig = guess_column(df, ["voertuig", "bus", "tram", "vehicle", "wagen"])

with st.expander("⚙️ Kolommen (auto-detect)"):
    st.write("Personeelsnummer:", col_pers)
    st.write("Dienst:", col_dienst)
    st.write("Voertuig:", col_voertuig)
    st.caption("Als auto-detect fout zit: zeg me even je exacte kolomnamen, dan zet ik ze vast.")

if not col_pers:
    st.error("Ik vind geen kolom voor personeelsnummer. Geef me je exacte kolomnaam.")
    st.stop()

persnr = st.text_input("Personeelsnummer", placeholder="bv. 12345").strip()

if persnr:
    # Zorg dat we zowel numeriek als tekst matchen
    s = df[col_pers].astype(str).str.strip()
    match = df[s == persnr]

    if match.empty:
        st.warning("Geen record gevonden voor dit personeelsnummer in het gekozen dagbestand.")
    else:
        row = match.iloc[0]

        dienst_val = row[col_dienst] if col_dienst else "(kolom 'dienst' niet gevonden)"
        voertuig_val = row[col_voertuig] if col_voertuig else "(kolom 'voertuig' niet gevonden)"

        st.subheader("Resultaat")
        st.metric("Dienst", str(dienst_val))
        st.metric("Voertuig", str(voertuig_val))

        with st.expander("Bekijk volledige rij"):
            st.dataframe(match)
