# app.py
import re
from datetime import date, datetime
from io import BytesIO
from ftplib import FTP

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Opzoeken voertuig chauffeur", layout="wide")


def extract_yyyymmdd(name: str):
    """Verwacht dat de bestandsnaam start met yyyymmdd, bv: 20260127_iets.xlsx"""
    m = re.match(r"^(\d{8})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def choose_file(files: list[str], today: date) -> str | None:
    """
    Kiest:
    1) bestand van vandaag (als er meerdere: alfabetisch laatste)
    2) anders: meest recente op basis van datum vooraan
    """
    candidates: list[tuple[str, date]] = []
    for f in files:
        if not f.lower().endswith((".xlsx", ".xlsm", ".xls")):
            continue
        d = extract_yyyymmdd(f)
        if d is None:
            continue
        candidates.append((f, d))

    if not candidates:
        return None

    today_matches = [f for f, d in candidates if d == today]
    if today_matches:
        return sorted(today_matches)[-1]

    return max(candidates, key=lambda x: x[1])[0]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s)).strip().lower()


def _find_col(df: pd.DataFrame, wanted: str) -> str | None:
    """Zoekt kolom op basis van 'genormaliseerde' naam (spaties/case negeren)."""
    w = _norm(wanted)
    for c in df.columns:
        if _norm(c) == w:
            return c
    return None


def clean_id_series(s: pd.Series) -> pd.Series:
    """
    Maakt van IDs (personeelnummer/voertuig/voertuigwissel) altijd 'proper' tekst:
    - non-breaking spaces weg
    - strip
    - trailing .0 verwijderen (typisch door Excel float)
    """
    return (
        s.astype(str)
        .str.replace("\u00a0", " ", regex=False)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )


def clean_query(q: str) -> str:
    q = str(q).replace("\u00a0", " ").strip()
    q = re.sub(r"\.0$", "", q)  # als iemand "6310.0" plakt
    return q


@st.cache_data(ttl=300)
def load_excel_via_ftp() -> tuple[str, date | None, pd.DataFrame]:
    """
    Leest via FTP:
      - list bestanden in huidige map na login
      - kiest vandaag of meest recente
      - downloadt naar geheugen
      - leest Excel tabblad 'Dienstlijst'
    Vereiste secrets:
      FTP_HOST, FTP_USER, FTP_PASS
    Optioneel:
      FTP_PORT (default 21)
    """
    host = st.secrets["FTP_HOST"]
    port = int(st.secrets.get("FTP_PORT", 21))
    user = st.secrets["FTP_USER"]
    pw = st.secrets["FTP_PASS"]

    today = date.today()

    ftp = FTP()
    try:
        ftp.connect(host=host, port=port, timeout=30)
        ftp.login(user=user, passwd=pw)

        # Indien je in een submap moet zijn:
        # ftp.cwd("data")

        files = ftp.nlst()
        chosen = choose_file(files, today)
        if not chosen:
            raise RuntimeError(
                "Geen Excel-bestanden gevonden die starten met yyyymmdd (bv. 20260127_...)."
            )

        bio = BytesIO()
        ftp.retrbinary(f"RETR {chosen}", bio.write)
        bio.seek(0)

        file_date = extract_yyyymmdd(chosen)

        try:
            df = pd.read_excel(bio, sheet_name="Dienstlijst")
        except ValueError:
            raise RuntimeError("Tabblad 'Dienstlijst' niet gevonden in het Excel-bestand.")

        return chosen, file_date, df

    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


def main():
    st.title("Opzoeken voertuig chauffeur")

    with st.sidebar:
        st.header("Instellingen")
        refresh = st.button("🔄 Herladen (cache leegmaken)")
        st.caption("Bestand wordt automatisch gekozen op basis van datum (yyyymmdd...).")

    if refresh:
        st.cache_data.clear()

    try:
        filename, file_date, df_raw = load_excel_via_ftp()

        # Metrics: enkel Bestandsdatum + Vandaag, gecentreerd
        m1, c2, c3, m4 = st.columns([1, 2, 2, 1])
        with c2:
            st.metric("Bestandsdatum", file_date.isoformat() if file_date else "—")
        with c3:
            st.metric("Vandaag", date.today().isoformat())

        st.divider()

        wanted_cols = {
            "personeelnummer": "personeelnummer",
            "dienstadres": "Dienstadres",
            "uur": "uur",
            "plaats": "plaats",
            "richting": "richting",
            "loop": "Loop",
            "naam": "naam",
