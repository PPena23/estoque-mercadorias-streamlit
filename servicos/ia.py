"""Integração com o Gemini (SDK google-genai).

Dois usos, ambos com SAÍDA ESTRUTURADA (response_schema com Pydantic):
1. extrair_nota(): lê o texto colado de uma nota fiscal/pedido e devolve
   fornecedor, número, data e itens em JSON validado.
2. resumo_inteligente(): recebe só números já agregados pelo pandas e
   devolve de 3 a 5 observações em texto.

A IA nunca calcula saldo nem valor de estoque: ela transforma texto em
dados (extração) e dados em texto (resumo). As contas ficam no pandas/SQL.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd
import streamlit as st
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

# ------------------------------------------------------------------ chave e cliente


def ler_chave() -> str | None:
    """Procura GEMINI_API_KEY em .streamlit/secrets.toml e depois no ambiente."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:  # secrets.toml não existe
        pass
    return os.environ.get("GEMINI_API_KEY")


@st.cache_resource
def cliente(chave: str) -> genai.Client:
    return genai.Client(api_key=chave)


@st.cache_data(ttl=3600, show_spinner=False)
def modelos_disponiveis(chave: str) -> list[str]:
    """Lista os modelos "flash" liberados para a chave (na ordem de ordem_modelo).
    Evita fixar um nome que pode ser aposentado."""
    nomes = [m.name.removeprefix("models/") for m in cliente(chave).models.list()
             if "generateContent" in (m.supported_actions or []) and "flash" in m.name
             and not any(x in m.name for x in ("image", "tts", "audio", "live"))]
    return sorted(nomes, key=ordem_modelo)


def ordem_modelo(nome: str) -> tuple:
    """Aliases "-latest" primeiro (sempre apontam para a versão atual), depois
    Flash-Lite (mais rápido e com mais cota grátis), versões mais novas antes e previews por último. Versões antigas
    podem continuar listadas mas recusar chaves novas."""
    versao = re.search(r"(\d+(?:\.\d+)?)", nome)
    return ("latest" not in nome, "lite" not in nome, "preview" in nome,
            -float(versao.group(1)) if versao else 0.0, nome)


def mensagem_erro(e: errors.APIError) -> str:
    if e.code == 429:
        return "A cota gratuita do Gemini acabou por agora. Tente mais tarde ou troque de modelo."
    if e.code in (400, 401, 403):
        return f"O Gemini recusou a chamada ({e.code}). Confira se a chave está correta."
    return f"Erro ao consultar o Gemini ({e.code}): {e.message}"


# ------------------------------------------------------------------ esquemas

class ItemNota(BaseModel):
    descricao: str = Field(description="Descrição do produto exatamente como no documento")
    quantidade: float = Field(description="Quantidade comprada, na unidade do documento")
    unidade: str = Field(description="Unidade normalizada: un, cx, kg ou L")
    custo_unitario: float = Field(description="Valor unitário em reais, sem impostos destacados")
    lote: str | None = Field(None, description="Código do lote, se houver")
    validade: str | None = Field(None, description="Data de validade no formato AAAA-MM-DD, se houver")


class NotaExtraida(BaseModel):
    fornecedor: str = Field(description="Razão social ou nome fantasia do emitente")
    numero: str = Field(description="Número da nota ou do pedido, só dígitos e letras")
    data_emissao: str = Field(description="Data de emissão no formato AAAA-MM-DD")
    itens: list[ItemNota]


class Resumo(BaseModel):
    observacoes: list[str] = Field(description="De 3 a 5 observações curtas e acionáveis")


INSTRUCOES_EXTRACAO = """Você extrai dados de notas fiscais e pedidos de compra brasileiros.
Regras:
- Copie a descrição de cada item como está no texto; não traduza nem invente produtos.
- Datas no formato AAAA-MM-DD. Números com ponto decimal (1.234,50 vira 1234.5).
- Unidade: use "cx" para caixa/fardo/pacote fechado, "kg" para quilo, "L" para litro
  e "un" para unidade/peça/pacote avulso.
- custo_unitario é o valor unitário do item. Se só houver o total, divida pela quantidade.
- Se lote ou validade não aparecerem, deixe nulo. Nunca invente valores ausentes.
- Ignore frete, impostos, totais da nota e dados de transporte."""

INSTRUCOES_RESUMO = """Você é analista de estoque de uma distribuidora de alimentos (dados fictícios).
Recebe APENAS números já calculados. Escreva de 3 a 5 observações em português do Brasil,
cada uma com no máximo 2 frases, citando os números recebidos (em R$ no formato 1.234,56)
e terminando com uma ação prática. Não faça contas novas além de variações percentuais
simples entre período atual e anterior, e não invente dados que não estejam no JSON."""


# ------------------------------------------------------------------ chamadas

