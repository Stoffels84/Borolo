# app.py
import re
from datetime import date, datetime
from io import BytesIO
from ftplib import FTP

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Steekkaart: bestand van vandaag", layout="wide")


def extract_yyyymmdd(name: str):
    """
    Verwacht dat de bestandsnaam start met yyyymmdd, bv:
    20260127_iets.xlsx
    """
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


@st.cache_data(ttl=300)
def load_excel_via_ftp() -> tuple[str, pd.DataFrame]:
    """
    Leest via FTP:
      - list bestanden in huidige map na login
      - kiest vandaag of meest recente
      - downloadt naar geheugen
      - leest Excel met pandas
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

        # Als je tóch een submap wil gebruiken, zet dan bv:
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

        df = pd.read_excel(bio)  # openpyxl is vereist voor xlsx/xlsm
        return chosen, df

    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


def main():
    st.title("Steekkaart: bestand van vandaag")

    with st.sidebar:
        st.header("Instellingen")
        st.caption("Deze app kiest automatisch het Excel-bestand van vandaag (yyyymmdd...).")
        refresh = st.button("🔄 Herladen (cache leegmaken)")

    if refresh:
        st.cache_data.clear()

    try:
        filename, df = load_excel_via_ftp()
        file_date = extract_yyyymmdd(filename)

        c1, c2, c3 = st.columns(3)
        c1.metric("Gekozen bestand", filename)
        c2.metric("Bestandsdatum", file_date.isoformat() if file_date else "—")
        c3.metric("Vandaag", date.today().isoformat())

        st.dataframe(df, use_container_width=True)

        # Optioneel: download knop
        out = BytesIO()
        df.to_excel(out, index=False)
        out.seek(0)
        st.download_button(
            "Download als Excel",
            data=out,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.error(f"FTP inlezen mislukt: {e}")
        st.info(
            "Check of je in de juiste FTP-map zit na login. "
            "Indien nodig: zet `ftp.cwd('mapnaam')` aan in de code."
        )


if __name__ == "__main__":
    main()
