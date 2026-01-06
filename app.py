import re
from io import BytesIO

import pandas as pd
import streamlit as st
import pdfplumber

st.set_page_config(page_title="Extrator de SKU x UNIDADES", layout="centered")
st.title("📄 Extrator de SKU x UNIDADES")
st.caption("Extrai SKU (1ª coluna) e UNIDADES (2ª coluna) mantendo a ordem do PDF.")

SKU_RE = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)

def extract_units_from_tail(page_text: str) -> list[int]:
    """
    UNIDADES aparecem no rodapé após 'PRODUTO UNIDADES ...'.
    Extrai números na ordem, aceitando linhas tipo '12 • Embale ...'.
    """
    if not page_text:
        return []

    up = page_text.upper()
    idx = up.rfind("PRODUTO UNIDADES")
    if idx == -1:
        return []

    tail = page_text[idx:]
    units: list[int] = []

    for line in tail.splitlines():
        s = line.strip()
        if not s:
            continue

        # Caso venha uma linha com vários números (ex: "3 2 360")
        if re.fullmatch(r"(?:\d{1,4}\s+)+\d{1,4}", s):
            units.extend([int(x) for x in s.split()])
            continue

        # Caso padrão: pega o primeiro número no começo da linha (ex: "12 • Embale...")
        m = re.match(r"^(\d{1,4})\b", s)
        if m:
            units.append(int(m.group(1)))

    return units

def parse_pdf(file_bytes: bytes) -> tuple[pd.DataFrame, dict]:
    rows = []
    diag = {"pages": 0, "pairs": 0, "mismatch_pages": []}

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        diag["pages"] = len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            # 1) SKUs em ordem (regex pega mesmo quando o SKU está na linha seguinte)
            skus = [m.group(1).strip() for m in SKU_RE.finditer(text)]

            # 2) UNIDADES em ordem (após o cabeçalho)
            units = extract_units_from_tail(text)

            # 3) pareamento por posição
            m = min(len(skus), len(units))
            for i in range(m):
                rows.append({"sku": skus[i], "unidades": units[i]})

            if len(skus) != len(units):
                diag["mismatch_pages"].append(
                    {"page": page_idx, "skus": len(skus), "units": len(units)}
                )

    df = pd.DataFrame(rows)
    diag["pairs"] = len(df)
    return df, diag

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return buf.getvalue()

uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded is not None:
    df, diag = parse_pdf(uploaded.read())

    if df.empty:
        st.error("Não consegui extrair SKU x UNIDADES deste PDF.")
        st.write("Diagnóstico:", diag)
    else:
        st.success(f"Extração OK: {len(df)} linhas (ordem do PDF preservada).")

        # Mostra diagnóstico se houver páginas com contagem diferente
        if diag["mismatch_pages"]:
            with st.expander("Diagnóstico (páginas com divergência)"):
                st.json(diag)

        st.dataframe(df, use_container_width=True)

        st.download_button(
            "⬇️ Baixar Excel (.xlsx)",
            data=df_to_excel_bytes(df),
            file_name="sku_unidades.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.download_button(
            "⬇️ Baixar CSV (.csv)",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="sku_unidades.csv",
            mime="text/csv",
        )
