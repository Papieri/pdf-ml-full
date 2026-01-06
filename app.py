import re
from io import BytesIO

import pandas as pd
import streamlit as st
import pdfplumber

st.set_page_config(page_title="Extrator SKU x Unidades", page_icon="📄", layout="centered")

st.title("📄 Extrator de SKU x UNIDADES (PDF → Planilha)")
st.write("Envie um PDF para extrair **SKU** e **UNIDADES** na ordem em que aparecem no documento.")

SKU_REGEX = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)

def parse_int(value):
    """Extrai inteiro de um texto (ex.: ' 3 ' -> 3). Retorna None se não achar."""
    if value is None:
        return None
    s = str(value).strip()
    m = re.search(r"\b(\d+)\b", s)
    return int(m.group(1)) if m else None

def extract_from_tables(pdf: pdfplumber.PDF):
    """
    Extrai preservando a ordem do PDF via tabelas:
    - SKU vem da coluna PRODUTO (contém 'SKU: ...')
    - UNIDADES vem da coluna UNIDADES
    """
    rows = []
    warnings = []

        table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
    }

    for page_idx, page in enumerate(pdf.pages, start=1):
        try:
            tables = page.extract_tables(table_settings=table_settings) or []
        except Exception as e:
            warnings.append(f"Página {page_idx}: erro lendo tabela ({type(e).__name__}). Vou usar fallback por texto.")
            tables = []

    for page_idx, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables(table_settings=table_settings) or []
        if not tables:
            warnings.append(f"Página {page_idx}: não consegui ler tabela (vou tentar fallback por texto).")
            continue

        for table in tables:
            if not table or len(table) < 2:
                continue

            # Detecta header (primeira linha) e tenta localizar colunas
            header = [("" if c is None else str(c)).strip().upper() for c in table[0]]

            # Normalmente: PRODUTO | UNIDADES | IDENTIFICAÇÃO | ...
            try:
                produto_col = header.index("PRODUTO")
            except ValueError:
                produto_col = 0  # fallback

            # UNIDADES pode vir com espaços/variações; tenta achar por contains
            unidades_col = None
            for i, h in enumerate(header):
                if "UNIDADE" in h:
                    unidades_col = i
                    break
            if unidades_col is None:
                unidades_col = 1  # fallback comum

            # Percorre linhas mantendo ordem
            for r in table[1:]:
                if not r or len(r) <= max(produto_col, unidades_col):
                    continue

                produto_cell = r[produto_col]
                unidades_cell = r[unidades_col]

                if produto_cell is None:
                    continue

                produto_text = str(produto_cell)

                msku = SKU_REGEX.search(produto_text)
                if not msku:
                    continue

                sku = msku.group(1).strip()
                unidades = parse_int(unidades_cell)

                rows.append({"page": page_idx, "sku": sku, "unidades": unidades})

    return pd.DataFrame(rows), warnings

def extract_fallback_text(pdf: pdfplumber.PDF):
    """
    Fallback: por texto, mas com pareamento por ocorrência de SKU e a UNIDADE
    mais próxima na mesma seção de tabela, reduzindo contaminação.
    Só entra se a extração por tabela falhar.
    """
    rows = []
    warnings = []

    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        if not text:
            continue

        # Divide a partir do cabeçalho para pegar a parte "tabela"
        up = text.upper()
        cut = up.find("PRODUTO")
        table_text = text[cut:] if cut != -1 else text

        # Captura SKUs na ordem
        skus = [m.group(1).strip() for m in SKU_REGEX.finditer(table_text)]
        if not skus:
            continue

        # Captura candidatos a unidades: números isolados em linhas mais “curtas”
        # (tenta evitar pegar códigos universais grandes e descrições)
        candidates = []
        for line in table_text.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            # linha com apenas número (ou quase)
            if re.fullmatch(r"\d{1,4}", line_stripped):
                candidates.append(int(line_stripped))

        if len(candidates) < len(skus):
            warnings.append(
                f"Página {page_idx} (fallback): {len(skus)} SKU(s), {len(candidates)} unidade(s)."
            )

        for i, sku in enumerate(skus):
            unidades = candidates[i] if i < len(candidates) else None
            rows.append({"page": page_idx, "sku": sku, "unidades": unidades})

    return pd.DataFrame(rows), warnings

def parse_pdf(file_bytes: bytes):
    warns = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        df, w1 = extract_from_tables(pdf)
        warns += w1

        # Se falhou (vazio ou muitas unidades None), usa fallback
        if df.empty or df["unidades"].isna().mean() > 0.5:
            df2, w2 = extract_fallback_text(pdf)
            warns += w2
            if not df2.empty:
                df = df2

    if df.empty:
        warns.append("Não consegui extrair dados. Verifique se o PDF é texto (não imagem/scan).")

    # IMPORTANTÍSSIMO: NÃO ordena por SKU (mantém ordem do PDF)
    df = df.reset_index(drop=True)
    return df, warns

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return output.getvalue()

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded:
    df, warns = parse_pdf(uploaded.read())

    for w in warns:
        st.warning(w)

    if not df.empty:
        st.subheader("Pré-visualização (na ordem do PDF)")
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
