import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from datetime import datetime

st.title("🧾 Faturas Continente Tracker")

# Base de dados local (podes depois ligar ao Google Sheets)
if "data" not in st.session_state:
    st.session_state.data = pd.DataFrame(columns=["Data", "Valor (€)"])

uploaded_files = st.file_uploader("Envia as faturas PDF do Continente", accept_multiple_files=True, type="pdf")

for uploaded_file in uploaded_files:
    with pdfplumber.open(uploaded_file) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text()

        # Extrai o valor total
        match_valor = re.search(r"Total a pagar\s*([\d,]+)", text)
        match_data = re.search(r"(\d{2}/\d{2}/\d{4})", text)

        if match_valor and match_data:
            valor = float(match_valor.group(1).replace(",", "."))
            data = datetime.strptime(match_data.group(1), "%d/%m/%Y")
            st.session_state.data.loc[len(st.session_state.data)] = [data, valor]

if not st.session_state.data.empty:
    df = st.session_state.data.sort_values("Data")
    df["Mês"] = df["Data"].dt.strftime("%B")
    df["Ano"] = df["Data"].dt.year

    total_mensal = df.groupby("Mês")["Valor (€)"].sum().reset_index()
    total_anual = df["Valor (€)"].sum()

    st.subheader("Resumo")
    st.write(f"💶 Total anual: **{total_anual:.2f} €**")
    st.bar_chart(total_mensal.set_index("Mês"))

    st.download_button("📥 Exportar CSV", data=df.to_csv(index=False), file_name="faturas_continente.csv")
