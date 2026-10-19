"""Regras de negócio do estoque. Tudo é calculado aqui, com pandas.

Nenhum número de estoque vem da IA: o modelo só lê/escreve texto. Saldo,
valor, status, curva ABC e reposição saem destas funções, que são
determinísticas e testáveis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

import db
from formatos import quantidade as fmt_qtd

# ---------------------------------------------------------------- parâmetros
JANELA_VALIDADE_DIAS = 30
FATOR_ALVO_PADRAO = 2.0   # reposição leva o saldo a 2x o estoque mínimo
LIMITE_A, LIMITE_B = 80, 95  # curva ABC: 80% do valor = A, até 95% = B

ZERADO, ABAIXO, VENCENDO, OK = "Zerado", "Abaixo do mínimo", "Vencendo em 30 dias", "OK"
STATUS = [ZERADO, ABAIXO, VENCENDO, OK]  # ordem de gravidade

MOTIVOS = {
    "Entrada": ["Compra", "Devolução de cliente"],
    "Saída": ["Venda", "Perda", "Transferência"],
}
CATEGORIAS = ["Mercearia", "Laticínios", "Carnes", "Congelados", "Hortifrúti",
              "Bebidas", "Limpeza", "Descartáveis"]
UNIDADES = ["un", "cx", "kg", "L"]


def hoje() -> pd.Timestamp:
    return pd.Timestamp(date.today())


# ---------------------------------------------------------------- posição

@st.cache_data(ttl=600, show_spinner=False)
def lotes_em_estoque() -> pd.DataFrame:
    """Saldo por lote, aplicando FEFO (primeiro que vence, primeiro que sai).

    Percorre o histórico em ordem cronológica: cada entrada abre um lote e
    cada saída consome os lotes disponíveis naquele momento, do que vence
    antes para o que vence depois. Só vale para produtos com validade.
    """
    itens = db.ler_itens()
    prod = db.ler_produtos(incluir_inativos=True)
    com_validade = set(prod.loc[prod["controla_validade"], "id"])
    itens = itens[itens["produto_id"].isin(com_validade)]

    linhas = []
    for pid, grupo in itens.groupby("produto_id", sort=False):
        abertos: list[dict] = []
        for mov in grupo.itertuples(index=False):
            if mov.tipo == "Entrada":
                abertos.append({"produto_id": pid, "lote": "s/ lote" if pd.isna(mov.lote) else mov.lote,
                                "validade": mov.validade, "entrada": mov.data,
                                "saldo": mov.quantidade})
                continue
            falta = mov.quantidade
            abertos.sort(key=lambda l: (pd.isna(l["validade"]), l["validade"]))
            for lote in abertos:
                usado = min(falta, lote["saldo"])
                lote["saldo"] -= usado
                falta -= usado
                if falta <= 1e-9:
                    break
            abertos = [l for l in abertos if l["saldo"] > 1e-9]
        linhas.extend(abertos)

    lotes = pd.DataFrame(linhas, columns=["produto_id", "lote", "validade", "entrada", "saldo"])
    lotes["saldo"] = lotes["saldo"].round(3)
    lotes["dias_para_vencer"] = (lotes["validade"] - hoje()).dt.days
    return lotes.merge(prod[["id", "sku", "nome", "categoria", "unidade", "custo_unitario"]],
                       left_on="produto_id", right_on="id").drop(columns="id")


def saldo_em(data_limite: pd.Timestamp | None = None) -> pd.Series:
    """Saldo de cada produto ao fim de uma data (ou hoje, se None)."""
    itens = db.ler_itens()
    if data_limite is not None:
        itens = itens[itens["data"] <= data_limite]
    return (itens["quantidade"] * itens["sinal"]).groupby(itens["produto_id"]).sum().round(3)


@st.cache_data(ttl=600, show_spinner=False)
def posicao_estoque() -> pd.DataFrame:
    """Uma linha por produto ativo com saldo, valor, status e alertas."""
    prod = db.ler_produtos()
    df = prod.assign(saldo=prod["id"].map(saldo_em()).fillna(0.0) + 0.0)  # +0.0 evita "-0"
    df["valor_estoque"] = (df["saldo"] * df["custo_unitario"]).round(2)

    lotes = lotes_em_estoque()
    vencendo = lotes[lotes["dias_para_vencer"] <= JANELA_VALIDADE_DIAS]
    df["qtd_vencendo"] = df["id"].map(vencendo.groupby("produto_id")["saldo"].sum()).fillna(0.0)
    df["proxima_validade"] = pd.to_datetime(df["id"].map(lotes.groupby("produto_id")["validade"].min()))

    df["status"] = np.select(
        [df["saldo"] <= 0, df["saldo"] < df["estoque_minimo"], df["qtd_vencendo"] > 0],
        [ZERADO, ABAIXO, VENCENDO], default=OK)
    # nível em relação ao mínimo (100% = exatamente no mínimo), limitado a 300% no gráfico
    minimo = df["estoque_minimo"].replace(0, np.nan)
    df["nivel_pct"] = (df["saldo"] / minimo * 100).fillna(300).clip(upper=300).round(0)
    return df


def reposicao_sugerida(posicao: pd.DataFrame, fator_alvo: float = FATOR_ALVO_PADRAO,
                       gatilho: float = 1.0) -> pd.DataFrame:
    """Sugere compra para quem está abaixo de `gatilho` x mínimo, até `fator_alvo` x mínimo."""
    df = posicao[posicao["saldo"] < gatilho * posicao["estoque_minimo"]].copy()
    falta = (fator_alvo * df["estoque_minimo"] - df["saldo"]).clip(lower=0)
    inteiro = df["unidade"].isin(["un", "cx"])
    df["sugerido"] = np.where(inteiro, np.ceil(falta), np.ceil(falta * 10) / 10)
    df["custo_estimado"] = (df["sugerido"] * df["custo_unitario"]).round(2)
    df = df[df["sugerido"] > 0]
    return df.sort_values(["fornecedor", "status", "nome"])


def curva_abc(valores: pd.Series) -> pd.DataFrame:
    """Classifica itens por participação no valor (Pareto 80/15/5)."""
    df = valores[valores > 0].sort_values(ascending=False).rename("valor").to_frame()
    total = df["valor"].sum()
    df["participacao"] = df["valor"] / total * 100 if total else 0
    df["acumulado"] = df["participacao"].cumsum()
    anterior = df["acumulado"] - df["participacao"]  # o item que cruza 80% ainda é A
    df["classe"] = np.select([anterior < LIMITE_A, anterior < LIMITE_B], ["A", "B"], default="C")
    df["posicao"] = range(1, len(df) + 1)
    return df


# ---------------------------------------------------------------- período

def filtrar_itens(inicio: date, fim: date, categorias: list[str] | None) -> pd.DataFrame:
    itens = db.ler_itens()
    sel = (itens["data"] >= pd.Timestamp(inicio)) & (itens["data"] <= pd.Timestamp(fim))
    if categorias:
        sel &= itens["categoria"].isin(categorias)
    return itens[sel]


def periodo_anterior(inicio: date, fim: date) -> tuple[date, date]:
    """Mesmo número de dias, imediatamente antes do período escolhido."""
    dias = (fim - inicio).days + 1
    return inicio - pd.Timedelta(days=dias), inicio - pd.Timedelta(days=1)


def _numeros_periodo(inicio, fim, categorias) -> dict:
    itens = filtrar_itens(inicio, fim, categorias)
    entradas = itens[itens["tipo"] == "Entrada"]
    saidas = itens[itens["tipo"] == "Saída"]
    vendas = saidas[saidas["motivo"] == "Venda"]
    perdas = saidas[saidas["motivo"] == "Perda"]
    return {
        "entradas": float(entradas["valor_custo"].sum()),
        "saidas": float(saidas["valor_custo"].sum()),
        "faturamento": float((vendas["quantidade"] * vendas["preco_unitario"]).sum()),
        "perdas": float(perdas["valor_custo"].sum()),
        "pedidos": int(vendas["movimentacao_id"].nunique()),
    }


def valor_estoque_em(data_limite, categorias) -> float:
    prod = db.ler_produtos(incluir_inativos=True).set_index("id")
    if categorias:
        prod = prod[prod["categoria"].isin(categorias)]
    saldo = saldo_em(pd.Timestamp(data_limite)).reindex(prod.index).fillna(0)
    return float((saldo * prod["custo_unitario"]).sum())


@dataclass
class Indicadores:
    atual: dict
    anterior: dict


def indicadores(inicio: date, fim: date, categorias: list[str] | None) -> Indicadores:
    ini_ant, fim_ant = periodo_anterior(inicio, fim)
    atual = _numeros_periodo(inicio, fim, categorias)
    anterior = _numeros_periodo(ini_ant, fim_ant, categorias)
    atual["valor_estoque"] = valor_estoque_em(fim, categorias)
    anterior["valor_estoque"] = valor_estoque_em(fim_ant, categorias)
    return Indicadores(atual, anterior)


def serie_entradas_saidas(inicio: date, fim: date, categorias) -> pd.DataFrame:
    """Valor (a custo) de entradas e saídas por dia ou por blocos de 7 dias
    contados a partir do início do período (assim não sobram semanas cortadas)."""
    itens = filtrar_itens(inicio, fim, categorias)
    freq = "D" if (fim - inicio).days <= 45 else "168h"  # 168h = 7 dias "fixos" (aceita origin)
    tabela = (itens.pivot_table(index="data", columns="tipo", values="valor_custo",
                                aggfunc="sum", fill_value=0)
              .reindex(columns=["Entrada", "Saída"], fill_value=0)
              .resample(freq, origin=pd.Timestamp(inicio)).sum())
    return tabela.reset_index()


def top_saidas(inicio, fim, categorias, n: int = 10) -> pd.DataFrame:
    itens = filtrar_itens(inicio, fim, categorias)
    vendas = itens[itens["tipo"] == "Saída"]
    return (vendas.groupby(["sku", "nome", "unidade"], as_index=False)
            .agg(quantidade=("quantidade", "sum"), valor=("valor_custo", "sum"))
            .nlargest(n, "valor"))


def valor_saidas_por_produto(inicio, fim, categorias) -> pd.Series:
    itens = filtrar_itens(inicio, fim, categorias)
    saidas = itens[itens["tipo"] == "Saída"]
    return saidas.groupby("nome")["valor_custo"].sum()


# ---------------------------------------------------------------- validação

def validar_itens(tipo: str, itens: pd.DataFrame, data_mov: date) -> tuple[list[str], list[dict]]:
    """Valida a grade de itens de uma movimentação.

    `itens` precisa ter produto_id e quantidade; entradas também custo_unitario,
    lote e validade. Devolve (erros, itens_prontos_para_gravar). A conferência de
    saldo usa o banco sem cache, para nunca validar contra dado velho.
    """
    erros: list[str] = []
    prod = db.ler_produtos().set_index("id")
    itens = itens.dropna(subset=["produto_id"]).copy()
    if itens.empty:
        return ["Adicione pelo menos um item com produto selecionado."], []

    prontos = []
    for n, linha in enumerate(itens.to_dict("records"), start=1):
        p = prod.loc[int(linha["produto_id"])]
        qtd = linha.get("quantidade")
        rotulo = f"Linha {n} ({p['nome']})"
        if qtd is None or pd.isna(qtd) or qtd <= 0:
            erros.append(f"{rotulo}: informe uma quantidade maior que zero.")
            continue
        if p["unidade"] in ("un", "cx") and float(qtd) != int(qtd):
            erros.append(f"{rotulo}: produto vendido em '{p['unidade']}' aceita só quantidades inteiras.")
            continue
        item = {"produto_id": int(linha["produto_id"]), "quantidade": float(qtd),
                "custo_unitario": float(p["custo_unitario"])}

        if tipo == "Entrada":
            custo = linha.get("custo_unitario")
            if custo is not None and not pd.isna(custo):
                if custo < 0:
                    erros.append(f"{rotulo}: custo não pode ser negativo.")
                    continue
                item["custo_unitario"] = float(custo)
            validade = linha.get("validade")
            tem_validade = validade is not None and not pd.isna(validade)
            if p["controla_validade"] and not tem_validade:
                erros.append(f"{rotulo}: produto com validade controlada — informe lote e validade.")
                continue
            if tem_validade and pd.Timestamp(validade) <= pd.Timestamp(data_mov):
                erros.append(f"{rotulo}: validade {pd.Timestamp(validade):%d/%m/%Y} já vencida na data da entrada.")
                continue
            lote = str(linha.get("lote") or "").strip() or None
            if p["controla_validade"] and not lote:
                erros.append(f"{rotulo}: informe o lote.")
                continue
            item["lote"] = lote
            item["validade"] = pd.Timestamp(validade).date().isoformat() if tem_validade else None
        else:
            item["preco_unitario"] = float(p["preco_venda"])
        prontos.append(item)

    if tipo == "Saída" and prontos:
        pedido = pd.DataFrame(prontos).groupby("produto_id")["quantidade"].sum()
        saldos = db.saldos_atuais(list(pedido.index))
        for pid, qtd in pedido.items():
            if qtd > saldos[pid] + 1e-9:
                p = prod.loc[pid]
                erros.append(
                    f"Saldo insuficiente de **{p['nome']}**: saída de "
                    f"{fmt_qtd(qtd, p['unidade'])}, disponível {fmt_qtd(max(saldos[pid], 0), p['unidade'])}.")
    return erros, prontos


# ---------------------------------------------------------------- IA (somente agregados)

def agregados_para_ia(inicio: date, fim: date, categorias: list[str] | None) -> dict:
    """Resumo numérico enxuto para o "Resumo inteligente".

    Nenhuma linha de movimentação é enviada ao modelo: só totais já
    calculados aqui. O modelo comenta, mas não calcula.
    """
    ind = indicadores(inicio, fim, categorias)
    pos = posicao_estoque()
    if categorias:
        pos = pos[pos["categoria"].isin(categorias)]
    top = top_saidas(inicio, fim, categorias, 5)
    por_cat = filtrar_itens(inicio, fim, categorias).query("tipo == 'Saída'") \
        .groupby("categoria")["valor_custo"].sum().round(0)

    def arred(d):
        return {k: round(v, 2) for k, v in d.items()}

    return {
        "periodo": f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}",
        "categorias": categorias or "todas",
        "periodo_atual": arred(ind.atual),
        "periodo_anterior_mesmo_tamanho": arred(ind.anterior),
        "contagem_status": pos["status"].value_counts().to_dict(),
        "produtos_zerados": pos.loc[pos["status"] == ZERADO, "nome"].tolist(),
        "produtos_abaixo_do_minimo": pos.loc[pos["status"] == ABAIXO, "nome"].tolist(),
        "produtos_com_lote_vencendo_30_dias": pos.loc[pos["qtd_vencendo"] > 0, "nome"].tolist(),
        "top5_saidas_valor_custo": dict(zip(top["nome"], top["valor"].round(0))),
        "saidas_por_categoria_valor_custo": por_cat.to_dict(),
    }
