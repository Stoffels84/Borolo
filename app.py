# app.py
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from ftplib import FTP
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Voertuig chauffeur", layout="wide")


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
    IDs altijd 'proper' tekst:
    - non-breaking spaces weg
    - strip
    - trailing .0 verwijderen (Excel float)
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

    # Mobiel: sorteer logisch (als uur bestaat)
    if "uur" in df.columns:
        try:
            df = df.sort_values("uur")
        except Exception:
            pass

    return df


def belgium_today() -> date:
    return datetime.now(ZoneInfo("Europe/Brussels")).date()


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

            # Sneller zoeken: index op personeelnummer
            df = df.set_index("personeelnummer", drop=False)

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
# UI (mobiel)
# ---------------------------
def inject_mobile_css():
    st.markdown(
        """
        <style>
          /* Breder en compacter op mobiel */
          .block-container { padding-top: 1rem; padding-bottom: 1rem; }

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

          /* Compacte info-tekst */
          .small-note { font-size: 12px !important; line-height: 1.25; opacity: 0.9; margin-top: 2px; }
          .small-muted { font-size: 12px !important; line-height: 1.25; opacity: 0.75; }
          .small-date { font-size: 12px !important; line-height: 1.25; opacity: 0.85; margin-top: -6px; }

          /* Titel neon (zoals je had) */
          div[data-testid="stMarkdownContainer"] .neon-title,
          div[data-testid="stMarkdownContainer"] .neon-title * {
            color: #39ff14 !important;
          }
          .neon-title {
            font-size: 22px !important;
            font-weight: 900 !important;
            letter-spacing: 0.2px;
            margin-top: 10px;
            margin-bottom: 2px;
            text-shadow:
              0 0 6px rgba(57, 255, 20, 0.65),
              0 0 14px rgba(57, 255, 20, 0.45);
          }

          /* Kaart-look */
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
            font-size: 12px;
            line-height: 1;
          }
          .pill b { font-weight: 800; }

          /* Tabellen: minder hoog, minder padding */
          div[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _compact_view(df: pd.DataFrame) -> pd.DataFrame:
    """
    Kies welke kolommen je op mobiel wil tonen.
    Pas gerust aan.
    """
    preferred = ["uur", "naam", "voertuig", "voertuigwissel", "plaats", "richting", "Loop", "Dienstadres"]
    cols = [c for c in preferred if c in df.columns]
    if not cols:
        return df
    return df[cols]


def render_day(label: str, payload: dict, personeelnummer_query: str, show_table: bool):
    st.markdown(f'<div class="neon-title"><span>{label}</span></div>', unsafe_allow_html=True)

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

    # Supersnelle lookup door index
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

    # Mobiel: toon eerst “cards”
    compact = _compact_view(results)

    for i, row in compact.reset_index(drop=True).iterrows():
        uur = row.get("uur", "")
        naam = row.get("naam", "")
        voertuig = row.get("voertuig", "")
        wissel = row.get("voertuigwissel", "")
        plaats = row.get("plaats", "")
        richting = row.get("richting", "")

        header = f"{uur} • {voertuig}" if str(uur).strip() else f"{voertuig}"
        with st.expander(header, expanded=(len(compact) <= 2 and i == 0)):
            st.markdown('<div class="card">', unsafe_allow_html=True)
            pills = []
            if str(naam).strip():
                pills.append(f'<span class="pill"><b>Naam</b> {naam}</span>')
            if str(plaats).strip():
                pills.append(f'<span class="pill"><b>Plaats</b> {plaats}</span>')
            if str(richting).strip():
                pills.append(f'<span class="pill"><b>Richting</b> {richting}</span>')
            if str(voertuig).strip():
                pills.append(f'<span class="pill"><b>Voertuig</b> {voertuig}</span>')
            if str(wissel).strip():
                pills.append(f'<span class="pill"><b>Wissel</b> {wissel}</span>')

            st.markdown(f'<div class="kv">{"".join(pills)}</div>', unsafe_allow_html=True)

            # Extra velden compact onderaan (als ze bestaan)
            extras = []
            for k in ["Loop", "Dienstadres"]:
                if k in compact.columns and str(row.get(k, "")).strip():
                    extras.append(f"**{k}:** {row.get(k)}")
            if extras:
                st.markdown("\n\n".join(extras))

            st.markdown("</div>", unsafe_allow_html=True)

    # Optioneel: tabel tonen (handig op desktop of als je alles wil zien)
    if show_table:
        st.dataframe(compact.reset_index(drop=True), use_container_width=True, hide_index=True, height=260)


def main():
    inject_mobile_css()

    # Bovenaan compact: titel + waarschuwingen
    st.markdown("## Opzoeken voertuig chauffeur")
    st.markdown(
        '<div class="small-note">Deze app bevat mogelijk fouten door last minute wijzigingen — controleer zeker de uitrijlijst op GBR of E17.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="small-note">Voertuigen worden pas in de loop van de nacht ingeladen voor de huidige dag.</div>',
        unsafe_allow_html=True,
    )

    # “Instellingen” in expander i.p.v. sidebar (sidebar is vaak irritant op mobiel)
    with st.expander("⚙️ Instellingen", expanded=False):
        colA, colB = st.columns([1, 1])
        with colA:
            refresh = st.button("🔄 Herladen (cache leegmaken)")
        with colB:
            show_table = st.toggle("Toon tabel", value=False)
        st.caption("Bestanden worden gekozen op basis van datum (yyyymmdd...).")

    if refresh:
        st.cache_data.clear()

    try:
        data = load_excels_via_ftp_three_days()

        # Zoek “kaart”
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Zoeken", help="Typ een personeelnummer. De match is exact.")
        q = st.text_input("Personeelnummer", placeholder="bv. 38529", label_visibility="collapsed")
        st.markdown("</div>", unsafe_allow_html=True)

        if not q.strip():
            st.info("Geef een personeelnummer in om resultaten te tonen.")
            st.stop()

        q_norm = clean_query(q)

        # Dagkeuze: minder scroll (mobiel-first)
        day = st.radio(
            "Kies dag",
            options=["Vandaag", "Gisteren", "Morgen", "Alles"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
        )

        st.divider()

        if day == "Alles":
            for label in ["Gisteren", "Vandaag", "Morgen"]:
                render_day(label, data[label], q_norm, show_table=show_table)
                st.divider()
        else:
            render_day(day, data[day], q_norm, show_table=show_table)

    except Exception as e:
        st.error(f"FTP inlezen mislukt: {e}")
        st.info(
            "Check of je in de juiste FTP-map zit na login. "
            "Indien nodig: pas `ftp.cwd('steekkaart')` aan naar de correcte mapnaam."
        )


if __name__ == "__main__":
    main()