def gerar(chave: str, modelo: str, contents: str, config: types.GenerateContentConfig):
    """Chama o modelo escolhido. Se ele estiver sobrecarregado (503), fora do ar
    (500) ou aposentado (404), tenta os próximos modelos disponíveis."""
    alternativos = [m for m in modelos_disponiveis(chave) if m != modelo][:2]
    candidatos = [modelo] + alternativos
    for i, nome in enumerate(candidatos):
        try:
            return cliente(chave).models.generate_content(
                model=nome, contents=contents, config=config)
        except errors.APIError as e:
            if e.code not in (404, 500, 503) or i == len(candidatos) - 1:
                raise


def extrair_nota(chave: str, modelo: str, texto: str) -> NotaExtraida:
    resposta = gerar(
        chave, modelo,
        contents=texto,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCOES_EXTRACAO,
            response_mime_type="application/json",
            response_schema=NotaExtraida,
            temperature=0,
        ),
    )
    if isinstance(resposta.parsed, NotaExtraida):
        return resposta.parsed
    return NotaExtraida.model_validate_json(resposta.text)  # validação extra


@st.cache_data(ttl=1800, show_spinner=False)
def resumo_inteligente(chave: str, modelo: str, agregados_json: str) -> list[str]:
    """Cacheado pelo conteúdo: mesmos números = mesma resposta, sem gastar cota."""
    resposta = gerar(
        chave, modelo,
        contents=f"Indicadores do estoque (JSON):\n{agregados_json}",
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCOES_RESUMO,
            response_mime_type="application/json",
            response_schema=Resumo,
            temperature=0.3,
        ),
    )
    resumo = resposta.parsed if isinstance(resposta.parsed, Resumo) \
        else Resumo.model_validate_json(resposta.text)
    return resumo.observacoes[:5]


# ------------------------------------------------------------------ casamento com SKUs

ABREVIACOES = {
    "qj": "queijo", "mussarela": "mucarela", "mozzarella": "mucarela", "muss": "mucarela",
    "refri": "refrigerante", "refrig": "refrigerante", "cong": "congelado",
    "congel": "congelado", "integ": "integral", "lt": "leite", "req": "requeijao",
    "manteig": "manteiga", "parm": "parmesao", "hamb": "hamburguer", "bov": "bovino",
    "bovina": "bovino", "pct": "pacote", "frang": "frango",
}
IRRELEVANTES = {"de", "da", "do", "com", "c", "x", "e", "tipo", "cx", "un", "und", "kg", "l",
                "ml", "g", "fardo", "pacote", "pc", "pct"}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    palavras = re.findall(r"[a-z]+|\d+(?:[.,]\d+)?", texto)
    return " ".join(ABREVIACOES.get(p, p) for p in palavras)


def _tokens(texto: str) -> set[str]:
    return {t for t in texto.split() if t not in IRRELEVANTES and len(t) > 1}


def similaridade(a: str, b: str) -> float:
    """Mistura a semelhança de caracteres (difflib) com a sobreposição de palavras."""
    na, nb = _normalizar(a), _normalizar(b)
    ta, tb = _tokens(na), _tokens(nb)
    sobreposicao = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0
    return 0.5 * SequenceMatcher(None, na, nb).ratio() + 0.5 * sobreposicao


def casar_itens(nota: NotaExtraida, produtos: pd.DataFrame, minimo: float = 0.45) -> pd.DataFrame:
    """Sugere um SKU para cada item lido. Abaixo de `minimo`, deixa em branco
    para o usuário escolher — melhor não sugerir do que sugerir errado."""
    linhas = []
    for item in nota.itens:
        notas = produtos["nome"].map(lambda nome: similaridade(item.descricao, nome))
        melhor = notas.idxmax() if len(notas) else None
        score = float(notas.max()) if len(notas) else 0.0
        linhas.append({
            "importar": score >= minimo,
            "descricao": item.descricao,
            "sku": produtos.at[melhor, "sku"] if score >= minimo else None,
            "similaridade": round(score * 100),
            "quantidade": item.quantidade,
            "unidade_nota": item.unidade,
            "custo_unitario": item.custo_unitario,
            "lote": item.lote,
            "validade": pd.to_datetime(item.validade, errors="coerce"),
        })
    return pd.DataFrame(linhas)


# ------------------------------------------------------------------ exemplos

