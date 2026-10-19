"""Movimentações: registrar entradas e saídas com vários itens e consultar o histórico."""

from datetime import date

import pandas as pd
import streamlit as st

import db
from componentes import (barra_filtros, cabecalho_pagina, estado_vazio, filtros_atuais,
                         titulo_secao)
from componentes.dialogos import confirmar_movimentacao
from componentes.tabelas import botoes_exportacao, col_data, col_moeda, col_qtd, formato_br, rotulos_produtos
from servicos import estoque as est

st.session_state.setdefault("form_mov", 0)  # trocar o número "zera" os formulários

produtos = db.ler_produtos()
rotulos = rotulos_produtos(produtos)
fornecedores = sorted(produtos["fornecedor"].unique())
clientes = sorted(db.ler_itens().query("motivo == 'Venda'")["parceiro"].dropna().unique())
fid = st.session_state.form_mov


def limpar_formularios() -> None:
    st.session_state.form_mov += 1


def grade_vazia(colunas: dict, linhas: int = 3) -> pd.DataFrame:
    """Grade com algumas linhas em branco (linhas sem produto são ignoradas na validação)."""
    return pd.DataFrame({c: pd.Series([None] * linhas, dtype=t) for c, t in colunas.items()})


def para_ids(grade: pd.DataFrame) -> pd.DataFrame:
    grade = grade.copy()
    grade["produto_id"] = grade["produto"].map(rotulos)
    return grade


cabecalho_pagina(
    "Movimentações", "Registre entradas e saídas com vários itens por documento. "
    "Saídas maiores que o saldo são bloqueadas.", "Operação · Entradas e saídas",
    lateral=f"<strong>{len(produtos)}</strong> produtos ativos")

aba_entrada, aba_saida, aba_hist = st.tabs([":material/south_west: Nova entrada",
                                            ":material/north_east: Nova saída",
                                            ":material/history: Histórico"])

# ================================================================== ENTRADA (st.form)
with aba_entrada:
    with st.form(f"form_entrada_{fid}"):
        c1, c2, c3, c4 = st.columns([1, 1.2, 1, 1.6])
        data_mov = c1.date_input("Data", value=date.today(), max_value=date.today(), format="DD/MM/YYYY")
        motivo = c2.selectbox("Motivo", est.MOTIVOS["Entrada"])
        documento = c3.text_input("Nº da nota", placeholder="NF 48213")
        parceiro = c4.selectbox("Fornecedor / cliente que devolveu", fornecedores + clientes, index=None,
                                accept_new_options=True, placeholder="Escolha ou digite um novo")
        st.caption("Itens da nota — clique em **+** para adicionar linhas. Custo em branco usa o custo do "
                   "cadastro. Lote e validade são obrigatórios para produtos com validade controlada.")
        grade = st.data_editor(
            grade_vazia({"produto": "object", "quantidade": "float", "custo_unitario": "float",
                         "lote": "object", "validade": "datetime64[ns]"}),
            num_rows="dynamic", placeholder="", key=f"grade_entrada_{fid}",
            column_config={
                "produto": st.column_config.SelectboxColumn("Produto", options=list(rotulos), required=True, width="large"),
                "quantidade": col_qtd("Quantidade", min_value=0.1, step=0.1, required=True),
                "custo_unitario": col_moeda("Custo unit.", min_value=0.0),
                "lote": st.column_config.TextColumn("Lote", max_chars=30),
                "validade": col_data("Validade"),
            })
        revisar = st.form_submit_button("Revisar entrada", type="primary", icon=":material/fact_check:")

    if revisar:
        erros = []
        if motivo == "Compra" and not documento.strip():
            erros.append("Informe o número da nota fiscal da compra.")
        if not parceiro:
            erros.append("Informe o fornecedor (ou o cliente, em devoluções).")
        erros_itens, prontos = est.validar_itens("Entrada", para_ids(grade), data_mov)
        erros += erros_itens
        if erros:
            st.error("Não foi possível registrar:\n\n" + "\n".join(f"- {e}" for e in erros),
                     icon=":material/error:")
        else:
            confirmar_movimentacao({"tipo": "Entrada", "motivo": motivo, "data": data_mov.isoformat(),
                       "documento": documento.strip(), "parceiro": parceiro}, prontos,
                                   limpar_formularios)

