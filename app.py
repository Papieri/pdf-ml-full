import re
from io import BytesIO
import pandas as pd
import streamlit as st
import pdfplumber

st.set_page_config(page_title="Extrator de SKU x UNIDADES", layout="centered")

st.title("📄 Extrator de SKU x UNIDADES")
st.caption("Extrai SKU e UNIDADES mantendo a ordem do PDF (layout tipo Mercado Livre/Fulfillment).")

# SKU real: deve ter pelo menos 1 letra e 1 número (evita pegar "3", "2", "360" etc.)
SKU_TOKEN_RE = re.compile(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+")
SKU_MARK_RE = re.compile(r"\bSKU:\b", re.IGNORECASE)

# Captura número curto (1–4 dígitos) logo após alguns rótulos
UNITS_AFTER_SKU_RE = re.compile(r"SKU:\s*([0-9]{1,4})\b", re.IGNORECASE)
UNITS_AFTER_UNIV_RE = re.compile(r"C[óo]digo\s+universal:\s*([0-9]{1,4})\b", re.IGNORECASE)

def looks_like_sku(tok: str) -> bool:
    if not tok:
        return False
    if not SKU_TOKEN_RE.fullmatch(tok):
        return False
    # filtros simples para evitar tokens “ruins” comuns
    bad = {"obrigatoria", "obrigatório", "obrigatoria.", "obrigatório."}
    return tok.lower() not in bad

def extract_first_sku_token(text: str) -> str | None:
    # pega o primeiro token alfanumérico que parece SKU real
    for tok in re.findall(r"[A-Za-z0-9]+", text or ""):
        if looks_like_sku(tok):
            return tok
    return None

def extract_units_candidate(line: str) -> int | None:
    """
    No seu PDF, por causa do texto extraído, as UNIDADES aparecem muitas vezes:
    - na mesma linha do "SKU:"  -> "SKU: 3 Etiquetagem"
    - ou na mesma linha do "Código universal:" -> "Código universal: 360 Etiquetagem"
    """
    m = UNITS_AFTER_SKU_RE.search(line or "")
    if m:
        return int(m.group(1))
    m = UNITS_AFTER_UNIV_RE.search(line or "")
    if m:
        return int(m.group(1))
    return None

def parse_ml_style_pdf(file_bytes: bytes) -> tuple[pd.DataFrame, dict]:
    """
    Parser por estado (state machine) para manter ordem e casar SKU ↔ UNIDADES mesmo com colunas embaralhadas.
    Estratégia por item:
      - Encontrou "SKU:" => inicia bloco do produto
      - Captura UNIDADES candidata na mesma linha (se houver)
      - Procura SKU real:
          a) na mesma linha após "SKU:"
          b) senão na próxima(s) linha(s), primeiro token válido
      - Se achou SKU mas não achou UNIDADES ainda, tenta usar a última unidade vista (se for plausível)
    """
    rows = []
    diag = {
        "pages": 0,
        "found_pairs": 0,
        "pending_without_units": 0,
        "pending_without_sku": 0,
        "notes": [],
    }

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        diag["pages"] = len(pdf.pages)

        # Estado
        waiting_for_sku_code = False
        pending_units: int | None = None

        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue

            lines = [l.strip() for l in text.splitlines() if l.strip()]

            for line in lines:
                # 1) Atualiza "unidades candidata" se apareceu em alguma linha (SKU: 3... ou Código universal: 360...)
                units_candidate = extract_units_candidate(line)
                if units_candidate is not None:
                    pending_units = units_candidate

                # 2) Quando aparece "SKU:" inicia bloco do produto
                if SKU_MARK_RE.search(line):
                    waiting_for_sku_code = True

                    # 2a) tenta achar SKU real na própria linha (às vezes vem junto)
                    # Ex.: "SKU: CX81X20"
                    parts = re.split(r"SKU:\s*", line, flags=re.IGNORECASE, maxsplit=1)
                    if len(parts) == 2:
                        tail = parts[1]
                        sku_inline = extract_first_sku_token(tail)
                        if sku_inline:
                            rows.append({"page": page_idx, "sku": sku_inline, "unidades": pending_units})
                            diag["found_pairs"] += 1
                            pending_units = None
                            waiting_for_sku_code = False

                    continue  # fim do tratamento desta linha

                # 3) Se estamos esperando o SKU real (normalmente vem na linha seguinte)
                if waiting_for_sku_code:
                    sku_next = extract_first_sku_token(line)
                    if sku_next:
                        rows.append({"page": page_idx, "sku": sku_next, "unidades": pending_units})
                        diag["found_pairs"] += 1
                        pending_units = None
                        waiting_for_sku_code = False

        # Diagnóstico pós-loop
        if waiting_for_sku_code:
            diag["pending_without_sku"] += 1
            diag["notes"].append("Terminou o arquivo ainda aguardando um SKU após 'SKU:' (provável quebra no texto do PDF).")

    df = pd.DataFrame(rows)

    # Se houver unidades vazias, registra diagnóstico
    if not df.empty:
        missing_units = int(df["unidades"].isna().sum())
        if missing_units:
            diag["pending_without_units"] = missing_units
            diag["notes"].append(
                f"{missing_units} linha(s) ficaram sem UNIDADES. Pode ser variação de layout/extração do PDF."
            )

    return df, diag

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SKU_UNIDADES")
    return buf.getvalue()

uploaded = st.file_uploader("Envie o PDF", type=["pdf"])

if uploaded is not None:
    df, diag = parse_ml_style_pdf(uploaded.read())

    if df.empty:
        st.error("Não consegui extrair pares SKU x UNIDADES deste PDF.")
        st.write("Diagnóstico:", diag)
    else:
        # Mantém ordem natural de extração (NÃO ordenar)
        df = df.reset_index(drop=True)

        st.success(f"Extração concluída: {len(df)} itens (ordem do PDF preservada).")
        with st.expander("Diagnóstico"):
            st.json(diag)

        st.dataframe(df, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="⬇️ Baixar Excel (.xlsx)",
                data=df_to_excel_bytes(df),
                file_name="sku_unidades.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with col2:
            st.download_button(
                label="⬇️ Baixar CSV (.csv)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="sku_unidades.csv",
                mime="text/csv",
            )
