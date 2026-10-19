"""Gráficos Plotly no padrão visual do app (fundo transparente, fontes do tema,
separador decimal brasileiro). As páginas chamam estas funções e exibem com
mostrar()."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

VERDE, VERDE_CLARO, TERRACOTA, MOSTARDA = "#1F6F50", "#8DBFA6", "#D9663A", "#C98A1B"
TEXTO, GRADE = "#2B2420", "#ECE4D7"
PALETA = [VERDE, TERRACOTA, MOSTARDA, "#5B8C85", "#8C5E3C", "#A7C4A0", "#C9A27E", "#3E4E50"]
COR_CLASSE = {"A": VERDE, "B": MOSTARDA, "C": "#C9BBA8"}


def _layout(fig: go.Figure, altura: int = 340) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", color=TEXTO, size=13),
        separators=",.",  # vírgula decimal, ponto de milhar
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(bgcolor="#FFFEFB", bordercolor=GRADE, font_color=TEXTO),
        colorway=PALETA,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRADE, tickcolor=GRADE, automargin=True)
    fig.update_yaxes(gridcolor=GRADE, zeroline=False, automargin=True)
    return fig


def mostrar(fig: go.Figure) -> None:
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False, "locale": "pt-BR"})


def entradas_x_saidas(serie: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for coluna, cor, preenchimento in [("Entrada", VERDE, "tozeroy"), ("Saída", TERRACOTA, "none")]:
        fig.add_scatter(x=serie["data"], y=serie[coluna], name=coluna + "s", mode="lines+markers",
                        line=dict(color=cor, width=2.6, shape="spline", smoothing=0.5),
                        marker=dict(size=5), fill=preenchimento, fillcolor="rgba(31,111,80,.10)",
                        hovertemplate="%{x|%d/%m/%Y}<br>R$ %{y:,.0f}<extra>" + coluna + "s</extra>")
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f", rangemode="tozero")
    fig.update_layout(hovermode="x unified")
    return _layout(fig)


def top_produtos(df: pd.DataFrame) -> go.Figure:
    df = df.sort_values("valor")
    fig = go.Figure(go.Bar(
        x=df["valor"], y=df["nome"], orientation="h", marker_color=VERDE,
        marker=dict(cornerradius=6),
        customdata=df[["quantidade", "unidade"]],
        hovertemplate="%{y}<br>R$ %{x:,.0f} · %{customdata[0]:,.1f} %{customdata[1]}<extra></extra>",
    ))
    fig.update_xaxes(tickprefix="R$ ", tickformat=",.0f", showgrid=True, gridcolor=GRADE)
    fig.update_yaxes(showgrid=False, ticksuffix="  ")
    return _layout(fig, 380)


def valor_por_categoria(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Pie(
        labels=df["categoria"], values=df["valor_estoque"], hole=0.62, sort=True,
        marker=dict(colors=PALETA, line=dict(color="#FBF8F3", width=3)),
        textinfo="percent", textfont=dict(color="#FFFFFF"),
        hovertemplate="%{label}<br>R$ %{value:,.0f} (%{percent})<extra></extra>",
    ))
    total = df["valor_estoque"].sum()
    fig.add_annotation(text=f"<b>R$ {total/1000:,.0f} mil</b><br><span style='font-size:11px'>em estoque</span>",
                       showarrow=False, font=dict(family="Fraunces, serif", size=17, color=TEXTO))
    fig.update_layout(legend=dict(orientation="v", x=1.0, y=0.5, yanchor="middle"))
    return _layout(fig, 380)


def pareto_abc(abc: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=abc["posicao"], y=abc["valor"], name="Valor",
                marker_color=abc["classe"].map(COR_CLASSE), customdata=abc[["classe"]].assign(nome=abc.index),
                hovertemplate="%{customdata[1]}<br>Classe %{customdata[0]} · R$ %{y:,.0f}<extra></extra>")
    fig.add_scatter(x=abc["posicao"], y=abc["acumulado"], name="% acumulado", yaxis="y2",
                    mode="lines", line=dict(color=TEXTO, width=2),
                    hovertemplate="%{y:.1f}% acumulado<extra></extra>")
    for limite in (80, 95):
        fig.add_hline(y=limite, yref="y2", line=dict(color=TERRACOTA, dash="dot", width=1),
                      annotation_text=f"{limite}%", annotation_position="top right",
                      annotation_font=dict(color=TERRACOTA, size=11))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105], ticksuffix="%",
                                  showgrid=False, automargin=True),
                      xaxis_title="Produtos ordenados por valor", bargap=0.15)
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f", selector=dict(anchor="x"))
    return _layout(fig, 380)


def niveis_estoque(df: pd.DataFrame) -> go.Figure:
    """Barras de saldo x mínimo dos produtos em alerta."""
    fig = go.Figure()
    fig.add_bar(y=df["nome"], x=df["estoque_minimo"], name="Estoque mínimo", orientation="h",
                marker_color="#E7DFD2")
    fig.add_bar(y=df["nome"], x=df["saldo"], name="Saldo atual", orientation="h",
                marker_color=TERRACOTA, width=0.45)
    fig.update_layout(barmode="overlay")
    return _layout(fig, max(220, 34 * len(df) + 80))
