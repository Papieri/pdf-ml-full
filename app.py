import re
from io import BytesIO
from typing import List, Tuple

import pandas as pd
import streamlit as st
import pdfplumber


st.set_page_config(page_title="PDF → SKU x UNIDADES", layout="centered")
st.title("📄 PDF → Markdown → Planilha (SKU x UNIDADES)")
st.caption("O app gera um Markdown interno a partir do PDF e converte para CSV/XLSX.")


# -----------------------------
# PDF parsing (gera os pares na ordem)
# -----------------------------
SKU_RE = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)

def extract_units_from_tail(page_text: str) -> list[int]:
    """
    Extrai UNIDADES do trecho após o cabeçalho 'PRODUTO UNIDADES' (com regex flexível).
    - Aceita 'PRODUTO  UNIDADES', 'PRODUTO\\nUNIDADES', etc.
    - Extrai números (1-4 dígitos) no início da linha (mesmo que venha '12 • ...')
    - Ou linhas com vários números '3 2 360'
    """
    if not page_text:
        return []

    # acha a ÚLTIMA ocorrência do cabeçalho (mais seguro)
    header_pat = re.compile(r"PRODUTO\s+UNIDADES", re.IGNORECASE)
    matches = list(header_pat.finditer(page_text))
    if not matches:
        return []

    idx = matches[-1].start()
    tail = page_text[idx:]

    units: list[int] = []

    for line in tail.splitlines():
        s = line.strip()
        if not s:
            continue

        # linha com vários números (ex: "3 2 360")
        if re.fullmatch(r"(?:\d{1,4}\s+)+\d{1,4}", s):
            units.extend([int(x) for x in s.split()])
            continue

        # número no começo da linha (ex: "12 • Embale ...")
        m = re.match(r"^(\d{1,4})\b", s)
        if m:
            units.append(int(m.group(1)))

    return units

def pdf_to_pairs(file_bytes: bytes) -> tuple[list[tuple[str, int]], dict]:
    pairs: list[tuple[str, int]] = []
    diag = {"pages": 0, "per_page": []}

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        diag["pages"] = len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            # SKUs em ordem
            skus = [m.group(1).strip() for m in SKU_RE.finditer(text)]

            # UNIDADES em ordem
            units = extract_units_from_tail(text)

            # fallback: se não achou nada por cabeçalho, tenta pegar números soltos no final (1–4 dígitos)
            # (ajuda quando o cabeçalho vem “muito torto”)
            if not units and skus:
                tail_nums = re.findall(r"\b\d{1,4}\b", text)
                units = [int(x) for x in tail_nums[-len(skus):]] if len(tail_nums) >= 1 else []

            # Se vier unidades a mais, corta; se vier a menos, preenche com None (para você ver onde falhou)
            m = min(len(skus), len(units))
            for i in range(m):
                pairs.append((skus[i], units[i]))

            diag["per_page"].append({
                "page": page_idx,
                "skus": len(skus),
                "units": len(units),
                "paired": m
            })

    return pairs, diag

# -----------------------------
# Markdown (gerar e "executar")
# -----------------------------
def pairs_to_markdown(pairs: List[Tuple[str, int]]) -> str:
    lines = []
    lines.append("| SKU | UNIDADES |")
    lines.append("|---|---:|")
    for sku, unidades in pairs:
        lines.append(f"| {sku} | {unidades} |")
    return "\n".join(lines)

def markdown_to_df(md: str) -> pd.DataFrame:
    """
    Converte tabela Markdown simples:
    | SKU | UNIDADES |
    |---|---:|
    | CX81X20 | 3 |
    """
    if not md.strip():
        return pd.DataFrame(columns=["SKU", "UNIDADES"])

    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    table_lines = [ln for ln in lines if ln.startswith("|") and ln.endswith("|")]
    if len(table_lines) < 2:
        return pd.DataFrame(columns=["SKU", "UNIDADES"])

    # remove linha separadora
    def is_sep(ln: str) -> bool:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        return all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells)

    header = None
    rows = []
    for ln in table_lines:
        if is_sep(ln):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if header is None:
            header = [h.upper() for h in cells]
        else:
            rows.append(cells)

    if not header:
        return pd.DataFrame(columns=["SKU", "UNIDADES"])

    sku_i = header.index("SKU") if "SKU" in header else None
    uni_i = header.index("UNIDADES") if "UNIDADES" in header else None
    if sku_i is None or uni_i is None:
        return pd.DataFrame(columns=["SKU", "UNIDADES"])

    out = []
    for r in rows:
        if max(sku_i, uni_i) >= len(r):
            continue
        sku = r[sku_i].strip()
        m = re.search(r"\d+", r[uni_i])
        unidades = int(m.group(0)) if m else None
        if sku:
            out.append({"SKU": sku, "UNIDADES": unidades})

    return pd.DataFrame(out)


# -----------------------------
# Export
# -----------------------------
def df_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return buf.getvalue()


# -----------------------------
# UI
# -----------------------------
uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded is not None:
    pairs, diag = pdf_to_pairs(uploaded.read())

    if not pairs:
        st.error("Não consegui extrair SKU x UNIDADES desse PDF.")
        st.write("Diagnóstico:", diag)
    else:
        # 1) Gera markdown interno
        md = pairs_to_markdown(pairs)

        # 2) Converte markdown em dataframe (jeito 02)
        df = markdown_to_df(md)

        st.success(f"OK: {len(df)} linhas geradas (ordem preservada).")

        # Mostra markdown para contra-prova (opcional)
        with st.expander("Ver Markdown gerado (contra-prova)"):
            st.code(md, language="markdown")

        # Mostra tabela final
        st.dataframe(df, use_container_width=True)

        # Diagnóstico de divergência de contagem por página
        if diag.get("mismatch_pages"):
            with st.expander("Diagnóstico (páginas com contagem diferente)"):
                st.json(diag)

        st.download_button(
            "⬇️ Baixar CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="sku_unidades.csv",
            mime="text/csv",
        )

        st.download_button(
            "⬇️ Baixar XLSX",
            data=df_to_xlsx_bytes(df),
            file_name="sku_unidades.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
