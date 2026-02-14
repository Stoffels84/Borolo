# app.py
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from ftplib import FTP
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ✅ stap 1/2: viewport detectie via JS component
from streamlit_javascript import st_javascript

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

    # Optioneel: sorteer op uur als dat lukt (mobiel: chronologisch is rustiger)
    if "uur" in df.columns:
        try:
            df = df.sort_values("uur")
        except Exception:
            pass

    # Sneller zoeken: index op personeelnummer
    df = df.set_index("personeelnummer", drop=False)

    return df


def belgium_today() -> date:
    return datetime.now(ZoneInfo("Europe/Brussels")).date()


# ---------------------------
# Viewport detectie (stap 2)
# ---------------------------
def get_viewport_width() -> int | None:
    """
    Betrouwbare 'universele' detectie: meet viewport-breedte.
    Kan bij eerste run None zijn.
    """
    w = st_javascript("window.innerWidth")
    try:
        return int(w) if w is not None else None
    except Exception:
        return None


def is_small_screen(width: int | None, breakpoint: int = 700) -> bool:
    # Fallback: als onbekend, gedraag je als desktop (veiliger voor debugging),
    # maar je kan dit ook naar True zetten als je “mobiel-first” wil.
    if width is None:
        return False
    return width < breakpoint


# ---------------------------
# FTP loader (3 dagen)
# ---------------------------
@st.cache_data(ttl=300)
def load_excels_via_ftp_three_days() -> dict[str, dict]:
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
# UI rendering (stap 1 + 3)
# ---------------------------
def inject_css():
    # ✅ stap 1: CSS media queries + universele touch targets + jouw neon titel
    st.markdown(
        """
        <style>
          .small-note { font-size: 12px !important; line-height: 1.25; opacity: 0.9; }
          .small-muted { font-size: 12px !important; line-height: 1.25; opacity: 0.75; }
          .small-date { font-size: 12px !important; line-height: 1.25; opacity: 0.85; margin-top: -6px; }

          /* SUPER-specifiek: Streamlit markdown container + onze class */
          div[data-testid="stMarkdownContainer"] .neon-title,
          div[data-testid="stMarkdownContainer"] .neon-title * {
            color: #39ff14 !important;
          }
          .neon-title {
            font-size: 28px !important;
            font-weight: 900 !important;
            letter-spacing: 0.3px;
            margin-top: 10px;
            margin-bottom: 2px;
            text-shadow:
              0 0 6px rgba(57, 255, 20, 0.65),
              0 0 14px rgba(57, 255, 20, 0.45);
          }

          /* Kaartstijl (werkt overal, niet app-specifiek) */
          .card {
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 16px;
            padding: 12px 12px;
            margin: 10px 0 12px 0;
            background: rgba(255,255,255,0.03);
          }
          .kv { display:flex; gap:10px; flex-wrap:wrap; margin-top: 6px; }
          .pill {
            display:inline-block; padding:6px 10px;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.12);
            background: rgba(255,255,255,0.03);
            font-size: 12px; line-height: 1;
          }
          .pill b { font-weight: 800; }

          /* Compactere dataframe look */
          div[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }

          /* ✅ Responsive gedrag via media query */
          @media (max-width: 700px) {
            .block-container { padding-top: .8rem; padding-bottom: .8rem; padding-left: .7rem; padding-right: .7rem; }

            /* Grotere touch targets */
            div[data-testid="stTextInput"] input {
              font-size: 18px !important;
              padding: 12px 12px !important;
            }
            div[data-testid="stButton"] button {
              width: 100%;
              padding: 12px 14px !important;
              font-size: 16px !important;
              border-radius: 14px !important;
            }

            /* Titel net iets kleiner op mobiel */
            .neon-title { font-size: 22px !important; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def auto_pick_columns(df: pd.DataFrame, max_cols: int) -> list[str]:
    """
    Universele kolomselectie (app-onafhankelijk) om cards compact te houden.
    """
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
    """
    Toon resultaten mobielvriendelijk als cards (expanders).
    """
    cols = auto_pick_columns(df, max_cols=max_cols)
    view = df[cols].copy()

    # Header voorkeur: uur/voertuig als die bestaan
    def make_header(row: pd.Series, idx: int) -> str:
        uur = str(row.get("uur", "")).strip() if "uur" in row else ""
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
                if pd.isna(v) or str(v).strip() == "":
                    continue
                pills.append(f'<span class="pill"><b>{c}</b> {v}</span>')
            st.markdown(
                f'<div class="kv">{"".join(pills) if pills else "<span class=\'pill\'>Leeg</span>"}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)


def render_section(label: str, payload: dict, personeelnummer_query: str, show_table: bool, max_cols: int, expand_first: bool):
    st.markdown(
        f'<div class="neon-title"><span>{label}</span></div>',
        unsafe_allow_html=True,
    )

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
        return

    # Snel: index lookup
    if personeelnummer_query in df.index:
        results = df.loc[[personeelnummer_query]].copy()
    else:
        results = df.iloc[0:0].copy()

    if results.empty:
        st.markdown(
            f'<div class="small-muted">Geen rijen gevonden voor personeelnummer <b>{personeelnummer_query}</b> in {label.lower()}.</div>',
            unsafe_allow_html=True,
        )
        return

    st.success(f"Gevonden: {len(results)} rij(en) in {label}.")

    # Cards (mobiel/desktop allebei ok)
    render_results_cards(results, max_cols=max_cols, default_expand=expand_first)

    # Optionele tabel
    if show_table:
        # niet te hoog op mobiel
        height = 260 if max_cols <= 6 else 420
        st.dataframe(
            results.reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            height=height,
        )


def main():
    inject_css()

    # ✅ stap 2: viewport detecteren
    width = get_viewport_width()
    small = is_small_screen(width, breakpoint=700)

    # ✅ stap 3: logica defaults aanpassen op basis van viewport
    # Mobiel: toon standaard 1 dag, geen tabel, minder kolommen
    default_day = "Vandaag" if small else "Alles"
    default_show_table = False if small else True
    max_cols = 6 if small else 10
    expand_first = True if small else False

    # Header compact
    st.title("Opzoeken voertuig chauffeur")
    st.markdown(
        '<div class="small-note">Deze app bevat mogelijk fouten door last minute wijzigingen - controleer zeker de uitrijlijst op GBR of E17</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="small-note">Voertuigen worden pas in de loop van de nacht ingeladen voor de huidige dag.</div>',
        unsafe_allow_html=True,
    )

    # Instellingen: expander (werkt beter op mobiel dan sidebar)
    with st.expander("⚙️ Instellingen", expanded=False):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            refresh = st.button("🔄 Herladen (cache leegmaken)")
        with c2:
            show_table = st.toggle("Toon tabel", value=default_show_table)
        with c3:
            # Optioneel: tonen voor debugging (kan je later weghalen)
            st.caption(f"Viewport: {width}px" if width else "Viewport: onbekend")

        st.caption("Bestanden worden gekozen op basis van datum (yyyymmdd...).")

    if refresh:
        st.cache_data.clear()

    try:
        data = load_excels_via_ftp_three_days()

        # Zoeken in een “kaart”
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Zoeken")
        q = st.text_input("Personeelnummer (exact)", placeholder="bv. 38529", label_visibility="collapsed")
        st.markdown("</div>", unsafe_allow_html=True)

        if not q.strip():
            st.info("Geef een personeelnummer in om resultaten te tonen (gisteren/vandaag/morgen).")
            st.stop()

        q_norm = clean_query(q)

        # Dagkeuze: mobiel minder scroll
        options = ["Vandaag", "Gisteren", "Morgen", "Alles"]
        day = st.radio(
            "Kies dag",
            options=options,
            index=options.index(default_day),
            horizontal=True,
            label_visibility="collapsed",
        )

        st.divider()

        if day == "Alles":
            for label in ["Gisteren", "Vandaag", "Morgen"]:
                render_section(
                    label,
                    data[label],
                    q_norm,
                    show_table=show_table,
                    max_cols=max_cols,
                    expand_first=expand_first,
                )
                st.divider()
        else:
            render_section(
                day,
                data[day],
                q_norm,
                show_table=show_table,
                max_cols=max_cols,
                expand_first=expand_first,
            )

    except Exception as e:
        st.error(f"FTP inlezen mislukt: {e}")
        st.info(
            "Check of je in de juiste FTP-map zit na login. "
            "Indien nodig: pas `ftp.cwd('steekkaart')` aan naar de correcte mapnaam."
        )


if __name__ == "__main__":
    main()
