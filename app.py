# app.py
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from ftplib import FTP
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ---------------------------
# Optional dependency (fail-safe)
# ---------------------------
try:
    from streamlit_javascript import st_javascript  # pip install streamlit-javascript
except ModuleNotFoundError:
    st_javascript = None

st.set_page_config(page_title="Opzoeken voertuig chauffeur", layout="wide")

CACHE_TTL_SECONDS = 300  # 5 minuten


# ---------------------------
# Helpers
# ---------------------------
def now_be() -> datetime:
    return datetime.now(ZoneInfo("Europe/Brussels"))


def belgium_today() -> date:
    return now_be().date()


def format_time(val) -> str:
    """Format tijd naar HH:MM (verwijdert seconden)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        if hasattr(val, "strftime"):
            return val.strftime("%H:%M")
    except Exception:
        pass

    s = str(val).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) >= 2:
            return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
    return s


# ✅ Datum nu dd/mm/yyyy
def format_date_ddmmyy(d) -> str:
    """Datum formatter dd/mm/yyyy."""
    if not d:
        return ""
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d)


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
    return pd.read_excel(bio, sheet_name="Dienstlijst")


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

    col_map = {}
    for excel_name, out_name in wanted_cols.items():
        found = _find_col(df_raw, excel_name)
        if found:
            col_map[found] = out_name

    df = df_raw[list(col_map.keys())].rename(columns=col_map)

    df["personeelnummer"] = clean_id_series(df["personeelnummer"])
    df["voertuig"] = clean_id_series(df["voertuig"])
    df["voertuigwissel"] = clean_id_series(df["voertuigwissel"])

    if "uur" in df.columns:
        try:
            df = df.sort_values("uur")
        except Exception:
            pass

    df = df.set_index("personeelnummer", drop=False)
    return df


# ---------------------------
# Viewport detectie
# ---------------------------
def get_viewport_width() -> int | None:
    if st_javascript is None:
        return None
    w = st_javascript("window.innerWidth")
    try:
        return int(w)
    except Exception:
        return None


def is_small_screen(width: int | None, breakpoint: int = 700) -> bool:
    return width is not None and width < breakpoint


# ---------------------------
# FTP loader
# ---------------------------
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_excels_via_ftp_three_days() -> dict:
    host = st.secrets["FTP_HOST"]
    port = int(st.secrets.get("FTP_PORT", 21))
    user = st.secrets["FTP_USER"]
    pw = st.secrets["FTP_PASS"]

    today = belgium_today()
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

        out = {}
        for label, d in targets.items():
            chosen = choose_file_for_date(files, d)
            if not chosen:
                out[label] = {"filename": None, "file_date": d, "df": None}
                continue

            df_raw = _load_one_excel_from_ftp(ftp, chosen)
            df = _prepare_df(df_raw)

            out[label] = {
                "filename": chosen,
                "file_date": extract_yyyymmdd(chosen),
                "df": df,
            }

        return {"loaded_at": now_be(), "data": out}

    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


# ---------------------------
# UI rendering
# ---------------------------
def inject_css():
    st.markdown(
        """
        <style>
          .small-note { font-size: 12px !important; }
          .small-muted { font-size: 14px !important; opacity: 0.75; } /* ✅ 2px groter */
          .small-date { font-size: 12px !important; margin-top: -6px; }

          .neon-title {
            font-size: 28px !important;
            font-weight: 900 !important;
            color:#39ff14 !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_section(label, payload, personeelnummer_query):

    st.markdown(f'<div class="neon-title">{label}</div>', unsafe_allow_html=True)

    file_date = payload.get("file_date")
    df = payload.get("df")

    if file_date:
        st.markdown(
            f'<div class="small-date">Datum: {format_date_ddmmyy(file_date)}</div>',
            unsafe_allow_html=True,
        )

    if df is None:
        st.markdown('<div class="small-muted">Er is geen dienst terug te vinden voor u</div>', unsafe_allow_html=True)
        return

    if personeelnummer_query in df.index:
        results = df.loc[[personeelnummer_query]].copy()
    else:
        results = df.iloc[0:0].copy()

    if results.empty:
        st.markdown('<div class="small-muted">Er is geen dienst terug te vinden voor u</div>', unsafe_allow_html=True)
        return

    st.success(f"Gevonden: {len(results)} rij(en) in {label}.")
    st.dataframe(results.reset_index(drop=True), use_container_width=True, hide_index=True)


def main():

    inject_css()

    width = get_viewport_width()
    small = is_small_screen(width)

    default_day = "Vandaag" if small else "Alles"

    st.title("Opzoeken voertuig chauffeur")

    payload = load_excels_via_ftp_three_days()
    data = payload["data"]

    q = st.text_input("Personeelnummer")

    if not q.strip():
        st.stop()

    q_norm = clean_query(q)

    options = ["Vandaag", "Gisteren", "Morgen", "Alles"]

    day = st.radio(
        "Kies dag",
        options=options,
        index=options.index(default_day),
        horizontal=True,
        label_visibility="collapsed",
    )

    st.divider()

    # ✅ geen divider meer tussen dagen
    if day == "Alles":
        for label in ["Gisteren", "Vandaag", "Morgen"]:
            render_section(label, data[label], q_norm)
    else:
        render_section(day, data[day], q_norm)


if __name__ == "__main__":
    main()
