import re
from io import BytesIO

import pandas as pd
import streamlit as st
import pdfplumber

st.set_page_config(page_title="Extrator SKU x UNIDADES", layout="centered")

st.title("📄 Extrator de SKU x UNIDADES")
st.write("Extrai **SKU** e **UNIDADES** mantendo a **ordem do PDF**.")

SKU_REGEX = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)

def parse_pdf(file_bytes):
    rows = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            lines = [l.strip() for l in text.splitlines() if l.strip()]

            current_sku = None

            for line in lines:
                # Captura SKU
                m = SKU_REGEX.search(line)
                if m:
                    current_sku = m.group(1)
                    continue

                # Captura UNIDADES (linha contendo apenas número)
                if current_sku and re.fullmatch(r"\d{1,4}", line):
                    rows.append({
                        "page": page_idx,
                        "sku": current_sku,
                        "unidades": int(line)
                    })
                    current_sku = None  # garante pareamento correto

    return pd.DataFrame(rows)

def to_excel(df):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return buffer.getvalue()

def to_csv(df):
    return df.to_csv(index=False).encode("utf-8")

uploaded = st.file_uploader("Envie o PDF", type="pdf")

if uploaded:
    df = parse_pdf(uploaded.read())

    if df.empty:
        st.error("Não foi possível extrair dados do PDF.")
    else:
        st.success("Dados extraídos com sucesso")
        st.dataframe(df, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "⬇️ Baixar Excel",
                data=to_excel(df),
                file_name="sku_unidades.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with col2:
            st.download_button(
                "⬇️ Baixar CSV",
                data=to_csv(df),
                file_name="sku_unidades.csv",
