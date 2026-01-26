import re
from io import BytesIO
from datetime import datetime, date
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from requests.auth import HTTPBasicAuth

st.set_page_config(page_title="Steekkaart", page_icon="🚌", layout="centered")

# ---------------- Secrets (zoals in jouw screenshot) ----------------
try:
    BASE_URL = st.secrets["DATA_BASE_URL"].rstrip("/") + "/"
    AUTH = HTTPBasicAuth(st.secrets["HOST_USER"], st.secrets["HOST_PASS"])
except Exception:
    st.error(
        "Secrets ontbreken of heten anders. Verwacht in Streamlit Secrets:\n"
        'HOST_USER = "Christoff"  \n'
        'HOST_PASS = "29076"  \n'
        'DATA_BASE_URL = "https://otgent.borolo.be/data/"'
    )
    st.stop()

# Herkent 8 cijfers ergens in bestandsnaam: jjjjmmdd
DATE_PREFIX_RE = re.compile(r"(\d{8})")


def brussels_today() -> date:
    """Pak 'vandaag' in Europe/Brussels."""
    return datetime.now(ZoneInfo("Europe/Brussels")).date()


@st.cache_data(ttl=300)
def list_xlsx_files() -> list[str]:
    """
    Haalt de HTML directory listing op en extraheert .xlsx links.
    Dit werkt enkel als de server de mapinhoud toont.
    """
    r = requests.get(BASE_URL, auth=AUTH, timeout=20)
    r.raise_for_status()

    html = r.text
    links = re.findall(r'href="([^"]+\.xlsx)"', html, flags=re.IGNORECASE)

    # normaliseer naar enkel bestandsnaam
    files = [link.split("/")[-1] for link in links]
    return sorted(set(files))


def pick_file_for_today(files: list[str]) -> str | None:
    """Kiest het meest recente bestand met datum (jjjjmmdd) <= vandaag."""
    today = brussels_today()

    candidates: list[tuple[date, str]] = []
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

with st.spinner("Bestanden ophalen…"):
    try:
        files = list_xlsx_files()
    except Exception:
        st.error(
            "Ik kan de map niet uitlezen.\n\n"
            "Mogelijke oorzaken:\n"
            "- Directory listing staat uit op de server\n"
            "- Basic Auth is fout (HOST_USER/HOST_PASS)\n"
            "- DATA_BASE_URL klopt niet\n\n"
            "Robuuste oplossing: zet een `latest.txt` in dezelfde map met de bestandsnaam."
        )
        st.stop()

if not files:
    st.error("Geen .xlsx-bestanden gevonden in de map.")
    st.stop()

chosen = pick_file_for_today(files)
if not chosen:
    st.error("Geen geschikt .xlsx-bestand gevonden met datum (jjjjmmdd) in de naam (<= vandaag).")
    st.stop()

st.success(f"Gekozen bestand: **{chosen}**")

with st.spinner("Excel inlezen…"):
    try:
        df = fetch_excel_as_df(chosen)
    except Exception as e:
        st.error(f"Kon Excel niet inlezen: {e}")
        st.stop()

# Auto-detect kolommen (pas keywords aan als jouw headers anders zijn)
col_pers = guess_column(df, ["pers", "personeel", "persnr", "personeelsnr", "person"])
col_dienst = guess_column(df, ["dienst", "shift", "ronde", "tour", "dienstcode"])
col_voertuig = guess_column(df, ["voertuig", "bus", "tram", "vehicle", "wagen"])

with st.expander("⚙️ Kolommen (auto-detect)"):
    st.write("Personeelsnummer:", col_pers)
    st.write("Dienst:", col_dienst)
    st.write("Voertuig:", col_voertuig)
    st.caption("Als dit fout zit: geef me je exacte kolomnamen, dan zet ik ze vast.")

if not col_pers:
    st.error("Ik vind geen kolom voor personeelsnummer. Geef me je exacte kolomnaam (header in Excel).")
    st.stop()

persnr = st.text_input("Personeelsnummer", placeholder="bv. 12345").strip()

if persnr:
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
            st.dataframe(match, use_container_width=True)
