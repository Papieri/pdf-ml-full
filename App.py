import re
from io import BytesIO

import pandas as pd
import streamlit as st
import pdfplumber

st.set_page_config(page_title="Extrator SKU x Unidades", page_icon="📄", layout="centered")

st.title("📄 Extrator de SKU x UNIDADES (PDF → Planilha)")
st.write(
    "Envie um PDF no padrão de lista (com campos **SKU:** e coluna **UNIDADES**) "
    "para gerar uma planilha com **SKU** e **UNIDADES**."
)

SKU_REGEX = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)

def extract_skus_in_order(page_text):
    return [m.group(1).strip() for m in SKU_REGEX.finditer(page_text or "")]

def extract_units_after_header(page_text):
    if not page_text:
        return []

    upper = page_text.upper()
    idx = upper.rfind("PRODUTO UNIDADES")
    if idx == -1:
        idx = upper.rfind("UNIDADES")
        if idx == -1:
            return []

    tail = page_text[idx:]
    nums = re.findall(r"\b\d+\b", tail)
    return [int(n) for n in nums]

def parse_pdf(file_bytes):
    rows = []
    warnings = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            skus = extract_skus_in_order(text)
            units = extract_units_after_header(text)

            if not skus:
                continue

            if len(units) < len(skus):
                warnings.append(
                    f"Página {page_idx}: {len(skus)} SKU(s) e apenas {len(units)} unidade(s)."
                )
            elif len(units) > len(skus):
                units = units[: len(skus)]

            for i, sku in enumerate(skus):
                rows.append({
                    "page": page_idx,
                    "sku": sku,
                    "unidades": units[i] if i < len(units) else None
                })

    df = pd.DataFrame(rows)
    if df.empty:
        warnings.append("Não foi possível extrair dados do PDF.")

    return df, warnings

def to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return output.getvalue()

def to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")

uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded:
    df, warns = parse_pdf(uploaded.read())

    for w in warns:
        st.warning(w)

    if not df.empty:
        st.subheader("Pré-visualização")
        st.dataframe(df, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "⬇️ Baixar Excel (.xlsx)",
                data=to_excel_bytes(df),
                file_name="sku_unidades.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with col2:
            st.download_button(
                "⬇️ Baixar CSV (.csv)",
                data=to_csv_bytes(df),
                file_name="sku_unidades.csv",
                mime="text/csv",
            )
