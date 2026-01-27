# app.py
import re
from datetime import date, datetime
from io import BytesIO
from ftplib import FTP

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Steekkaart: zoek op personeelsnummer", layout="wide")


def extract_yyyymmdd(name: str):
    """Bestandsnaam start met yyyymmdd (bv. 20260127 - Basis Steekkaart ....xlsx)."""
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


def normalize_personeelsnummer(x) -> str:
    """Maak personeelsnummer vergelijkbaar (string, trim, geen .0)."""
    if pd.isna(x):
        return ""
    s = str(x).strip()
    # Excel-nummers komen soms als 12345.0 binnen
    if s.endswith(".0"):
        s = s[:-2]
    return s


@st.cache_data(ttl=300)
def load_dienstlijst_via_ftp() -> tuple[str, date | None, pd.DataFrame]:
    """
    - Logt in via FTP (map na login is correct)
    - Kiest excel van vandaag (of meest recente)
    - Leest tabblad 'dienstlijst'
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

        files = ftp.nlst()
        chosen = choose_file(files, today)
        if not chosen:
            raise RuntimeError(
                "Geen Excel-bestanden gevonden die starten met yyyymmdd (bv. 20260127...)."
            )

        bio = BytesIO()
        ftp.retrbinary(f"RETR {chosen}", bio.write)
        bio.seek(0)

        # Lees alleen tabblad 'dienstlijst'
        df = pd.read_excel(bio, sheet_name="dienstlijst")

        file_date = extract_yyyymmdd(chosen)
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
    st.title("Steekkaart: zoek op personeelsnummer")

    # Data laden
    try:
        filename, file_date, df = load_dienstlijst_via_ftp()
    except Exception as e:
        st.error(f"FTP/Excel inlezen mislukt: {e}")
        st.stop()

    # Metrics gecentreerd (foto 2)
    _, c1, c2, c3, _ = st.columns([1, 2, 2, 2, 1])
    c1.metric("Gekozen bestand", filename)
    c2.metric("Bestandsdatum", file_date.isoformat() if file_date else "—")
    c3.metric("Vandaag", date.today().isoformat())

    st.divider()

    # Zoekveld
    zoek = st.text_input("Zoek op personeelsnummer", placeholder="bv. 12345")

    # Kolommen (case-insensitive)
    required_cols = [
        "personeelsnummer",
        "Dienstadres",
        "uur",
        "plaats",
        "richting",
        "Loop",
        "naam",
        "voertuig",
        "wissel",
    ]
    col_map = {c.lower(): c for c in df.columns}
    missing = [c for c in required_cols if c.lower() not in col_map]
    if missing:
        st.error("Kolommen ontbreken in tabblad 'dienstlijst': " + ", ".join(missing))
        st.write("Gevonden kolommen:", list(df.columns))
        st.stop()

    # Maak view dataframe met gewenste kolommen + rename wissel -> voertuigwissel
    df_view = df[[col_map[c.lower()] for c in required_cols]].copy()
    df_view = df_view.rename(columns={col_map["wissel"]: "voertuigwissel"})

    # Normaliseer personeelsnummer voor matching
    pn_col = col_map["personeelsnummer"]
    df_view["_pn_norm"] = df_view[pn_col].apply(normalize_personeelsnummer)

    if not zoek.strip():
        st.info("Geef een personeelsnummer in om resultaten te zien.")
        return

    zoek_norm = normalize_personeelsnummer(zoek)

    # Exact match op personeelsnummer
    result = df_view[df_view["_pn_norm"] == zoek_norm].drop(columns=["_pn_norm"])

    if result.empty:
        st.warning("Geen resultaten gevonden voor dit personeelsnummer.")
        return

    st.subheader("Resultaat")
    st.dataframe(result, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
