# app.py
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from ftplib import FTP

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Opzoeken voertuig chauffeur", layout="wide")


# ---------------------------
# Helpers
# ---------------------------
def extract_yyyymmdd(name: str):
    """Verwacht dat de bestandsnaam start met yyyymmdd, bv: 20260127_iets.xlsx"""
    m = re.match(r"^(\d{8})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


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
    Maakt van IDs altijd 'proper' tekst:
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
    q = re.sub(r"\.0$", "", q)
    return q


def choose_file_for_date(files: list[str], target: date) -> str | None:
    """
    Kiest het bestand dat exact matcht met target (yyyymmdd...).
    Als er meerdere zijn voor dezelfde datum: alfabetisch laatste.
    """
    candidates = []
    for f in files:
        if not f.lower().endswith((".xlsx", ".xlsm", ".xls")):
            continue
        d = extract_yyyymmdd(f)
        if d == target:
            candidates.append(f)

    if not candidates:
        return None
    return sorted(candidates)[-1]


def _load_one_excel_from_ftp(ftp: FTP, filename: str) -> pd.DataFrame:
    bio = BytesIO()
    ftp.retrbinary(f"RETR {filename}", bio.write)
    bio.seek(0)
    try:
        return pd.read_excel(bio, sheet_name="Dienstlijst")
    except ValueError:
        raise RuntimeError(f"Tabblad 'Dienstlijst' niet gevonden in: {filename}")


def _prepare_df(df_raw: pd.DataFrame) -> pd.DataFrame:
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

    col_map: dict[str, str] = {}
    missing: list[str] = []
    for excel_name, out_name in wanted_cols.items():
        found = _find_col(df_raw, excel_name)
        if not found:
            missing.append(excel_name)
        else:
            col_map[found] = out_name

    if missing:
        raise RuntimeError(
            "In tabblad 'Dienstlijst' ontbreken deze vereiste kolommen: "
            + ", ".join(missing)
        )

    df = df_raw[list(col_map.keys())].rename(columns=col_map)

    # IDs proper maken
    df["personeelnummer"] = clean_id_series(df["personeelnummer"])
    df["voertuig"] = clean_id_series(df["voertuig"])
    df["voertuigwissel"] = clean_id_series(df["voertuigwissel"])

    return df


# ---------------------------
# FTP loader (3 dagen)
# ---------------------------
@st.cache_data(ttl=300)
def load_excels_via_ftp_three_days() -> dict[str, dict]:
    """
    Leest via FTP in map 'steekkaart' na login:
    - Gisteren (vandaag-1), Vandaag, Morgen (vandaag+1)
    - downloadt naar geheugen
    - leest Excel tabblad 'Dienstlijst'
    Retourneert dict per label met: filename (intern), file_date, df (of None als niet gevonden)
    Vereiste secrets: FTP_HOST, FTP_USER, FTP_PASS
    Optioneel: FTP_PORT (default 21)
    """
    host = st.secrets["FTP_HOST"]
    port = int(st.secrets.get("FTP_PORT", 21))
    user = st.secrets["FTP_USER"]
    pw = st.secrets["FTP_PASS"]

    today = date.today()
    targets = {
        "Gisteren": today - timedelta(days=1),
        "Vandaag": today,
        "Morgen": today + timedelta(days=1),
    }

    ftp = FTP()
    try:
        ftp.connect(host=host, port=port, timeout=30)
        ftp.login(user=user, passwd=pw)
        ftp.cwd("steekkaart")

        files = ftp.nlst()

        out: dict[str, dict] = {}
        for label, d in targets.items():
            chosen = choose_file_for_date(files, d)
            if not chosen:
                out[label] = {"filename": None, "file_date": d, "df": None}
                continue

            df_raw = _load_one_excel_from_ftp(ftp, chosen)
            df = _prepare_df(df_raw)

            out[label] = {
                "filename": chosen,  # intern, niet tonen in UI
                "file_date": extract_yyyymmdd(chosen),
                "df": df,
            }

        return out

    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


# ---------------------------
# UI rendering
# ---------------------------
def inject_small_text_css():
    st.markdown(
        """
        <style>
          .small-note { font-size: 14px; line-height: 1.2; opacity: 0.9; }
          .small-muted { font-size: 14px; line-height: 1.2; opacity: 0.75; }
          .small-date { font-size: 14px; line-height: 1.2; opacity: 0.85; margin-top: -6px; }
          /* optioneel: iets minder verticale ruimte onder headers */
          h1, h2, h3 { margin-bottom: 0.25rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_section(label: str, payload: dict, personeelnummer_query: str):
    st.header(label)

    # Enkel datum zichtbaar (bestandsnaam/metrics verbergen)
    file_date = payload.get("file_date")
    df = payload.get("df")

    if file_date:
        st.markdown(
            f'<div class="small-date">Datum: {file_date.isoformat()}</div>',
            unsafe_allow_html=True,
        )

    if df is None:
        st.markdown(
            f'<div class="small-muted">Geen bestand gevonden voor {label.lower()}.</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        return

    # Filter enkel op personeelnummer (exact)
    pn = df["personeelnummer"].fillna("").astype(str)
    results = df[pn == personeelnummer_query].copy()

    if results.empty:
        st.markdown(
            f'<div class="small-muted">Geen rijen gevonden voor personeelnummer <b>{personeelnummer_query}</b> in {label.lower()}.</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        return

    st.success(f"Gevonden: {len(results)} rij(en) in {label}.")
    st.dataframe(results, use_container_width=True, hide_index=True)

    st.divider()


def main():
    inject_small_text_css()

    st.title("Opzoeken voertuig chauffeur")

    # Kleine tekst (14px) zoals gevraagd
    st.markdown(
        '<div class="small-note">Deze app bevat mogelijk fouten door last minute wijzigingen - controleer zeker de uitrijlijst op GBR of E17</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="small-note">Voertuigen worden pas in de loop van de nacht ingeladen voor de huidige dag.</div>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Instellingen")
        refresh = st.button("🔄 Herladen (cache leegmaken)")
        st.caption("Bestanden worden gekozen op basis van datum (yyyymmdd...).")

    if refresh:
        st.cache_data.clear()

    try:
        data = load_excels_via_ftp_three_days()

        st.subheader("Zoeken")
        q = st.text_input(
            "Personeelnummer (exact)",
            placeholder="bv. 38529",
        )

        if not q.strip():
            st.info("Geef een personeelnummer in om resultaten te tonen (gisteren/vandaag/morgen).")
            st.stop()

        q_norm = clean_query(q)

        render_section("Gisteren", data["Gisteren"], q_norm)
        render_section("Vandaag", data["Vandaag"], q_norm)
        render_section("Morgen", data["Morgen"], q_norm)

    except Exception as e:
        st.error(f"FTP inlezen mislukt: {e}")
        st.info(
            "Check of je in de juiste FTP-map zit na login. "
            "Indien nodig: pas `ftp.cwd('steekkaart')` aan naar de correcte mapnaam."
        )


if __name__ == "__main__":
    main()
