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

    def is_sku_token(tok: str) -> bool:
        # SKU precisa ter pelo menos 1 letra e 1 número (evita pegar "3", "2", etc.)
        return bool(re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+", tok))

    def extract_short_int_after(label: str, line: str):
        """
        Pega número curto (1-4 dígitos) após um label. Ex:
        'SKU: 3 Etiquetagem' -> 3
        'Código universal: 360 Etiquetagem' -> 360
        """
        m = re.search(label + r"\s*([0-9]{1,4})\b", line, flags=re.IGNORECASE)
        return int(m.group(1)) if m else None

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            pending_units = None        # unidade associada ao próximo SKU
            waiting_sku_code = False    # estamos esperando encontrar o SKU real

            for line in lines:
                # 1) Às vezes a UNIDADE aparece colada em "Código universal:" (número curto)
                u_from_universal = extract_short_int_after(r"C[óo]digo\s+universal:\s*", line)
                if u_from_universal is not None:
                    pending_units = u_from_universal

                # 2) Detectou "SKU:" -> começa um bloco de produto
                if re.search(r"\bSKU:\b", line, flags=re.IGNORECASE):
                    waiting_sku_code = True

                    # 2a) Se vier "SKU: 3 ..." pega essa unidade
                    u_from_sku = extract_short_int_after(r"SKU:\s*", line)
                    if u_from_sku is not None:
                        pending_units = u_from_sku

                    # 2b) Às vezes o SKU real vem na mesma linha após "SKU:"
                    after = re.split(r"SKU:\s*", line, flags=re.IGNORECASE, maxsplit=1)
                    if len(after) == 2:
                        tail = after[1]
                        # pega tokens e procura o primeiro que parece SKU real
                        for tok in re.findall(r"[A-Za-z0-9]+", tail):
                            if is_sku_token(tok) and tok.lower() not in {"obrigatoria", "obrigatório"}:
                                rows.append({"page": page_idx, "sku": tok, "unidades": pending_units})
                                pending_units = None
                                waiting_sku_code = False
                                break

                    continue  # já tratou esta linha

                # 3) Se estamos esperando SKU real, ele costuma vir na linha seguinte (ex: "CX81X20 obrigatória")
                if waiting_sku_code:
                    # primeiro token alfanumérico da linha
                    toks = re.findall(r"[A-Za-z0-9]+", line)
                    if toks:
                        tok0 = toks[0]
                        if is_sku_token(tok0):
                            rows.append({"page": page_idx, "sku": tok0, "unidades": pending_units})
                            pending_units = None
                            waiting_sku_code = False

    return pd.DataFrame(rows)

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
