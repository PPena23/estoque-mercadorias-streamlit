"""Sobre o projeto: o que o app faz e onde cada conceito de Streamlit aparece no código."""

import pandas as pd
import streamlit as st

import db
from componentes import cabecalho_pagina, titulo_secao

cabecalho_pagina(
    "Sobre o projeto",
    "App de portfólio: controle de entrada e saída de mercadorias com estoque, painel e IA, "
    "feito 100% em Python com Streamlit.",
    "Projeto · Pedro Pena",
    lateral="<a style='color:#fff' href='https://github.com/PPena23' target='_blank'>GitHub</a> · "
            "<a style='color:#fff' href='https://www.linkedin.com/in/pedropena23/' target='_blank'>LinkedIn</a>")

esq, dir_ = st.columns([1.3, 1], gap="large")
with esq:
    titulo_secao("O que o app resolve")
    st.markdown("""
Uma distribuidora de alimentos **fictícia** (Boa Safra) precisa saber, a qualquer momento,
**quanto tem de cada produto, quanto vale e o que comprar**. O app registra entradas e saídas
com vários itens por documento, calcula o saldo a partir do histórico, alerta sobre mínimos e
validades (FEFO) e usa IA para tirar o trabalho braçal de digitar notas fiscais.

**Regra de ouro da IA:** o modelo transforma texto em dados (extração com esquema) e dados em
texto (resumo). **Nenhum saldo ou valor é calculado pelo modelo** — tudo vem de pandas/SQL.
""")
with dir_:
    titulo_secao("A base de demonstração")
    itens = db.ler_itens()
    st.markdown(f"""
- **{len(db.ler_produtos())}** produtos em 8 categorias
- **{itens['movimentacao_id'].nunique():,}** movimentações e **{len(itens):,}** itens
- de **{itens['data'].min():%d/%m/%Y}** a **{itens['data'].max():%d/%m/%Y}**
- gerada por `gerar_dados.py` na primeira execução (SQLite)
""".replace(",", "."))

titulo_secao("Conceitos de Streamlit → onde estão no código")
conceitos = pd.DataFrame([
    ("Multipage com navegação no topo", "st.navigation(position='top'), st.Page, seções", "app.py"),
    ("Componentes reutilizáveis", "cabeçalho, KPI, badge, estado vazio, gráficos", "componentes/"),
    ("CSS integrado + tema", "config.toml (cores, fontes Google) + estilo.css", ".streamlit/, estilo/"),
    ("Session State", "filtros globais entre páginas, fila de toasts, reset de formulários", "componentes/filtros.py"),
    ("persist_state", "texto da nota e modelo de IA sobrevivem à troca de página", "paginas/importar_ia.py"),
    ("Formulários", "st.form com validação (produtos e entrada)", "paginas/produtos.py"),
    ("Grade editável", "st.data_editor com SelectboxColumn, DateColumn, linhas dinâmicas", "paginas/movimentacoes.py"),
    ("Diálogos", "st.dialog para confirmar gravação e desativação", "componentes/dialogos.py"),
    ("Feedback", "st.toast, st.status, st.spinner", "componentes/feedback.py, paginas/importar_ia.py"),
    ("column_config", "ProgressColumn, NumberColumn (R$), DateColumn, CheckboxColumn", "paginas/estoque.py"),
    ("Seleção em tabela", "st.dataframe(on_select='rerun') abre os itens", "paginas/movimentacoes.py"),
    ("Cache", "cache_resource (conexão, cliente IA) e cache_data com ttl + limpeza na escrita", "db.py, servicos/"),
    ("Exportação", "CSV e Excel gerados só no clique (download_button com função)", "componentes/tabelas.py"),
    ("Visualização", "Plotly com tema próprio e separador decimal brasileiro", "componentes/graficos.py"),
    ("IA / LLM", "Gemini com response_schema (Pydantic) e resumo de agregados", "servicos/ia.py"),
], columns=["Conceito", "Como aparece", "Arquivo"])
st.dataframe(conceitos, hide_index=True, width="stretch")
