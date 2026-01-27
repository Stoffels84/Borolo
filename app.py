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
            "voertuig": "voertuig",
            "wissel": "voertuigwissel",
        }

        # Map echte kolomnamen in Excel naar onze output
        col_map: dict[str, str] = {}
        missing: list[str] = []
        for excel_name, out_name in wanted_cols.items():
            found = _find_col(df_raw, excel_name)
            if not found:
                missing.append(excel_name)
            else:
                col_map[found] = out_name

        if missing:
            st.error(
                "In tabblad 'Dienstlijst' ontbreken deze vereiste kolommen: "
                + ", ".join(missing)
            )
            st.stop()

        df = df_raw[list(col_map.keys())].rename(columns=col_map)

        # Zorg dat personeelnummer en voertuig altijd als tekst behandeld worden
        df["personeelnummer"] = df["personeelnummer"].astype(str)
        df["voertuig"] = df["voertuig"].astype(str)

        # Keuze: zoeken op personeelnummer of voertuig
        search_mode = st.radio("Zoeken op", ["Personeelnummer", "Voertuig"], horizontal=True)

        if search_mode == "Personeelnummer":
            q = st.text_input("Personeelnummer", placeholder="bv. 12345")
        else:
            q = st.text_input("Voertuig", placeholder="bv. 6201 (of deel van de code)")

        if not q.strip():
            st.info("Geef een zoekwaarde in om resultaten te tonen.")
            st.stop()

        q_norm = q.strip()

        if search_mode == "Personeelnummer":
            pn_series = (
                df["personeelnummer"]
                .astype(str)
                .str.replace("\u00a0", " ", regex=False)  # NBSP -> spatie
                .str.strip()
                .str.replace(r"\.0$", "", regex=True)     # 12345.0 -> 12345
            )
            results = df[pn_series == q_norm].copy()
            download_suffix = f"personeelnummer_{q_norm}"
        else:
            veh_series = (
                df["voertuig"]
                .astype(str)
                .str.replace("\u00a0", " ", regex=False)
                .str.strip()
            )
            # Zoeken op voertuig: case-insensitive "bevat" (handig als je maar een deel kent)
            results = df[veh_series.str.contains(q_norm, case=False, na=False)].copy()
            download_suffix = f"voertuig_{q_norm}"

        if results.empty:
            st.warning(f"Geen resultaten gevonden voor {search_mode.lower()}: {q_norm}")
            st.stop()

        st.success(f"Gevonden: {len(results)} rij(en) voor {search_mode.lower()} {q_norm}")
        st.dataframe(results, use_container_width=True, hide_index=True)

        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            results.to_excel(writer, index=False, sheet_name="Dienstlijst_resultaat")
        out.seek(0)

        safe_name = filename.rsplit(".", 1)[0]
        st.download_button(
            "Download resultaat als Excel",
            data=out,
            file_name=f"{safe_name}_{download_suffix}.xlsx",
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
