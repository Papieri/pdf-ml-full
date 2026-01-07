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

SKU_TOKEN_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+$")

def extract_skus_from_page(page) -> list[str]:
    """
    Extrai SKUs na ordem visual da página usando extract_words.
    Regra: após 'SKU' ou 'SKU:' pegar o próximo token que contenha letra+numero.
    Se vier 'SKU: 3', ignora '3' e continua até achar 'CX81X20'.
    """
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    if not words:
        return []

    # Ordena de cima pra baixo, esquerda pra direita (ordem do documento)
    words.sort(key=lambda w: (float(w["top"]), float(w["x0"])))

    skus = []
    pending = False
    lookahead = 0

    for w in words:
        t = (w.get("text") or "").strip()
        if not t:
            continue

        upper = t.upper()

        # Detecta o marcador SKU
        if upper in ("SKU", "SKU:") or upper.startswith("SKU:"):
            pending = True
            lookahead = 0
            continue

        if pending:
            lookahead += 1

            # para não “viajar” demais (caso não encontre SKU perto)
            if lookahead > 20:
                pending = False
                continue

            # ignora tokens numéricos (são as UNIDADES ou outros números)
            if t.isdigit():
                continue

            # aceita somente SKU com letra+numero
            if SKU_TOKEN_RE.match(t):
                skus.append(t)
                pending = False

    return skus

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

def extract_units_by_column(page) -> list[int]:
    """
    Pega UNIDADES usando coordenadas: encontra o cabeçalho 'UNIDADES' e coleta
    números (1–4 dígitos) na mesma faixa X abaixo do cabeçalho, ordenados por Y.
    """
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    if not words:
        return []

    # acha a palavra UNIDADES no cabeçalho
    header = None
    for w in words:
        if (w.get("text") or "").strip().upper() == "UNIDADES":
            header = w
            break
    if header is None:
        return []

    x0 = float(header["x0"])
    x1 = float(header["x1"])
    header_bottom = float(header["bottom"])

    # tolerância para pegar números alinhados na coluna (varia conforme fonte/layout)
    pad_left = 25.0
    pad_right = 40.0
    xmin = x0 - pad_left
    xmax = x1 + pad_right

    candidates = []
    for w in words:
        t = (w.get("text") or "").strip()
        if not t.isdigit():
            continue
        if len(t) > 4:
            continue

        wx0 = float(w["x0"])
        wx1 = float(w["x1"])
        wtop = float(w["top"])
        wbottom = float(w["bottom"])

        # abaixo do cabeçalho e dentro da faixa X da coluna
        if wbottom > header_bottom and wx0 >= xmin and wx1 <= xmax:
            candidates.append((wtop, wx0, int(t)))

    # ordena na ordem visual (de cima pra baixo)
    candidates.sort(key=lambda a: (a[0], a[1]))
    return [u for _, __, u in candidates]

def pdf_to_pairs(file_bytes: bytes) -> Tuple[List[Tuple[str, int]], Dict[str, Any]]:
    pairs: List[Tuple[str, int]] = []
    diag: Dict[str, Any] = {"pages": 0, "per_page": []}

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        diag["pages"] = len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            skus = extract_skus_from_page(page)
            units = extract_units_by_column(page)
            if not units:
            # fallback pro método antigo se por algum motivo não achar a coluna
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
