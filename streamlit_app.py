# FaturasContinente - Streamlit app
# Single-file Streamlit app: streamlit_app.py
# Purpose: upload Continente PDF receipts (text PDFs), extract date and total,
# store records (Google Sheets optional), and show monthly/annual summaries + charts.

import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
import sqlite3
import os

st.set_page_config(page_title="FaturasContinente", layout="wide")
st.title("🧾 FaturasContinente")
st.write("Faz upload das faturas do Continente (PDF texto). A app extrai data e total e sumariza por mês/ano.")

# -----------------------
# Utilities
# -----------------------

def extract_text_from_pdf_bytes(file_bytes: bytes) -> str:
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        texts = [p.extract_text() or "" for p in pdf.pages]
    return "\n".join(texts)


def extract_date_and_total(text: str):
    # Try to find date formats dd/mm/yyyy or dd-mm-yyyy
    date_match = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", text)
    date = None
    if date_match:
        try:
            date = datetime.strptime(date_match.group(1).replace('-', '/'), "%d/%m/%Y").date()
        except Exception:
            date = None

    # Common patterns for Continente receipts: 'Total a pagar 12,34' or 'TOTAL 12,34€' etc.
    # We'll try a few regexes in order of likelihood.
    patterns = [
        r"Total a pagar\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"TOTAL\s*[:\-]?\s*([0-9]+[.,][0-9]{2})\s*€",
        r"TOTAL\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"TOTAL A PAGAR\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"Valor total\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"(Total)\s*[:\-]?\s*([0-9]+[.,][0-9]{2})"
    ]

    total = None
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            # Some patterns have the value in group 1 or group 2
            val = m.groups()[-1]
            try:
                total = float(val.replace('.', '').replace(',', '.'))
                break
            except Exception:
                continue

    # Fallback: find the last currency-like number on the page
    if total is None:
        all_nums = re.findall(r"[0-9]+[.,][0-9]{2}", text)
        if all_nums:
            try:
                total = float(all_nums[-1].replace('.', '').replace(',', '.'))
            except Exception:
                total = None

    return date, total


# -----------------------
# Storage helpers
# -----------------------

# We'll support two storage modes:
# 1) Google Sheets (recommended for persistent online storage) - requires Streamlit secrets
#    Put service account JSON into st.secrets["gspread_service_account"] and sheet id into st.secrets["gspread_sheet_id"]
# 2) SQLite local file (ephemeral on many free hosts) + CSV download

USE_GSHEETS = False
try:
    # If secrets are set in Streamlit Cloud, use gspread
    if st.secrets.get("gspread_service_account") and st.secrets.get("gspread_sheet_id"):
        USE_GSHEETS = True
except Exception:
    USE_GSHEETS = False

if USE_GSHEETS:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    def gs_connect():
        sa_json = st.secrets["gspread_service_account"]
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(sa_json, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(st.secrets["gspread_sheet_id"]).sheet1
        return sheet

    def gs_append_row(row):
        sheet = gs_connect()
        sheet.append_row(row)

else:
    # SQLite storage
    DB_PATH = "faturas_continente.db"
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        total REAL,
        filename TEXT,
        uploaded_at TEXT
    )
    """)
    conn.commit()

    def sqlite_insert(date_str, total, filename):
        cur.execute("INSERT INTO receipts (date, total, filename, uploaded_at) VALUES (?, ?, ?, datetime('now'))",
                    (date_str, total, filename))
        conn.commit()

    def sqlite_fetch_all():
        df = pd.read_sql_query("SELECT date, total, filename, uploaded_at FROM receipts ORDER BY date", conn)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date']).dt.date
        return df

# -----------------------
# UI: upload
# -----------------------

st.header("📤 Upload de faturas")
uploaded_files = st.file_uploader("Envia aqui as faturas PDF do Continente", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    added = 0
    errors = []
    for up in uploaded_files:
        raw = up.read()
        text = extract_text_from_pdf_bytes(raw)
        date, total = extract_date_and_total(text)

        if date is None or total is None:
            errors.append((up.name, date, total))
            continue

        # Save to storage
        date_str = date.strftime("%Y-%m-%d")
        if USE_GSHEETS:
            try:
                gs_append_row([date_str, f"{total:.2f}", up.name])
                added += 1
            except Exception as e:
                errors.append((up.name, str(e)))
        else:
            try:
                sqlite_insert(date_str, total, up.name)
                added += 1
            except Exception as e:
                errors.append((up.name, str(e)))

    st.success(f"Processados: {added} faturas")
    if errors:
        st.warning("Algumas faturas não foram processadas corretamente. Ver detalhes abaixo.")
        st.write(errors)

# -----------------------
# UI: Display database & summaries
# -----------------------
st.header("📈 Resumo de gastos")

if USE_GSHEETS:
    st.info("Aguardando dados do Google Sheets (modo ativo). Os dados serão lidos diretamente da folha.)")
    try:
        sheet = gs_connect()
        values = sheet.get_all_records()
        df = pd.DataFrame(values)
        if not df.empty:
            # Expecting columns like [date, total, filename]
            if 'date' in df.columns and 'total' in df.columns:
                df['date'] = pd.to_datetime(df['date']).dt.date
                df['total'] = df['total'].astype(float)
            else:
                # Try guessing columns
                df.columns = ['date', 'total', 'filename']
                df['date'] = pd.to_datetime(df['date']).dt.date
                df['total'] = df['total'].astype(float)
        else:
            df = pd.DataFrame(columns=['date','total','filename'])
    except Exception as e:
        st.error(f"Erro ao ler Google Sheets: {e}")
        df = pd.DataFrame(columns=['date','total','filename'])

else:
    df = sqlite_fetch_all()

if df.empty:
    st.write("Sem faturas ainda. Faz upload acima para começar.")
else:
    # Normalize df
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df['month'] = df['date'].dt.to_period('M').dt.to_timestamp()
    df['year'] = df['date'].dt.year
    df['total'] = df['total'].astype(float)

    # Monthly summary
    monthly = df.groupby('month')['total'].sum().reset_index()
    yearly = df.groupby('year')['total'].sum().reset_index()

    col1, col2 = st.columns([2,1])
    with col1:
        st.subheader("Gasto por mês")
        st.bar_chart(monthly.set_index('month'))
    with col2:
        st.subheader("Gasto por ano")
        st.table(yearly)

    st.subheader("Detalhe das faturas")
    st.dataframe(df.sort_values('date', ascending=False).reset_index(drop=True))

    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Exportar CSV", data=csv, file_name="faturas_continente.csv", mime='text/csv')

# -----------------------
# Footer / Help
# -----------------------

st.markdown("""**requirements.txt** suggestion:\n
streamlit
pdfplumber
pandas
gspread
oauth2client
""")

st.markdown("---")
st.caption("App criada: **FaturasContinente** — modifica este ficheiro conforme necessidades (extras: identificar supermercado, número de fatura, categorias por palavras-chave, tags, etc.).")
