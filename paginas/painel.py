"""Painel: KPIs com variação, gráficos e o Resumo inteligente (IA)."""

import pandas as pd
import streamlit as st
from google.genai import errors

import db
from componentes import (barra_filtros, cabecalho_pagina, estado_vazio,
                         filtros_atuais, grade_kpis, kpi_card, lista_insights, titulo_secao)
from componentes import graficos
from componentes.tabelas import formato_br
from formatos import data_br, moeda_curta
from servicos import estoque as est
from servicos import ia


def variacao(atual: float, anterior: float) -> float | None:
    return (atual - anterior) / anterior * 100 if anterior else None


itens = db.ler_itens()
inicio, fim, categorias = filtros_atuais()
ini_ant, fim_ant = est.periodo_anterior(inicio, fim)

cabecalho_pagina(
    "Painel de estoque",
    "Entradas, saídas e saúde do estoque da distribuidora em um só lugar.",
    "Visão geral · Distribuidora Boa Safra",
    lateral=f"<strong>{data_br(inicio)} → {data_br(fim)}</strong><br>"
            f"comparado a {data_br(ini_ant)} → {data_br(fim_ant)}<br>"
            f"<span class='faixa__selo'>dados fictícios</span>",
)
barra_filtros(data_minima=itens["data"].min().date())

ind = est.indicadores(inicio, fim, categorias)
a, b = ind.atual, ind.anterior
posicao = est.posicao_estoque()
if categorias:
    posicao = posicao[posicao["categoria"].isin(categorias)]
alerta = posicao[posicao["status"] != est.OK]

grade_kpis([
    kpi_card("Valor em estoque", moeda_curta(a["valor_estoque"]),
             variacao(a["valor_estoque"], b["valor_estoque"]), bom_quando="neutro",
             rodape="no fim do período"),
    kpi_card("Entradas (custo)", moeda_curta(a["entradas"]), variacao(a["entradas"], b["entradas"]),
             rodape="vs. período anterior"),
    kpi_card("Saídas (custo)", moeda_curta(a["saidas"]), variacao(a["saidas"], b["saidas"]),
             rodape="vs. período anterior"),
    kpi_card("Faturamento", moeda_curta(a["faturamento"]),
             variacao(a["faturamento"], b["faturamento"]), rodape=f"{a['pedidos']} pedidos"),
    kpi_card("Perdas", moeda_curta(a["perdas"]), variacao(a["perdas"], b["perdas"]),
             bom_quando="baixa", rodape="avarias e vencidos"),
    kpi_card("Produtos em alerta", str(len(alerta)), com_delta=False, alerta=len(alerta) > 0,
             rodape=f"de {len(posicao)} ativos · hoje"),
])

# ------------------------------------------------------------------ resumo com IA
with st.container(key="cartao_resumo"):
    c_txt, c_btn = st.columns([4, 1.3], vertical_alignment="center")
    c_txt.markdown("**Resumo inteligente** · a IA comenta os números do período "
                   "(só totais agregados são enviados; nenhum cálculo é feito pelo modelo).")
    gerar = c_btn.button("Gerar resumo", icon=":material/auto_awesome:", type="primary", width="stretch")
    chave_resumo = (inicio, fim, tuple(categorias))
    if gerar:
        chave_api = ia.ler_chave()
        if not chave_api:
            st.info("Configure a GEMINI_API_KEY para usar o resumo — veja a página "
                    "**Importar nota com IA**. O restante do painel funciona normalmente.",
                    icon=":material/key:")
        else:
            try:
                with st.spinner("Lendo os indicadores..."):
                    modelo = st.session_state.get("modelo_ia") or ia.modelos_disponiveis(chave_api)[0]
                    dados = est.agregados_para_ia(inicio, fim, categorias)
                    st.session_state.resumo_ia = (chave_resumo, ia.resumo_inteligente(
                        chave_api, modelo, ia.para_json(dados)))
            except errors.APIError as e:
                st.error(ia.mensagem_erro(e))
    resumo = st.session_state.get("resumo_ia")
    if resumo and resumo[0] == chave_resumo:
        lista_insights(resumo[1])

if itens[(itens["data"] >= pd.Timestamp(inicio)) & (itens["data"] <= pd.Timestamp(fim))].empty:
    estado_vazio("Sem movimentações no período", "Escolha outro intervalo de datas nos filtros.", "🗓️")
    st.stop()

# ------------------------------------------------------------------ gráficos
esq, dir_ = st.columns([1.7, 1], gap="medium")
with esq.container(key="cartao_serie"):
    titulo_secao("Entradas × saídas", "Valor a custo · diário até 45 dias; acima disso, em blocos de 7 dias")
    graficos.mostrar(graficos.entradas_x_saidas(est.serie_entradas_saidas(inicio, fim, categorias)))
with dir_.container(key="cartao_categoria"):
    titulo_secao("Valor em estoque por categoria", "Posição atual, a custo")
    por_cat = posicao.groupby("categoria", as_index=False)["valor_estoque"].sum()
    graficos.mostrar(graficos.valor_por_categoria(por_cat))

esq, dir_ = st.columns(2, gap="medium")
with esq.container(key="cartao_top"):
    titulo_secao("Top 10 produtos por saída", "Valor a custo no período")
    graficos.mostrar(graficos.top_produtos(est.top_saidas(inicio, fim, categorias)))
with dir_.container(key="cartao_abc"):
    abc = est.curva_abc(est.valor_saidas_por_produto(inicio, fim, categorias))
    contagem = abc["classe"].value_counts()
    titulo_secao("Curva ABC das saídas",
                 f"A: {contagem.get('A', 0)} itens · B: {contagem.get('B', 0)} · C: {contagem.get('C', 0)}")
    graficos.mostrar(graficos.pareto_abc(abc))

# ------------------------------------------------------------------ atenção
with st.container(key="cartao_alertas"):
    titulo_secao("Precisa de atenção hoje", "Produtos zerados, abaixo do mínimo ou com lote vencendo")
    if alerta.empty:
        estado_vazio("Tudo em ordem", "Nenhum produto em alerta nas categorias filtradas.", "✅")
    else:
        ordem = {s: i for i, s in enumerate(est.STATUS)}
        tabela = (alerta.sort_values("status", key=lambda s: s.map(ordem))
                  [["status", "sku", "nome", "saldo", "estoque_minimo", "unidade", "proxima_validade"]]
                  .rename(columns={"status": "Status"}))
        st.dataframe(
            formato_br(tabela, numeros=["saldo", "estoque_minimo"], datas=["proxima_validade"], status="Status"),
            hide_index=True,
            column_config={
                "sku": "SKU", "nome": "Produto", "unidade": "Un.",
                "saldo": "Saldo", "estoque_minimo": "Mínimo",
                "proxima_validade": "Próx. validade",
            })
        st.page_link("paginas/estoque.py", label="Abrir estoque e reposição sugerida",
                     icon=":material/arrow_forward:")
