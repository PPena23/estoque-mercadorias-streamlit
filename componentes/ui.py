"""Componentes visuais reutilizáveis (HTML + CSS do estilo/estilo.css).

Cada função recebe dados já prontos e só cuida da apresentação. As páginas
ficam curtas e o visual fica consistente em todo o app.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from formatos import percentual
from servicos.estoque import ABAIXO, OK, STATUS, VENCENDO, ZERADO

CSS = Path(__file__).parent.parent / "estilo" / "estilo.css"

CLASSE_STATUS = {OK: "ok", ABAIXO: "abaixo", ZERADO: "zerado", VENCENDO: "vencendo"}
# mesmas cores dos badges, para tabelas (Styler) e gráficos
COR_STATUS = {OK: ("#E3F0E9", "#144D37"), ABAIXO: ("#FBF0D9", "#8A5A0B"),
              ZERADO: ("#FBE6DC", "#A4401C"), VENCENDO: ("#F1E7F3", "#7B4A86")}
# situações da conferência de saída reaproveitam as mesmas cores
COR_STATUS |= {"Excede o saldo": COR_STATUS[ZERADO], "Fica abaixo do mínimo": COR_STATUS[ABAIXO]}


def aplicar_estilo() -> None:
    """Injeta o CSS. st.html só com <style> não ocupa espaço na página."""
    st.html(f"<style>{CSS.read_text(encoding='utf-8')}</style>")


def cabecalho_pagina(titulo: str, subtitulo: str, sobretitulo: str, lateral: str = "") -> None:
    st.html(f"""
    <section class="faixa">
      <div style="position:relative;z-index:1">
        <div class="faixa__sobre">{escape(sobretitulo)}</div>
        <h1 class="faixa__titulo">{escape(titulo)}</h1>
        <p class="faixa__sub">{escape(subtitulo)}</p>
      </div>
      <div class="faixa__lado">{lateral}</div>
    </section>""")


def titulo_secao(titulo: str, legenda: str = "") -> None:
    legenda_html = f'<p class="secao__legenda">{escape(legenda)}</p>' if legenda else ""
    st.html(f'<div class="secao"><h3 class="secao__titulo">{escape(titulo)}</h3>{legenda_html}</div>')


def _delta_html(delta_pct: float | None, bom_quando: str) -> str:
    if delta_pct is None or pd.isna(delta_pct):
        return '<span class="delta delta--neutro">sem base</span>'
    if abs(delta_pct) < 0.05:
        return '<span class="delta delta--neutro">= 0%</span>'
    subiu = delta_pct > 0
    if bom_quando == "neutro":
        classe = "neutro"
    else:
        classe = "bom" if subiu == (bom_quando == "alta") else "ruim"
    seta = "▲" if subiu else "▼"
    return f'<span class="delta delta--{classe}">{seta} {percentual(abs(delta_pct))}</span>'


def kpi_card(rotulo: str, valor: str, delta_pct: float | None = None, *,
             bom_quando: str = "alta", rodape: str = "", alerta: bool = False,
             com_delta: bool = True) -> str:
    """Devolve o HTML de um cartão; use grade_kpis() para renderizar vários lado a lado.

    bom_quando: "alta" (ex.: faturamento), "baixa" (ex.: perdas) ou "neutro" define a cor da variação.
    """
    delta = _delta_html(delta_pct, bom_quando) if com_delta else ""
    return f"""
    <div class="kpi{' kpi--alerta' if alerta else ''}">
      <div class="kpi__rotulo">{escape(rotulo)}</div>
      <div class="kpi__valor">{escape(valor)}</div>
      <div class="kpi__rodape">{delta}<span>{escape(rodape)}</span></div>
    </div>"""


def grade_kpis(cartoes: list[str]) -> None:
    st.html(f'<div class="kpis">{"".join(cartoes)}</div>')


def status_badge(status: str, texto: str | None = None) -> str:
    return f'<span class="badge badge--{CLASSE_STATUS.get(status, "ok")}">{escape(texto or status)}</span>'


def resumo_status(contagem: dict[str, int], total: int) -> None:
    """Linha de badges: '62 produtos · ● 50 OK · ● 3 Zerado ...' (cor + texto)."""
    badges = "".join(status_badge(s, f"{contagem.get(s, 0)} · {s}") for s in STATUS)
    st.html(f'<div class="badges"><span class="badges__total">{total} produtos</span>{badges}</div>')


def estado_vazio(titulo: str, texto: str, icone: str = "📦") -> None:
    st.html(f"""
    <div class="vazio">
      <div class="vazio__icone">{icone}</div>
      <div class="vazio__titulo">{escape(titulo)}</div>
      <div>{escape(texto)}</div>
    </div>""")


def lista_insights(observacoes: list[str]) -> None:
    itens = "".join(
        f'<div class="insight"><span class="insight__n">{i:02d}</span><span>{escape(t)}</span></div>'
        for i, t in enumerate(observacoes, start=1))
    st.html(itens)


def rodape() -> None:
    st.html("""
    <div class="rodape">
      <span>Dados 100% fictícios · projeto de portfólio</span>
      <span>Feito por Pedro Pena ·
        <a href="https://www.linkedin.com/in/pedropena23/" target="_blank">LinkedIn</a> ·
        <a href="https://github.com/PPena23" target="_blank">GitHub</a></span>
    </div>""")
