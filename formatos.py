"""Formatação no padrão brasileiro (R$ 1.234,56 · 12,5 kg · 19/10/2026)."""

from __future__ import annotations

import math

import pandas as pd


def _br(numero: float, casas: int) -> str:
    texto = f"{numero:,.{casas}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def moeda(valor: float, casas: int = 2) -> str:
    return f"R$ {_br(valor, casas)}"


def moeda_curta(valor: float) -> str:
    """R$ 12,3 mil · R$ 1,2 mi — para cartões de KPI."""
    if abs(valor) >= 1_000_000:
        return f"R$ {_br(valor / 1_000_000, 1)} mi"
    if abs(valor) >= 10_000:
        return f"R$ {_br(valor / 1_000, 1)} mil"
    return moeda(valor, 0)


def numero(valor: float, casas: int = 0) -> str:
    return _br(valor, casas)


def numero_flex(valor: float) -> str:
    """87 ou 74,3 — inteiro sem casas, fracionado com 1 casa."""
    return _br(valor, 0) if math.isclose(valor, round(valor)) else _br(valor, 1)


def quantidade(valor: float, unidade: str) -> str:
    """Inteiro para un/cx, até 1 casa para kg/L."""
    if unidade in ("un", "cx") or math.isclose(valor, round(valor)):
        return f"{_br(valor, 0)} {unidade}"
    return f"{_br(valor, 1)} {unidade}"


def percentual(valor: float, casas: int = 1) -> str:
    return f"{_br(valor, casas)}%"


def data_br(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return pd.Timestamp(valor).strftime("%d/%m/%Y")