EXEMPLOS = {
    "NF-e de laticínios": """DANFE - DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRÔNICA
LATICINIOS CAMPO BOM LTDA          CNPJ 00.000.000/0001-00 (fictício)
NF-e Nº 000.048.213   SÉRIE 1      DATA DE EMISSÃO: {d0}
DESTINATÁRIO: DISTRIBUIDORA BOA SAFRA (FICTÍCIA)

CÓD   DESCRIÇÃO DO PRODUTO                    UN   QTD     V.UNIT    V.TOTAL
1021  LEITE UHT INTEGRAL CX C/12X1L            CX   40      53,90     2.156,00
      LOTE: LB{lote}A  VAL: {v1}
1088  QJ MUSSARELA FATIADA KG                  KG   35,5    35,20     1.249,60
      LOTE: QM{lote}  VAL: {v2}
1102  MANTEIGA C/ SAL POTE 500G                UN   24      22,50       540,00
      LOTE: MT{lote}  VAL: {v3}
1140  IOGURTE NATURAL 1KG                      UN   30       9,60       288,00
      LOTE: IG{lote}  VAL: {v4}
1199  DOCE DE LEITE PASTOSO 400G               UN   12       8,40       100,80
      LOTE: DL{lote}  VAL: {v5}

VALOR TOTAL DOS PRODUTOS: 4.334,40   FRETE: 0,00   VALOR TOTAL DA NOTA: 4.334,40
TRANSPORTADORA: PRÓPRIA - PLACA ABC1D23""",

    "Pedido por e-mail (bebidas e mercearia)": """De: comercial@bebidasrioclaro.exemplo
Assunto: Confirmação do pedido 7731 — entrega {d0}

Bom dia, segue a confirmação do pedido nº 7731 faturado hoje ({d0}):

- 25 fardos de refri cola 2L (6 un) a R$ 41,50 o fardo — lote RC{lote}, val. {v1}
- 18 fardos de guaraná 2L c/6 por R$ 32,80 cada — lote GR{lote}, validade {v2}
- 30 fardos água mineral 500ml c/12 = R$ 13,50/fardo, lote AM{lote}, val {v3}
- 40 litros de suco de laranja integral, R$ 9,70 o litro, lote SL{lote}, val {v4}
- 12 pacotes de café torrado e moído 500g a 16,40 (lote CF{lote}, vence {v5})

Frete CIF. Qualquer dúvida estou à disposição.
Marcos — Bebidas Rio Claro Distribuição (empresa fictícia)""",
}


def texto_exemplo(nome: str) -> str:
    """Preenche as datas do exemplo relativas a hoje, para a validade fazer sentido."""
    hoje = pd.Timestamp.today().normalize()
    dias = [90, 45, 80, 30, 120] if nome.startswith("NF") else [150, 140, 300, 50, 280]
    datas = {f"v{i}": (hoje + pd.Timedelta(days=d)).strftime("%d/%m/%Y")
             for i, d in enumerate(dias, start=1)}
    return EXEMPLOS[nome].format(d0=hoje.strftime("%d/%m/%Y"), lote=hoje.strftime("%y%m%d"), **datas)


def extracao_demonstracao(nome: str) -> NotaExtraida:
    """Resultado pré-pronto dos exemplos, para testar o fluxo sem chave de API."""
    hoje = pd.Timestamp.today().normalize()
    lote = hoje.strftime("%y%m%d")

    def v(d):
        return (hoje + pd.Timedelta(days=d)).strftime("%Y-%m-%d")

    if nome.startswith("NF"):
        dados = {"fornecedor": "Laticínios Campo Bom Ltda", "numero": "48213", "itens": [
            ("LEITE UHT INTEGRAL CX C/12X1L", 40, "cx", 53.90, f"LB{lote}A", v(90)),
            ("QJ MUSSARELA FATIADA KG", 35.5, "kg", 35.20, f"QM{lote}", v(45)),
            ("MANTEIGA C/ SAL POTE 500G", 24, "un", 22.50, f"MT{lote}", v(80)),
            ("IOGURTE NATURAL 1KG", 30, "un", 9.60, f"IG{lote}", v(30)),
            ("DOCE DE LEITE PASTOSO 400G", 12, "un", 8.40, f"DL{lote}", v(120))]}
    else:
        dados = {"fornecedor": "Bebidas Rio Claro Distribuição", "numero": "7731", "itens": [
            ("refri cola 2L (6 un)", 25, "cx", 41.50, f"RC{lote}", v(150)),
            ("guaraná 2L c/6", 18, "cx", 32.80, f"GR{lote}", v(140)),
            ("água mineral 500ml c/12", 30, "cx", 13.50, f"AM{lote}", v(300)),
            ("suco de laranja integral", 40, "L", 9.70, f"SL{lote}", v(50)),
            ("café torrado e moído 500g", 12, "un", 16.40, f"CF{lote}", v(280))]}
    campos = ["descricao", "quantidade", "unidade", "custo_unitario", "lote", "validade"]
    return NotaExtraida(fornecedor=dados["fornecedor"], numero=dados["numero"],
                        data_emissao=hoje.strftime("%Y-%m-%d"),
                        itens=[ItemNota(**dict(zip(campos, i))) for i in dados["itens"]])


def para_json(dados: dict) -> str:
    """Serializa os agregados de forma estável (a chave do cache depende disso)."""
    return json.dumps(dados, ensure_ascii=False, sort_keys=True, default=str)
