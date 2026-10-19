"""Controle de Entrada e Saída de Mercadorias — ponto de entrada.

Rodar:  .venv\\Scripts\\streamlit run app.py

Este arquivo roda a cada interação: configura a página, aplica o CSS,
garante o banco (cria e popula na primeira vez), inicia o Session State,
monta a navegação no topo e executa a página escolhida (pasta paginas/).
"""

from pathlib import Path

import streamlit as st

import db
from componentes import aplicar_estilo, exibir_avisos, iniciar_filtros, rodape

RAIZ = Path(__file__).parent

st.set_page_config(
    page_title="Boa Safra · Controle de Mercadorias",
    page_icon=":material/inventory_2:",
    layout="wide",
    initial_sidebar_state="collapsed",
)
aplicar_estilo()
db.banco()          # cache_resource: só cria/abre o SQLite uma vez por servidor
iniciar_filtros()   # período e categorias compartilhados entre as páginas

paginas = {
    "": [
        st.Page("paginas/painel.py", title="Painel", icon=":material/space_dashboard:", default=True),
        st.Page("paginas/movimentacoes.py", title="Movimentações", icon=":material/swap_horiz:"),
        st.Page("paginas/estoque.py", title="Estoque", icon=":material/inventory_2:"),
        st.Page("paginas/produtos.py", title="Produtos", icon=":material/category:"),
    ],
    "IA & projeto": [
        st.Page("paginas/importar_ia.py", title="Importar nota com IA", icon=":material/auto_awesome:"),
        st.Page("paginas/sobre.py", title="Sobre o projeto", icon=":material/info:"),
    ],
}
pagina = st.navigation(paginas, position="top")
st.logo(str(RAIZ / "estilo" / "logo.svg"), size="large")

exibir_avisos()  # toasts agendados antes de um st.rerun()
pagina.run()
rodape()
