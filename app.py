import re
from io import BytesIO

import pandas as pd
import streamlit as st
import pdfplumber

st.set_page_config(page_title="Extrator SKU x UNIDADES", layout="centered")
st.title("📄 Extrator de SKU x UNIDADES")
st.write("Extrai **SKU** e **UNIDADES** mantendo a **ordem do PDF**.")

SKU_REGEX = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)


def parse_pdf(file_bytes: bytes) -> pd.DataFrame:
    rows = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            current_sku = None

            for line in lines:
                m = SKU_REGEX.search(line)
                if m:
                    current_sku = m.group(1).strip()
                    continue

                if current_sku and re.fullmatch(r"\d{1,4}", line):
                    rows.append({"page": page_idx, "sku": current_sku, "unidades": int(line)})
                    current_sku = None

    return pd.DataFrame(rows)


def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return buf.getvalue()


uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded is not None:
    df = parse_pdf(uploaded.read())

    if df.empty:
        st.error("Não foi possível extrair dados. Verifique se o PDF tem texto selecionável (não é imagem/scan).")
    else:
        st.success("Dados extraídos com sucesso.")
        st.dataframe(df, use_container_width=True)

        st.download_button(
            label="⬇️ Baixar Excel (.xlsx)",
            data=df_to_excel_bytes(df),
            file_name="sku_unidades.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.download_button(
            label="⬇️ Baixar CSV (.csv)",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="sku_unidades.csv",
            mime="text/csv",
        )
