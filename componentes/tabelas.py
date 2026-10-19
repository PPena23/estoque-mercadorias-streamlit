"""Peças reutilizáveis para tabelas: colunas formatadas e exportação."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from componentes.ui import COR_STATUS
from formatos import data_br, moeda, numero_flex, percentual


def formato_br(df: pd.DataFrame, *, moedas=(), numeros=(), pcts=(), datas=(), status: str | None = None):
    """Styler com números no padrão brasileiro (R$ 1.234,56 · 74,3 · 12,5% · 19/10/2026).

    O format do column_config usa printf (ponto decimal); o Styler resolve isso
    só na exibição — a ordenação da tabela continua usando o valor numérico.
    `status` pinta a coluna com as mesmas cores dos badges.
    """
    # datas viram texto dd/mm/aaaa ("—" se vazia): o Styler não troca NaT por na_rep na tela
    df = df.assign(**{c: df[c].map(data_br) for c in datas})
    formatos = ({c: moeda for c in moedas} | {c: numero_flex for c in numeros}
                | {c: percentual for c in pcts})
    estilo = df.style.format(formatos, na_rep="—") if formatos else df.style
    if status:
        def pintar(valor):
            fundo, texto = COR_STATUS.get(valor, ("transparent", "inherit"))
            return f"background-color: {fundo}; color: {texto}; font-weight: 600"
        estilo = estilo.map(pintar, subset=[status])
    return estilo


def col_moeda(rotulo: str, **kwargs):
    """Para grades EDITÁVEIS (data_editor), onde o Styler não se aplica.
    "localized" segue o idioma do navegador (1.234,56 em pt-BR)."""
    return st.column_config.NumberColumn(f"{rotulo} (R$)", format="localized", **kwargs)


def col_qtd(rotulo: str, **kwargs):
    return st.column_config.NumberColumn(rotulo, format="localized", **kwargs)


def col_data(rotulo: str, **kwargs):
    return st.column_config.DateColumn(rotulo, format="DD/MM/YYYY", **kwargs)


def rotulos_produtos(produtos: pd.DataFrame) -> dict[str, int]:
    """'MER-0001 · Arroz branco tipo 1 5 kg' -> id, para caixas de seleção em grades."""
    return {f"{r.sku} · {r.nome}": int(r.id) for r in produtos.itertuples()}


def _excel(planilhas: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        for nome, df in planilhas.items():
            df.to_excel(escritor, sheet_name=nome[:31], index=False)
            folha = escritor.sheets[nome[:31]]
            for coluna in folha.columns:  # largura automática simples
                largura = max(len(str(c.value or "")) for c in coluna[:200])
                folha.column_dimensions[coluna[0].column_letter].width = min(max(10, largura + 2), 48)
    return buffer.getvalue()


def botoes_exportacao(planilhas: dict[str, pd.DataFrame], nome_base: str, chave: str) -> None:
    """CSV (primeira planilha) e Excel (todas). Os arquivos só são gerados no
    clique — data recebe uma função, então o rerun normal não paga esse custo."""
    sufixo = date.today().strftime("%Y%m%d")
    principal = next(iter(planilhas.values()))
    c1, c2 = st.columns(2)
    c1.download_button(
        "CSV", data=lambda: principal.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=f"{nome_base}_{sufixo}.csv", mime="text/csv", icon=":material/download:",
        key=f"csv_{chave}", width="stretch", on_click="ignore")
    c2.download_button(
        "Excel", data=lambda: _excel(planilhas),
        file_name=f"{nome_base}_{sufixo}.xlsx", icon=":material/table_view:", key=f"xlsx_{chave}",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch", on_click="ignore")
