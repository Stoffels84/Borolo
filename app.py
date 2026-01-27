import re
from datetime import date, datetime
from io import BytesIO
from ftplib import FTP
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Steekkaart van vandaag", layout="wide")

def extract_yyyymmdd(name: str):
    m = re.match(r"^(\d{8})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None

def choose_file(files: list[str], suffix: str, today: date) -> str | None:
    # Alleen bestanden met juiste suffix én datum vooraan
    candidates = []
    for f in files:
        if not f.lower().endswith(suffix.lower()):
            continue
        d = extract_yyyymmdd(f)
        if d is None:
            continue
        candidates.append((f, d))

    if not candidates:
        return None

    # 1) exact vandaag (kan meerdere: neem alfabetisch laatste)
    today_matches = [f for f, d in candidates if d == today]
    if today_matches:
        return sorted(today_matches)[-1]

    # 2) anders: meest recente datum
    return max(candidates, key=lambda x: x[1])[0]

def ftp_try_cwd(ftp: FTP, path: str) -> None:
    """
    Probeer een paar varianten die vaak voorkomen op shared hosting.
    """
    path = path.strip()
    if not path:
        return

    tries = []
    # exact zoals uit URL
    tries.append(path)
    # zonder leading slash
    if path.startswith("/"):
        tries.append(path[1:])
    # met public_html ervoor
    if path.startswith("/"):
        tries.append("/public_html" + path)
        tries.append("public_html" + path)
    else:
        tries.append("public_html/" + path)

    last_err = None
    for p in tries:
        try:
            ftp.cwd(p)
            return
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Kon FTP-map niet openen. Laatste fout: {last_err}")

@st.cache_data(ttl=300)
def load_excel_via_ftp() -> tuple[str, pd.DataFrame]:
    user = st.secrets["HOST_USER"]
    pw = st.secrets["HOST_PASS"]
    base_url = st.secrets["DATA_BASE_URL"]  # bv "https://otgent.borolo.be/data/"
    suffix = st.secrets["FILE_SUFFIX"]      # bv "_steekkaart.xlsx"

    parsed = urlparse(base_url)
    ftp_host = parsed.hostname              # otgent.borolo.be
    url_path = parsed.path                  # /data/

    if not ftp_host:
        raise RuntimeError("DATA_BASE_URL bevat geen geldige hostname.")

    today = date.today()

    ftp = FTP()
    try:
        ftp.connect(ftp_host, 21, timeout=30)
        ftp.login(user=user, passwd=pw)

        # ga naar directory die bij de URL hoort
        ftp_try_cwd(ftp, url_path)

        files = ftp.nlst()
        chosen = choose_file(files, suffix=suffix, today=today)
        if not chosen:
            raise RuntimeError(
                f"Geen bestanden gevonden die beginnen met yyyymmdd en eindigen op '{suffix}'."
            )

        bio = BytesIO()
        ftp.retrbinary(f"RETR {chosen}", bio.write)
        bio.seek(0)

        df = pd.read_excel(bio)  # openpyxl via requirements
        return chosen, df

    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass

st.title("Steekkaart: bestand van vandaag")

try:
    filename, df = load_excel_via_ftp()
    file_date = extract_yyyymmdd(filename)

    c1, c2, c3 = st.columns(3)
    c1.metric("Gekozen bestand", filename)
    c2.metric("Bestandsdatum", file_date.isoformat() if file_date else "—")
    c3.metric("Vandaag", date.today().isoformat())

    st.dataframe(df, use_container_width=True)

except Exception as e:
    st.error(f"FTP inlezen mislukt: {e}")
    st.caption(
        "Tip: als de map niet gevonden wordt, is het FTP-pad vaak anders (bv. /public_html/data/). "
        "Dit script probeert die varianten al automatisch."
    )