# ================================================================== SAÍDA (prévia ao vivo)
with aba_saida:
    with st.container(key="cartao_saida"):
        c1, c2, c3, c4 = st.columns([1, 1.2, 1, 1.6])
        data_s = c1.date_input("Data", value=date.today(), max_value=date.today(),
                               format="DD/MM/YYYY", key=f"data_s_{fid}")
        motivo_s = c2.selectbox("Motivo", est.MOTIVOS["Saída"], key=f"motivo_s_{fid}")
        doc_s = c3.text_input("Nº do pedido", placeholder="PED-001234", key=f"doc_s_{fid}")
        opcoes = {"Venda": clientes, "Transferência": ["CD Filial Norte", "Loja Centro"], "Perda": ["Descarte"]}
        parceiro_s = c4.selectbox("Cliente / destino", opcoes[motivo_s], index=None, accept_new_options=True,
                                  placeholder="Escolha ou digite", key=f"parceiro_s_{fid}")
        st.caption("A conferência abaixo é atualizada a cada item digitado; a validação final é feita "
                   "de novo direto no banco ao registrar.")
        grade_s = st.data_editor(
            grade_vazia({"produto": "object", "quantidade": "float"}),
            num_rows="dynamic", placeholder="", key=f"grade_saida_{fid}",
            column_config={
                "produto": st.column_config.SelectboxColumn("Produto", options=list(rotulos), required=True, width="large"),
                "quantidade": col_qtd("Quantidade", min_value=0.1, step=0.1, required=True),
            })

        previa = para_ids(grade_s).dropna(subset=["produto_id"])
        if not previa.empty:
            pos = est.posicao_estoque().set_index("id")
            conf = previa.groupby("produto_id", as_index=False)["quantidade"].sum()
            conf["Produto"] = conf["produto_id"].map(pos["nome"])
            conf["Disponível"] = conf["produto_id"].map(pos["saldo"])
            conf["Após a saída"] = conf["Disponível"] - conf["quantidade"].fillna(0)
            conf["Mínimo"] = conf["produto_id"].map(pos["estoque_minimo"])
            conf["Situação"] = conf.apply(
                lambda r: "Excede o saldo" if r["Após a saída"] < 0
                else ("Fica abaixo do mínimo" if r["Após a saída"] < r["Mínimo"] else "OK"), axis=1)
            titulo_secao("Conferência de saldo")
            st.dataframe(
                formato_br(conf.drop(columns="produto_id").rename(columns={"quantidade": "Saída"}),
                           numeros=["Saída", "Disponível", "Após a saída", "Mínimo"], status="Situação"),
                hide_index=True)
            if (conf["Situação"] == "Excede o saldo").any():
                st.warning("Há itens acima do saldo disponível. Ajuste antes de registrar.",
                           icon=":material/warning:")

        if st.button("Registrar saída", type="primary", icon=":material/fact_check:", key=f"btn_s_{fid}"):
            erros = [] if parceiro_s else ["Informe o cliente ou destino."]
            erros_itens, prontos = est.validar_itens("Saída", para_ids(grade_s), data_s)
            erros += erros_itens
            if erros:
                st.error("Saída bloqueada:\n\n" + "\n".join(f"- {e}" for e in erros), icon=":material/block:")
            else:
                if motivo_s != "Venda":
                    for item in prontos:
                        item["preco_unitario"] = None
                confirmar_movimentacao({"tipo": "Saída", "motivo": motivo_s, "data": data_s.isoformat(),
                           "documento": doc_s.strip() or None, "parceiro": parceiro_s},
                                       prontos, limpar_formularios)

