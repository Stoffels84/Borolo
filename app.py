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


def format_date_ddmmyy(d) -> str:
    """Datum formatter ddmmyy."""
    if not d:
        return ""
    try:
        return d.strftime("%d%m%y")
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

    # Optioneel: sorteer op uur als dat lukt (mobiel: chronologisch is rustiger)
    if "uur" in df.columns:
        try:
            df = df.sort_values("uur")
        except Exception:
            pass

    # Sneller zoeken: index op personeelnummer
    df = df.set_index("personeelnummer", drop=False)

    return df


# ---------------------------
# Viewport detectie (stap 2)
# ---------------------------
def get_viewport_width() -> int | None:
    """Meet viewport breedte als JS component beschikbaar is."""
    if st_javascript is None:
        return None
    w = st_javascript("window.innerWidth")
    try:
        return int(w) if w is not None else None
    except Exception:
        return None


def is_small_screen(width: int | None, breakpoint: int = 700) -> bool:
    if width is None:
        return False
    return width < breakpoint


# ---------------------------
# FTP loader (3 dagen)
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

        out: dict[str, dict] = {}
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
            try:
                ftp.close()
            except Exception:
                pass


# ---------------------------
# UI rendering
# ---------------------------
def inject_css():
    st.markdown(
        """
        <style>
          .small-note { font-size: 12px !important; line-height: 1.25; opacity: 0.9; }
          .small-muted { font-size: 12px !important; line-height: 1.25; opacity: 0.75; }
          .small-date { font-size: 12px !important; line-height: 1.25; opacity: 0.85; margin-top: -6px; }

          div[data-testid="stMarkdownContainer"] .neon-title,
          div[data-testid="stMarkdownContainer"] .neon-title * { color: #39ff14 !important; }

          .neon-title {
            font-size: 28px !important;
            font-weight: 900 !important;
            letter-spacing: 0.3px;
            margin-top: 10px;
            margin-bottom: 2px;
            text-shadow: 0 0 6px rgba(57,255,20,0.65), 0 0 14px rgba(57,255,20,0.45);
          }

          .card {
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 16px;
            padding: 12px 12px;
            margin: 10px 0 12px 0;
            background: rgba(255,255,255,0.03);
          }
          .kv { display:flex; gap:10px; flex-wrap:wrap; margin-top: 6px; }
          .pill {
            display:inline-block;
            padding:6px 10px;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.12);
            background: rgba(255,255,255,0.03);
            font-size: 14px;
            line-height: 1;
          }
          .pill b { font-weight: 800; }

          div[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }

          @media (max-width: 700px) {
            .block-container { padding-top: .8rem; padding-bottom: .8rem; padding-left: .7rem; padding-right: .7rem; }
            div[data-testid="stTextInput"] input { font-size: 18px !important; padding: 12px 12px !important; }
            div[data-testid="stButton"] button { width: 100%; padding: 12px 14px !important; font-size: 16px !important; border-radius: 14px !important; }
            .neon-title { font-size: 22px !important; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def auto_pick_columns(df: pd.DataFrame, max_cols: int) -> list[str]:
    preferred_tokens = [
        "uur", "tijd", "time", "naam", "name", "voertuig", "vehicle",
        "plaats", "locatie", "location", "richting", "loop", "dienst", "adres",
        "id", "nr", "nummer", "wissel", "change"
    ]
    cols = list(df.columns)

    def score(col: str) -> int:
        c = str(col).lower()
        s = 0
        if any(t in c for t in preferred_tokens):
            s += 3
        if len(c) <= 10:
            s += 1
        if any(t in c for t in ["omschrijving", "description", "comment", "opmerking", "details"]):
            s -= 2
        return s

    ranked = sorted(cols, key=score, reverse=True)
    return ranked[: max_cols if len(ranked) >= max_cols else len(ranked)]


def render_results_cards(df: pd.DataFrame, max_cols: int, default_expand: bool):
    cols = auto_pick_columns(df, max_cols=max_cols)
    view = df[cols].copy()

    def make_header(row: pd.Series, idx: int) -> str:
        uur = format_time(row.get("uur", "")) if "uur" in row else ""
        voertuig = str(row.get("voertuig", "")).strip() if "voertuig" in row else ""
        naam = str(row.get("naam", "")).strip() if "naam" in row else ""
        base = " • ".join([x for x in [uur, voertuig] if x])
        return base or naam or f"Resultaat {idx+1}"

    for i, row in view.reset_index(drop=True).iterrows():
        with st.expander(make_header(row, i), expanded=(default_expand and i == 0)):
            st.markdown('<div class="card">', unsafe_allow_html=True)
            pills = []
            for c in cols:
                v = row.get(c, "")
                if str(c).lower() == "uur":
                    v = format_time(v)
                if pd.isna(v) or str(v).strip() == "":
                    continue
                pills.append(f'<span class="pill"><b>{c}</b> {v}</span>')
            st.markdown(
                f'<div class="kv">{"".join(pills) if pills else "<span class=\'pill\'>Leeg</span>"}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)


def render_section(
    label: str,
    payload: dict,
    personeelnummer_query: str,
    show_table: bool,
    max_cols: int,
    expand_first: bool
):
    st.markdown(f'<div class="neon-title"><span>{label}</span></div>', unsafe_allow_html=True)

    file_date = payload.get("file_date")
    df = payload.get("df")

    if file_date:
        st.markdown(
            f'<div class="small-date">Datum: {format_date_ddmmyy(file_date)}</div>',
            unsafe_allow_html=True,
        )

    if df is None:
        st.markdown(
            f'<div class="small-muted">Geen bestand gevonden voor {label.lower()}.</div>',
            unsafe_allow_html=True,
        )
        return

    if personeelnummer_query in df.index:
        results = df.loc[[personeelnummer_query]].copy()
    else:
        results = df.iloc[0:0].copy()

    # ✅ Tekst vervangen zoals gevraagd
    if results.empty:
        st.markdown(
            '<div class="small-muted">Er is geen dienst terug te vinden voor u</div>',
            unsafe_allow_html=True,
        )
        return

    st.success(f"Gevonden: {len(results)} rij(en) in {label}.")
    render_results_cards(results, max_cols=max_cols, default_expand=expand_first)

    if show_table:
        height = 260 if max_cols <= 6 else 420
        st.dataframe(
            results.reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            height=height,
        )


def main():
    inject_css()

    width = get_viewport_width()
    small = is_small_screen(width, breakpoint=700)

    default_day = "Vandaag" if small else "Alles"
    default_show_table = False if small else True
    max_cols = 6 if small else 10
    expand_first = True if small else False

    st.title("Opzoeken voertuig chauffeur")
    st.markdown(
        '<div class="small-note">Deze app bevat mogelijk fouten door last minute wijzigingen - controleer zeker de uitrijlijst op GBR of E17</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="small-note">Voertuigen worden pas in de loop van de nacht ingeladen voor de huidige dag.</div>',
        unsafe_allow_html=True,
    )

    with st.expander("⚙️ Instellingen", expanded=False):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            refresh = st.button("🔄 Herladen (cache leegmaken)")
        with c2:
            show_table = st.toggle("Toon tabel", value=default_show_table)
        with c3:
            st.caption(f"Viewport: {width}px" if width else "Viewport: onbekend")

        st.caption("Bestanden worden gekozen op basis van datum (yyyymmdd...).")

    if refresh:
        st.cache_data.clear()
        st.rerun()

    try:
        payload = load_excels_via_ftp_three_days()
        data = payload["data"]

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Zoeken")
        q = st.text_input(
            "Personeelnummer (exact)",
            placeholder="bv. 38529",
            label_visibility="collapsed",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        if not q.strip():
            st.info("Geef een personeelnummer in om resultaten te tonen (gisteren/vandaag/morgen).")
            st.stop()

        q_norm = clean_query(q)

        options = ["Vandaag", "Gisteren", "Morgen", "Alles"]
        idx = options.index(default_day) if default_day in options else 0

        day = st.radio(
            "Kies dag",
            options=options,
            index=idx,
            horizontal=True,
            label_visibility="collapsed",
        )

        # (mag blijven) scheidingslijn tussen keuze en resultaten
        st.divider()

        # ✅ divider tussen gisteren/vandaag/morgen verwijderd bij "Alles"
        if day == "Alles":
            for label in ["Gisteren", "Vandaag", "Morgen"]:
                render_section(label, data[label], q_norm, show_table, max_cols, expand_first)
        else:
            render_section(day, data[day], q_norm, show_table, max_cols, expand_first)

    except Exception as e:
        st.error(f"FTP inlezen mislukt: {e}")
        st.info(
            "Check of je in de juiste FTP-map zit na login. "
            "Indien nodig: pas `ftp.cwd('steekkaart')` aan naar de correcte mapnaam."
        )


if __name__ == "__main__":
    main()
