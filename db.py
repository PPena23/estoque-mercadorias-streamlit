"""Camada de dados: todo o SQL do app mora aqui.

- Banco SQLite em dados/estoque.db, criado e populado automaticamente na
  primeira execução (assim o app sobe sozinho no Streamlit Community Cloud).
- @st.cache_resource guarda UMA conexão para o servidor inteiro.
- @st.cache_data guarda o resultado das consultas; toda escrita chama
  limpar_cache() para que as telas reflitam o dado novo na hora.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
CAMINHO_DB = RAIZ / "dados" / "estoque.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS produtos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sku               TEXT    NOT NULL UNIQUE,
    nome              TEXT    NOT NULL,
    categoria         TEXT    NOT NULL,
    unidade           TEXT    NOT NULL CHECK (unidade IN ('un', 'cx', 'kg', 'L')),
    estoque_minimo    REAL    NOT NULL CHECK (estoque_minimo >= 0),
    custo_unitario    REAL    NOT NULL CHECK (custo_unitario >= 0),
    preco_venda       REAL    NOT NULL CHECK (preco_venda >= 0),
    fornecedor        TEXT    NOT NULL,
    controla_validade INTEGER NOT NULL DEFAULT 0,
    ativo             INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS movimentacoes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo       TEXT NOT NULL CHECK (tipo IN ('Entrada', 'Saída')),
    motivo     TEXT NOT NULL,
    data       TEXT NOT NULL,             -- AAAA-MM-DD
    documento  TEXT,                      -- nº da nota ou do pedido
    parceiro   TEXT,                      -- fornecedor, cliente ou destino
    observacao TEXT,
    origem     TEXT NOT NULL DEFAULT 'manual'  -- manual | ia | carga inicial
);

CREATE TABLE IF NOT EXISTS itens_movimentacao (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    movimentacao_id INTEGER NOT NULL REFERENCES movimentacoes(id) ON DELETE CASCADE,
    produto_id      INTEGER NOT NULL REFERENCES produtos(id),
    quantidade      REAL    NOT NULL CHECK (quantidade > 0),
    custo_unitario  REAL    NOT NULL,
    preco_unitario  REAL,
    lote            TEXT,
    validade        TEXT
);

CREATE INDEX IF NOT EXISTS ix_mov_data ON movimentacoes(data);
CREATE INDEX IF NOT EXISTS ix_itens_mov ON itens_movimentacao(movimentacao_id);
CREATE INDEX IF NOT EXISTS ix_itens_prod ON itens_movimentacao(produto_id);
"""


class EstoqueInsuficiente(Exception):
    """Disparada quando uma saída deixaria o saldo de algum produto negativo."""


@dataclass
class Banco:
    conexao: sqlite3.Connection
    trava: threading.Lock  # o Streamlit atende cada sessão em uma thread


