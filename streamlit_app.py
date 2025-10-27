import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
import sqlite3

st.set_page_config(page_title="Faturas Continente", layout="wide")
st.title("🧾 Registo de Gastos Continente")

# -----------------------
# Funções auxiliares
# -----------------------

def extract_text_from_pdf_bytes(file_bytes: bytes) -> str:
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        texts = [p.extract_text() or "" for p in pdf.pages]
    return "\n".join(texts)


def extract_date_and_total(text: str):
    date_match = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", text)
    date = None
    if date_match:
        try:
            date = datetime.strptime(date_match.group(1).replace('-', '/'), "%d/%m/%Y").date()
        except Exception:
            date = None

    patterns = [
        r"Total a pagar\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"TOTAL\s*[:\-]?\s*([0-9]+[.,][0-9]{2})\s*€",
        r"TOTAL\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"TOTAL A PAGAR\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
        r"Valor total\s*[:\-]?\s*([0-9]+[.,][0-9]{2})",
    ]

    total = None
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            val = m.group(1)
            try:
                total = float(val.replace('.', '').replace(',', '.'))
                break
            except Exception:
                continue

    if total is None:
        all_nums = re.findall(r"[0-9]+[.,][0-9]{2}", text)
        if all_nums:
            try:
                total = float(all_nums[-1].replace('.', '').replace(',', '.'))
            except Exception:
                total = None

    return date, total

# -----------------------
# Base de dados SQLite
# -----------------------
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
# Menu superior (abas)
# -----------------------
tab1, tab2, tab3 = st.tabs(["📤 Inserir Faturas", "📈 Ver Gastos", "🗑️ Eliminar Faturas"])

# -----------------------
# Página: Inserir Faturas
# -----------------------
with tab1:
    st.header("📤 Inserir novas faturas")

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

            date_str = date.strftime("%Y-%m-%d")
            try:
                sqlite_insert(date_str, total, up.name)
                added += 1
            except Exception as e:
                errors.append((up.name, str(e)))

        st.success(f"✅ {added} faturas processadas com sucesso.")
        if errors:
            st.warning("⚠️ Algumas faturas não foram processadas corretamente.")
            st.write(errors)

# -----------------------
# Página: Ver Gastos
# -----------------------
with tab2:
    st.header("📈 Visualização de gastos")

    df = sqlite_fetch_all()
    if df.empty:
        st.info("Ainda não há faturas registadas.")
    else:
        df['date'] = pd.to_datetime(df['date'])
        df['month'] = df['date'].dt.to_period('M').dt.to_timestamp()
        df['year'] = df['date'].dt.year
        df['total'] = df['total'].astype(float)

        monthly = df.groupby('month')['total'].sum().reset_index()
        yearly = df.groupby('year')['total'].sum().reset_index()

        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("Gasto por mês")
            st.bar_chart(monthly.set_index('month'))
        with col2:
            st.subheader("Gasto por ano")
            yearly_display = yearly.copy()
            yearly_display["total"] = yearly_display["total"].apply(lambda x: f"{x:.2f} €")
            yearly_display.rename(columns={"year": "Ano", "total": "Total (€)"}, inplace=True)
            st.table(yearly_display)

        st.subheader("📄 Detalhe das faturas")
        df_sorted = df.sort_values('date', ascending=False).reset_index(drop=True)
        df_sorted["Comentário"] = df_sorted["total"].apply(
            lambda x: "Pago com saldo Cartão Continente" if x == 0 else ""
        )

        df_display = df_sorted.copy()
        df_display["Data"] = df_display["date"].dt.strftime("%d/%m/%Y")
        df_display["Valor (€)"] = df_display["total"].map(lambda x: f"{x:.2f}")
        df_display.rename(columns={"filename": "Ficheiro"}, inplace=True)
        df_display = df_display[["Data", "Valor (€)", "Ficheiro", "Comentário"]]

        st.dataframe(df_display, use_container_width=True)

        st.download_button("📥 Exportar CSV",
                           data=df_display.to_csv(index=False).encode('utf-8'),
                           file_name="faturas_continente.csv",
                           mime='text/csv')

# -----------------------
# Página: Eliminar Faturas
# -----------------------
with tab3:
    st.header("🗑️ Eliminar faturas")

    df = sqlite_fetch_all()
    if df.empty:
        st.info("Não há faturas registadas.")
    else:
        selected_filename = st.selectbox(
            "Escolhe o ficheiro a eliminar:",
            options=df["filename"].tolist()
        )
        if st.button("Eliminar fatura selecionada"):
            cur.execute("DELETE FROM receipts WHERE filename = ?", (selected_filename,))
            conn.commit()
            st.success(f"Fatura '{selected_filename}' eliminada com sucesso.")
            st.experimental_rerun()