# ================================================================== HISTÓRICO
with aba_hist:
    barra_filtros(data_minima=db.ler_itens()["data"].min().date())
    inicio, fim, categorias = filtros_atuais()
    itens = est.filtrar_itens(inicio, fim, categorias)

    c1, c2 = st.columns([1, 2])
    tipo = c1.segmented_control("Tipo", ["Entradas", "Saídas"], selection_mode="multi",
                                default=["Entradas", "Saídas"], key="hist_tipo")
    busca = c2.text_input("Buscar", placeholder="Documento, parceiro ou produto",
                          key="hist_busca", label_visibility="visible")
    tipos = {"Entradas": "Entrada", "Saídas": "Saída"}
    itens = itens[itens["tipo"].isin([tipos[t] for t in tipo or []])]
    if busca:
        alvo = busca.lower()
        mascara = (itens["documento"].fillna("").str.lower().str.contains(alvo, regex=False)
                   | itens["parceiro"].fillna("").str.lower().str.contains(alvo, regex=False)
                   | itens["nome"].str.lower().str.contains(alvo, regex=False)
                   | itens["sku"].str.lower().str.contains(alvo, regex=False))
        itens = itens[mascara]

    if itens.empty:
        estado_vazio("Nenhuma movimentação encontrada", "Ajuste o período, as categorias ou a busca.", "🔎")
    else:
        movs = (itens.groupby(["movimentacao_id", "data", "tipo", "motivo", "documento", "parceiro", "origem"],
                              dropna=False, as_index=False)
                .agg(itens=("item_id", "count"), valor=("valor_custo", "sum"))
                .sort_values(["data", "movimentacao_id"], ascending=False))
        st.caption(f"{len(movs)} movimentações · {len(itens)} itens · clique numa linha para ver os itens.")
        selecao = st.dataframe(
            formato_br(movs, moedas=["valor"], datas=["data"]), hide_index=True, on_select="rerun", selection_mode="single-row", key="hist_tabela",
            height=380,
            column_config={
                "movimentacao_id": st.column_config.NumberColumn("Nº", format="%d"),
                "data": "Data", "tipo": "Tipo", "motivo": "Motivo", "documento": "Documento",
                "parceiro": "Fornecedor / cliente", "origem": "Origem",
                "itens": st.column_config.NumberColumn("Itens", format="%d"),
                "valor": "Valor (custo)",
            })
        linhas = selecao.selection.rows
        if linhas:
            mov = movs.iloc[linhas[0]]
            titulo_secao(f"Itens da movimentação nº {mov['movimentacao_id']}",
                         f"{mov['tipo']} · {mov['motivo']} · {mov['parceiro']}")
            detalhe = itens[itens["movimentacao_id"] == mov["movimentacao_id"]]
            st.dataframe(formato_br(detalhe[["sku", "nome", "quantidade", "unidade", "custo_unitario",
                                             "preco_unitario", "lote", "validade"]],
                                    numeros=["quantidade"], moedas=["custo_unitario", "preco_unitario"],
                                    datas=["validade"]), hide_index=True,
                         column_config={"sku": "SKU", "nome": "Produto", "quantidade": "Qtd.", "unidade": "Un.",
                                        "custo_unitario": "Custo unit.", "preco_unitario": "Preço unit.",
                                        "lote": "Lote", "validade": "Validade"})

        exportar = itens[["movimentacao_id", "data", "tipo", "motivo", "documento", "parceiro", "sku",
                          "nome", "categoria", "quantidade", "unidade", "custo_unitario",
                          "preco_unitario", "lote", "validade", "valor_custo"]]
        c_vazio, c_exp = st.columns([3, 1.2])
        c_vazio.caption("A exportação respeita os filtros e a busca acima.")
        with c_exp:
            botoes_exportacao({"Itens": exportar, "Movimentações": movs}, "movimentacoes", "hist")
