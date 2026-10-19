"""Filtros globais (período e categorias) guardados no Session State.

Widgets do Streamlit apagam o próprio valor quando a página muda. Para os
filtros valerem em todas as páginas, o valor "oficial" fica em chaves
próprias (filtro_periodo, filtro_categorias) e cada widget usa uma chave
espelho (_w_...) que é sincronizada por callback.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from servicos.estoque import CATEGORIAS

ATALHOS = {"30 dias": 30, "90 dias": 90, "6 meses": 182}
ATALHO_PADRAO = "90 dias"


def iniciar_filtros() -> None:
    hoje = date.today()
    st.session_state.setdefault("filtro_periodo", (hoje - timedelta(days=ATALHOS[ATALHO_PADRAO] - 1), hoje))
    st.session_state.setdefault("filtro_categorias", [])
    st.session_state.setdefault("filtro_atalho", ATALHO_PADRAO)


def filtros_atuais() -> tuple[date, date, list[str]]:
    inicio, fim = st.session_state.filtro_periodo
    return inicio, fim, st.session_state.filtro_categorias


def _ao_mudar_atalho() -> None:
    atalho = st.session_state._w_atalho
    st.session_state.filtro_atalho = atalho
    if atalho:
        hoje = date.today()
        st.session_state.filtro_periodo = (hoje - timedelta(days=ATALHOS[atalho] - 1), hoje)


def _ao_mudar_periodo() -> None:
    valor = st.session_state._w_periodo
    if isinstance(valor, (tuple, list)) and len(valor) == 2:  # ignora seleção pela metade
        st.session_state.filtro_periodo = tuple(valor)
        st.session_state.filtro_atalho = None


def _ao_mudar_categorias() -> None:
    st.session_state.filtro_categorias = st.session_state._w_categorias


def barra_filtros(com_periodo: bool = True, data_minima: date | None = None) -> None:
    """Desenha a barra de filtros. Os valores persistem entre páginas."""
    # espelha o valor oficial para os widgets antes de desenhá-los
    st.session_state._w_atalho = st.session_state.filtro_atalho
    parcial = st.session_state.get("_w_periodo")
    if not (isinstance(parcial, (tuple, list)) and len(parcial) == 1):  # não atrapalha quem está escolhendo
        st.session_state._w_periodo = st.session_state.filtro_periodo
    st.session_state._w_categorias = st.session_state.filtro_categorias

    with st.container(key="barra_filtros"):
        colunas = st.columns([1.25, 1.35, 2.2] if com_periodo else [1])
        if com_periodo:
            colunas[0].segmented_control("Atalhos", list(ATALHOS), key="_w_atalho",
                                         on_change=_ao_mudar_atalho)
            colunas[1].date_input("Período", key="_w_periodo", on_change=_ao_mudar_periodo,
                                  min_value=data_minima, max_value=date.today(), format="DD/MM/YYYY")
        colunas[-1].multiselect("Categorias", CATEGORIAS, key="_w_categorias",
                                on_change=_ao_mudar_categorias, placeholder="Todas as categorias")
