"""Estoque: posição atual, reposição sugerida, curva ABC e lotes por validade."""

import streamlit as st

import db
from componentes import (barra_filtros, cabecalho_pagina, estado_vazio, filtros_atuais,
                         grade_kpis, kpi_card, resumo_status, titulo_secao)
from componentes import graficos
from componentes.tabelas import botoes_exportacao, formato_br
from formatos import moeda, numero
from servicos import estoque as est


def vezes(fator: float) -> str:
    """1.5 -> '1,5×' · 2.0 -> '2×'"""
    return f"{numero(fator, 2).rstrip('0').rstrip(',')}×"


posicao = est.posicao_estoque()
cabecalho_pagina(
    "Estoque", "Saldo calculado a partir das movimentações, com status, valor e sugestão de compra.",
    "Operação · Posição de estoque",
    lateral=f"Valor total a custo<br><strong style='font-size:1.4rem'>{moeda(posicao['valor_estoque'].sum(), 0)}</strong>")

barra_filtros(data_minima=db.ler_itens()["data"].min().date())
inicio, fim, categorias = filtros_atuais()
if categorias:
    posicao = posicao[posicao["categoria"].isin(categorias)]

resumo_status(posicao["status"].value_counts().to_dict(), len(posicao))
st.write("")

aba_pos, aba_rep, aba_abc, aba_lotes = st.tabs([
    ":material/inventory: Posição atual", ":material/shopping_cart: Reposição sugerida",
    ":material/stacked_bar_chart: Curva ABC", ":material/event_busy: Lotes e validade"])

# ------------------------------------------------------------------ posição
with aba_pos:
    c1, c2 = st.columns([2, 1.4])
    busca = c1.text_input("Buscar produto", placeholder="Nome ou SKU", key="est_busca")
    status_sel = c2.multiselect("Status", est.STATUS, key="est_status", placeholder="Todos")
    tabela = posicao
    if busca:
        alvo = busca.lower()
        tabela = tabela[tabela["nome"].str.lower().str.contains(alvo, regex=False)
                        | tabela["sku"].str.lower().str.contains(alvo, regex=False)]
    if status_sel:
        tabela = tabela[tabela["status"].isin(status_sel)]

    if tabela.empty:
        estado_vazio("Nenhum produto encontrado", "Tente outro termo ou limpe os filtros.", "🔎")
    else:
        colunas = ["status", "sku", "nome", "categoria", "unidade", "saldo", "estoque_minimo",
                   "nivel_pct", "custo_unitario", "valor_estoque", "proxima_validade", "fornecedor"]
        exibir = tabela[colunas].rename(columns={"status": "Status"})
        st.dataframe(
            formato_br(exibir, moedas=["custo_unitario", "valor_estoque"], numeros=["saldo", "estoque_minimo"],
                       datas=["proxima_validade"], status="Status"),
            hide_index=True, height=520,
            column_config={
                "Status": st.column_config.TextColumn("Status", pinned=True, width=150),
                "sku": st.column_config.TextColumn("SKU", pinned=True, width=90),
                "nome": st.column_config.TextColumn("Produto", pinned=True, width=230),
                "categoria": "Categoria", "unidade": "Un.", "saldo": "Saldo", "estoque_minimo": "Mínimo",
                "nivel_pct": st.column_config.ProgressColumn(
                    "Saldo × mínimo", min_value=0, max_value=300, format="%.0f%%",
                    help="100% = saldo igual ao estoque mínimo (barra limitada a 300%)."),
                "custo_unitario": "Custo unit.", "valor_estoque": "Valor em estoque",
                "proxima_validade": "Próx. validade",
                "fornecedor": "Fornecedor",
            })
        botoes_exportacao({"Estoque": tabela[colunas]}, "posicao_estoque", "pos")

