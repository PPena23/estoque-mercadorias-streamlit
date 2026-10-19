"""Diálogo de confirmação de movimentação, usado pela tela manual e pela importação com IA."""

from __future__ import annotations

from typing import Callable

import pandas as pd
import streamlit as st

import db
from componentes.feedback import avisar
from formatos import moeda, quantidade


@st.dialog("Confirmar movimentação", width="large")
def confirmar_movimentacao(cabecalho: dict, itens: list[dict],
                           ao_concluir: Callable[[], None] | None = None) -> None:
    """Mostra o resumo e só grava no banco quando o usuário confirma.

    st.dialog roda como fragmento: os botões daqui reexecutam só esta função,
    e st.rerun() no fim fecha o diálogo e redesenha a página inteira.
    """
    produtos = db.ler_produtos().set_index("id")
    tabela = pd.DataFrame(itens)
    entrada = cabecalho["tipo"] == "Entrada"
    valor_unit = tabela["custo_unitario"] if entrada else tabela["preco_unitario"].fillna(tabela["custo_unitario"])
    tabela["Produto"] = tabela["produto_id"].map(produtos["nome"])
    tabela["Qtd."] = [quantidade(q, produtos.at[p, "unidade"])
                      for p, q in zip(tabela["produto_id"], tabela["quantidade"])]
    tabela["Total"] = (tabela["quantidade"] * valor_unit).map(moeda)

    st.markdown(f"**{cabecalho['tipo']} · {cabecalho['motivo']}** — {cabecalho.get('parceiro') or 'sem parceiro'}  \n"
                f"Documento {cabecalho.get('documento') or '—'} · {pd.Timestamp(cabecalho['data']):%d/%m/%Y}")
    colunas = ["Produto", "Qtd.", "Total"] + (["lote", "validade"] if entrada else [])
    st.dataframe(tabela[colunas], hide_index=True, column_config={
        "lote": "Lote", "validade": st.column_config.DateColumn("Validade", format="DD/MM/YYYY")})
    rotulo_total = "Total a custo" if entrada else ("Total da venda" if cabecalho["motivo"] == "Venda"
                                                    else "Total a custo")
    st.markdown(f"**{rotulo_total}: {moeda(float((tabela['quantidade'] * valor_unit).sum()))}**")

    c1, c2 = st.columns(2)
    if c1.button("Voltar e editar", width="stretch"):
        st.rerun()
    if c2.button("Confirmar e gravar", type="primary", icon=":material/check:", width="stretch"):
        try:
            mov_id = db.registrar_movimentacao(cabecalho, itens)
        except db.EstoqueInsuficiente:
            st.error("Outra operação consumiu o saldo enquanto você confirmava. Revise as quantidades.")
            return
        avisar(f"{cabecalho['tipo']} nº {mov_id} registrada com {len(itens)} item(ns).")
        if ao_concluir:
            ao_concluir()
        st.rerun()
