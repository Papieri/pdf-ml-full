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

    def extract_units_from_tail(page_text: str) -> list[int]:
        if not page_text:
            return []

        up = page_text.upper()
        idx = up.rfind("PRODUTO UNIDADES")
        if idx == -1:
            # fallback: tenta achar pelo menos "UNIDADES"
            idx = up.rfind("UNIDADES")
            if idx == -1:
                return []

        tail = page_text[idx:]

        units = []
        for line in tail.splitlines():
            s = line.strip()

            # pega linhas que são APENAS números (1 a 4 dígitos) => evita código universal e números de descrição
            if re.fullmatch(r"\d{1,4}", s):
                units.append(int(s))
                continue

            # também aceita linha com "números separados por espaço" e nada mais (ex: "3 2 360")
            if s and re.fullmatch(r"(?:\d{1,4}\s+)+\d{1,4}", s):
                units.extend([int(x) for x in s.split()])

        return units

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            # SKUs na ordem em que aparecem na página
            skus = [m.group(1).strip() for m in SKU_REGEX.finditer(text)]
            if not skus:
                continue

            # UNIDADES extraídas do trecho do rodapé/tabela
            units = extract_units_from_tail(text)

            # pareamento por posição (mantém ordem do PDF)
            for i, sku in enumerate(skus):
                unidade = units[i] if i < len(units) else None
                rows.append({"page": page_idx, "sku": sku, "unidades": unidade})

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