# ------------------------------------------------------------------ reposição
with aba_rep:
    c1, c2 = st.columns(2)
    alvo = c1.select_slider("Repor até (× estoque mínimo)", [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
                            value=est.FATOR_ALVO_PADRAO, format_func=vezes, key="rep_alvo")
    gatilho = c2.select_slider("Sugerir quando o saldo estiver abaixo de", [1.0, 1.25, 1.5, 1.75, 2.0],
                               value=1.0, format_func=lambda v: vezes(v) + " o mínimo", key="rep_gatilho",
                               help="1× = só quem já furou o mínimo.")
    rep = est.reposicao_sugerida(posicao, alvo, gatilho)
    if rep.empty:
        estado_vazio("Nada para repor", "Nenhum produto abaixo do gatilho escolhido.", "✅")
    else:
        grade_kpis([
            kpi_card("Produtos a repor", str(len(rep)), com_delta=False, rodape="abaixo do gatilho"),
            kpi_card("Fornecedores", str(rep["fornecedor"].nunique()), com_delta=False, rodape="pedidos a emitir"),
            kpi_card("Custo estimado", moeda(rep["custo_estimado"].sum(), 0), com_delta=False,
                     rodape=f"para chegar a {vezes(alvo)} o mínimo"),
        ])
        colunas = ["fornecedor", "status", "sku", "nome", "unidade", "saldo", "estoque_minimo",
                   "sugerido", "custo_unitario", "custo_estimado"]
        st.dataframe(
            formato_br(rep[colunas].rename(columns={"status": "Status"}), status="Status",
                       moedas=["custo_unitario", "custo_estimado"], numeros=["saldo", "estoque_minimo", "sugerido"]),
            hide_index=True,
            column_config={
                "fornecedor": "Fornecedor", "sku": "SKU", "nome": "Produto", "unidade": "Un.",
                "saldo": "Saldo", "estoque_minimo": "Mínimo",
                "sugerido": st.column_config.Column("Comprar", help=f"Leva o saldo a {numero(alvo, 1)}× o mínimo."),
                "custo_unitario": "Custo unit.", "custo_estimado": "Custo estimado",
            })
        titulo_secao("Saldo × mínimo dos itens a repor")
        graficos.mostrar(graficos.niveis_estoque(rep.sort_values("saldo", ascending=False)))
        por_fornecedor = (rep.groupby("fornecedor", as_index=False)
                          .agg(itens=("sku", "count"), custo_estimado=("custo_estimado", "sum")))
        botoes_exportacao({"Pedido sugerido": rep[colunas], "Por fornecedor": por_fornecedor},
                          "reposicao_sugerida", "rep")

# ------------------------------------------------------------------ ABC
with aba_abc:
    base = st.segmented_control(
        "Base da classificação", ["Valor das saídas no período", "Valor em estoque hoje"],
        default="Valor das saídas no período", key="abc_base", required=True)
    if base == "Valor em estoque hoje":
        valores = posicao.set_index("nome")["valor_estoque"]
    else:
        valores = est.valor_saidas_por_produto(inicio, fim, categorias)
    abc = est.curva_abc(valores)
    if abc.empty:
        estado_vazio("Sem valores para classificar", "Não há saídas no período filtrado.", "📉")
    else:
        resumo = abc.groupby("classe").agg(itens=("valor", "size"), valor=("valor", "sum"))
        cols = st.columns(3)
        for col, classe in zip(cols, ["A", "B", "C"]):
            if classe in resumo.index:
                linha = resumo.loc[classe]
                col.metric(f"Classe {classe}", f"{int(linha['itens'])} itens",
                           f"{linha['valor'] / resumo['valor'].sum() * 100:.0f}% do valor".replace(".", ","),
                           delta_color="off")
        graficos.mostrar(graficos.pareto_abc(abc))
        tabela_abc = abc.reset_index()
        st.dataframe(formato_br(tabela_abc[["posicao", "classe", "nome", "valor", "participacao", "acumulado"]],
                                moedas=["valor"], pcts=["participacao"]),
                     hide_index=True, height=320,
                     column_config={"posicao": "#", "classe": "Classe", "nome": "Produto",
                                    "valor": "Valor", "participacao": "% do total",
                                    "acumulado": st.column_config.ProgressColumn("% acumulado", min_value=0,
                                                                                 max_value=100, format="%.1f%%")})

# ------------------------------------------------------------------ lotes
with aba_lotes:
    lotes = est.lotes_em_estoque()
    if categorias:
        lotes = lotes[lotes["categoria"].isin(categorias)]
    janela = st.slider("Mostrar lotes que vencem em até (dias)", 7, 180, est.JANELA_VALIDADE_DIAS, 1,
                       key="lotes_janela")
    proximos = lotes[lotes["dias_para_vencer"] <= janela].sort_values("validade")
    st.caption("Saldo por lote calculado com FEFO: cada saída consome primeiro o lote que vence antes.")
    if proximos.empty:
        estado_vazio("Nenhum lote nessa janela", "Aumente o número de dias para ver mais lotes.", "🗓️")
    else:
        proximos = proximos.assign(valor=proximos["saldo"] * proximos["custo_unitario"])
        st.dataframe(
            formato_br(proximos[["dias_para_vencer", "validade", "sku", "nome", "lote", "saldo", "unidade", "valor"]],
                       datas=["validade"], numeros=["saldo"], moedas=["valor"]),
            hide_index=True,
            column_config={
                "dias_para_vencer": st.column_config.NumberColumn("Dias", format="%d",
                                                                  help="Negativo = já vencido"),
                "validade": "Validade", "sku": "SKU", "nome": "Produto", "lote": "Lote",
                "saldo": "Saldo no lote", "unidade": "Un.", "valor": "Valor a custo",
            })
        st.info(f"{len(proximos)} lote(s) somando {moeda(proximos['valor'].sum())} vencem em até {janela} dias. "
                "Priorize esses itens nas próximas saídas ou negocie promoção com clientes.",
                icon=":material/lightbulb:")