def criar_tabelas(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


@st.cache_resource(show_spinner="Preparando o banco de dados...")
def banco() -> Banco:
    """Abre (e, se preciso, cria e popula) o SQLite uma única vez por servidor."""
    if not CAMINHO_DB.exists():
        from gerar_dados import criar_banco  # import tardio evita ciclo

        criar_banco(CAMINHO_DB)
    con = sqlite3.connect(CAMINHO_DB, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    return Banco(con, threading.Lock())


def _consultar(sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    b = banco()
    with b.trava:
        return pd.read_sql_query(sql, b.conexao, params=params)


def limpar_cache() -> None:
    """Invalida todas as consultas em cache depois de uma escrita."""
    st.cache_data.clear()


# --------------------------------------------------------------------------- leitura

@st.cache_data(ttl=600, show_spinner=False)
def ler_produtos(incluir_inativos: bool = False) -> pd.DataFrame:
    sql = "SELECT * FROM produtos" + ("" if incluir_inativos else " WHERE ativo = 1")
    df = _consultar(sql + " ORDER BY categoria, nome")
    df["controla_validade"] = df["controla_validade"].astype(bool)
    df["ativo"] = df["ativo"].astype(bool)
    return df


@st.cache_data(ttl=600, show_spinner=False)
def ler_itens() -> pd.DataFrame:
    """Uma linha por item movimentado, já com dados do cabeçalho e do produto."""
    df = _consultar("""
        SELECT m.id AS movimentacao_id, m.tipo, m.motivo, m.data, m.documento,
               m.parceiro, m.origem, i.id AS item_id, i.produto_id, p.sku, p.nome,
               p.categoria, p.unidade, i.quantidade, i.custo_unitario,
               i.preco_unitario, i.lote, i.validade
          FROM itens_movimentacao i
          JOIN movimentacoes m ON m.id = i.movimentacao_id
          JOIN produtos p      ON p.id = i.produto_id
         ORDER BY m.data, m.id, i.id
    """)
    df["data"] = pd.to_datetime(df["data"])
    df["validade"] = pd.to_datetime(df["validade"])
    df["sinal"] = df["tipo"].map({"Entrada": 1, "Saída": -1})
    df["valor_custo"] = df["quantidade"] * df["custo_unitario"]
    return df


def saldos_atuais(produto_ids: list[int]) -> dict[int, float]:
    """Saldo direto do banco, sem cache: usado na validação final de saídas."""
    if not produto_ids:
        return {}
    marcadores = ",".join("?" * len(produto_ids))
    df = _consultar(f"""
        SELECT i.produto_id,
               SUM(CASE WHEN m.tipo = 'Entrada' THEN i.quantidade ELSE -i.quantidade END) AS saldo
          FROM itens_movimentacao i JOIN movimentacoes m ON m.id = i.movimentacao_id
         WHERE i.produto_id IN ({marcadores})
         GROUP BY i.produto_id
    """, tuple(produto_ids))
    saldos = dict(zip(df["produto_id"], df["saldo"]))
    return {pid: round(float(saldos.get(pid, 0.0)), 3) + 0.0 for pid in produto_ids}  # +0.0 evita "-0"


def sku_existe(sku: str, ignorar_id: int | None = None) -> bool:
    df = _consultar("SELECT id FROM produtos WHERE UPPER(sku) = UPPER(?)", (sku,))
    return any(df["id"] != ignorar_id)


# --------------------------------------------------------------------------- escrita

CAMPOS_PRODUTO = ["sku", "nome", "categoria", "unidade", "estoque_minimo",
                  "custo_unitario", "preco_venda", "fornecedor", "controla_validade"]


def inserir_produto(dados: dict) -> int:
    b = banco()
    with b.trava, b.conexao:
        cur = b.conexao.execute(
            f"INSERT INTO produtos ({', '.join(CAMPOS_PRODUTO)}) "
            f"VALUES ({', '.join('?' * len(CAMPOS_PRODUTO))})",
            [dados[c] for c in CAMPOS_PRODUTO],
        )
    limpar_cache()
    return int(cur.lastrowid)


def atualizar_produto(produto_id: int, dados: dict) -> None:
    b = banco()
    with b.trava, b.conexao:
        b.conexao.execute(
            f"UPDATE produtos SET {', '.join(f'{c} = ?' for c in CAMPOS_PRODUTO)} WHERE id = ?",
            [dados[c] for c in CAMPOS_PRODUTO] + [produto_id],
        )
    limpar_cache()


def definir_ativo(produto_id: int, ativo: bool) -> None:
    """Desativar em vez de apagar: o histórico de movimentações continua íntegro."""
    b = banco()
    with b.trava, b.conexao:
        b.conexao.execute("UPDATE produtos SET ativo = ? WHERE id = ?", (int(ativo), produto_id))
    limpar_cache()


def registrar_movimentacao(cabecalho: dict, itens: list[dict]) -> int:
    """Grava cabeçalho + itens numa única transação.

    Para saídas, o saldo é conferido DENTRO da transação (com a trava), então
    duas pessoas não conseguem vender o mesmo último item ao mesmo tempo.
    """
    b = banco()
    with b.trava, b.conexao:
        con = b.conexao
        if cabecalho["tipo"] == "Saída":
            pedido: dict[int, float] = {}
            for item in itens:
                pedido[item["produto_id"]] = pedido.get(item["produto_id"], 0) + item["quantidade"]
            for pid, qtd in pedido.items():
                saldo = con.execute("""
                    SELECT COALESCE(SUM(CASE WHEN m.tipo = 'Entrada' THEN i.quantidade
                                             ELSE -i.quantidade END), 0)
                      FROM itens_movimentacao i JOIN movimentacoes m ON m.id = i.movimentacao_id
                     WHERE i.produto_id = ?""", (pid,)).fetchone()[0]
                saldo = round(saldo, 3)
                if qtd > saldo + 1e-9:
                    raise EstoqueInsuficiente(f"Produto {pid}: saldo {saldo:g}, pedido {qtd:g}.")

        cur = con.execute(
            "INSERT INTO movimentacoes (tipo, motivo, data, documento, parceiro, observacao, origem) "
            "VALUES (:tipo, :motivo, :data, :documento, :parceiro, :observacao, :origem)",
            {"observacao": None, "origem": "manual", **cabecalho},
        )
        mov_id = cur.lastrowid
        con.executemany(
            "INSERT INTO itens_movimentacao (movimentacao_id, produto_id, quantidade, "
            "custo_unitario, preco_unitario, lote, validade) "
            "VALUES (:movimentacao_id, :produto_id, :quantidade, :custo_unitario, "
            ":preco_unitario, :lote, :validade)",
            [{"preco_unitario": None, "lote": None, "validade": None, **i,
              "movimentacao_id": mov_id} for i in itens],
        )
    limpar_cache()
    return int(mov_id)
