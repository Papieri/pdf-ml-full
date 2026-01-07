import re
from io import BytesIO
from typing import List, Tuple, Dict, Any

import streamlit as st
import pdfplumber


st.set_page_config(page_title="PDF → Markdown (SKU x UNIDADES)", layout="centered")
st.title("📄 PDF → Markdown (SKU x UNIDADES)")
st.caption("Envie o PDF e copie o Markdown gerado (SKU e UNIDADES na ordem do documento).")

# SKU padrão do documento
SKU_RE = re.compile(r"SKU:\s*([A-Za-z0-9]+)", re.IGNORECASE)

# Cabeçalho flexível (aceita espaços e quebras de linha)
HEADER_RE = re.compile(r"PRODUTO\s+UNIDADES", re.IGNORECASE)


def extract_skus(page_text: str) -> List[str]:
    return [m.group(1).strip() for m in SKU_RE.finditer(page_text or "")]


def extract_units_from_tail(page_text: str) -> List[int]:
    """
    Pega UNIDADES do bloco após o cabeçalho 'PRODUTO UNIDADES' (flexível).
    Extrai números na ordem:
      - linhas com vários números: '3 2 360'
      - linhas começando com número: '12 • Embale ...'
    """
    if not page_text:
        return []

    matches = list(HEADER_RE.finditer(page_text))
    if not matches:
        return []

    # pega a ÚLTIMA ocorrência na página (mais seguro)
    idx = matches[-1].start()
    tail = page_text[idx:]

    units: List[int] = []
    for line in tail.splitlines():
        s = line.strip()
        if not s:
            continue

        # Caso: vários números na mesma linha (ex.: "3 2 360")
        if re.fullmatch(r"(?:\d{1,4}\s+)+\d{1,4}", s):
            units.extend([int(x) for x in s.split()])
            continue

        # Caso: começa com número e depois vem texto (ex.: "12 • Embale ...")
        m = re.match(r"^(\d{1,4})\b", s)
        if m:
            units.append(int(m.group(1)))

    return units


def pdf_to_pairs(file_bytes: bytes) -> Tuple[List[Tuple[str, int]], Dict[str, Any]]:
    pairs: List[Tuple[str, int]] = []
    diag: Dict[str, Any] = {"pages": 0, "per_page": []}

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        diag["pages"] = len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            skus = extract_skus(text)
            units = extract_units_from_tail(text)

            paired = min(len(skus), len(units))
            for i in range(paired):
                pairs.append((skus[i], units[i]))

            diag["per_page"].append(
                {"page": page_idx, "skus": len(skus), "units": len(units), "paired": paired}
            )

    return pairs, diag


def pairs_to_markdown(pairs: List[Tuple[str, int]]) -> str:
    lines = ["| SKU | UNIDADES |", "|---|---:|"]
    for sku, unidades in pairs:
        lines.append(f"| {sku} | {unidades} |")
    return "\n".join(lines)


uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded is not None:
    pairs, diag = pdf_to_pairs(uploaded.read())

    if not pairs:
        st.error("Não consegui gerar o Markdown. (Nenhum par SKU x UNIDADES encontrado.)")
        with st.expander("Diagnóstico por página"):
            st.json(diag)
    else:
        md = pairs_to_markdown(pairs)

        st.success(f"Markdown gerado com {len(pairs)} linha(s).")
        st.text_area("Markdown (copie e cole)", md, height=360)

        # Se não bateu em alguma página, te mostra exatamente onde
        mismatches = [d for d in diag["per_page"] if d["skus"] != d["units"]]
        if mismatches:
            st.warning("Algumas páginas tiveram contagens diferentes (SKU vs UNIDADES). Veja o diagnóstico.")
            with st.expander("Diagnóstico por página"):
                st.json(diag)
