"""Gera a base FICTÍCIA da "Distribuidora Boa Safra" em dados/estoque.db.

Simula ~6 meses de operação, sempre relativos à data de hoje:
- compras semanais por fornecedor quando o saldo cai abaixo de 2x o mínimo;
- vendas diárias (seg a sáb) para restaurantes, padarias e lanchonetes;
- perdas, transferências e devoluções de clientes esporádicas;
- alguns fornecedores "atrasam" no último mês (produtos abaixo do mínimo ou
  zerados) e alguns lotes chegam com validade curta (alerta de vencimento).

As vendas nunca passam do saldo, então o histórico é coerente com a regra
de negócio do app. Rodar manualmente (opcional — o app cria sozinho):
    python gerar_dados.py          # recria do zero
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from db import CAMINHO_DB, criar_tabelas

DIAS_HISTORICO = 182

# (nome, unidade, custo, demanda média/dia, validade em dias ou None)
CATALOGO: dict[str, dict] = {
    "Mercearia": {"prefixo": "MER", "fornecedor": "Grãos do Vale Alimentos", "entrega": [1], "itens": [
        ("Arroz branco tipo 1 5 kg", "un", 22.90, 18, 365),
        ("Feijão carioca 1 kg", "un", 7.40, 25, 270),
        ("Açúcar refinado 5 kg", "un", 19.50, 8, 540),
        ("Óleo de soja 900 ml", "un", 6.80, 20, 360),
        ("Farinha de trigo 5 kg", "un", 21.00, 6, 180),
        ("Macarrão espaguete 500 g (cx 20 un)", "cx", 62.00, 2, 540),
        ("Sal refinado 1 kg", "un", 2.10, 6, None),
        ("Café torrado e moído 500 g", "un", 16.90, 10, 300),
        ("Molho de tomate bag 2 kg", "un", 11.50, 7, 365),
        ("Azeite extravirgem 500 ml", "un", 29.90, 3, 540),
        ("Farinha de mandioca 1 kg", "un", 6.20, 3, 240),
        ("Fubá mimoso 1 kg", "un", 4.10, 3, 180),
        ("Vinagre de álcool 750 ml (cx 12 un)", "cx", 26.40, 1, None),
    ]},
    "Laticínios": {"prefixo": "LAT", "fornecedor": "Laticínios Campo Bom", "entrega": [0, 3], "itens": [
        ("Leite integral UHT 1 L (cx 12 un)", "cx", 54.00, 10, 120),
        ("Queijo muçarela fatiado", "kg", 34.90, 12, 60),
        ("Requeijão culinário 1,5 kg", "un", 27.50, 5, 75),
        ("Manteiga com sal 500 g", "un", 22.80, 4, 90),
        ("Creme de leite 200 g (cx 27 un)", "cx", 81.00, 1.2, 180),
        ("Iogurte natural 1 kg", "un", 9.80, 6, 40),
        ("Queijo parmesão ralado 1 kg", "kg", 68.00, 1.5, 120),
        ("Leite condensado 395 g (cx 27 un)", "cx", 132.00, 0.8, 240),
    ]},
    "Carnes": {"prefixo": "CAR", "fornecedor": "Frigorífico Boi Nobre", "entrega": [2], "itens": [
        ("Peito de frango congelado", "kg", 13.90, 40, 365),
        ("Carne moída bovina congelada", "kg", 27.90, 25, 180),
        ("Alcatra bovina resfriada a vácuo", "kg", 44.90, 12, 60),
        ("Linguiça toscana congelada", "kg", 18.50, 15, 180),
        ("Bacon em manta", "kg", 32.00, 5, 90),
        ("Filé de tilápia congelado", "kg", 39.90, 6, 365),
        ("Costela bovina congelada", "kg", 24.90, 10, 365),
    ]},
    "Congelados": {"prefixo": "CON", "fornecedor": "Gelado Sul Congelados", "entrega": [3], "itens": [
        ("Batata pré-frita 2,5 kg", "un", 24.90, 14, 365),
        ("Pão de queijo congelado 1 kg", "un", 17.50, 9, 180),
        ("Polpa de morango 1 kg", "un", 12.90, 5, 365),
        ("Polpa de maracujá 1 kg", "un", 13.90, 5, 365),
        ("Sorvete de creme 10 L", "un", 89.00, 1, 365),
        ("Hambúrguer bovino 120 g (cx 36 un)", "cx", 98.00, 1.5, 270),
        ("Mix de legumes congelados 1 kg", "un", 11.40, 4, 365),
    ]},
    "Hortifrúti": {"prefixo": "HOR", "fornecedor": "Hortifrúti Cinturão Verde", "entrega": [0, 2, 4], "itens": [
        ("Tomate italiano", "kg", 5.90, 30, None),
        ("Cebola", "kg", 3.80, 25, None),
        ("Batata inglesa", "kg", 4.20, 30, None),
        ("Alface crespa", "un", 2.50, 20, None),
        ("Limão tahiti", "kg", 4.90, 10, None),
        ("Alho descascado", "kg", 24.00, 3, None),
        ("Banana prata", "kg", 5.20, 15, None),
    ]},
    "Bebidas": {"prefixo": "BEB", "fornecedor": "Bebidas Rio Claro Distribuição", "entrega": [1, 4], "itens": [
        ("Refrigerante cola 2 L (fardo 6 un)", "cx", 42.00, 6, 180),
        ("Refrigerante guaraná 2 L (fardo 6 un)", "cx", 33.00, 5, 180),
        ("Água mineral 500 ml (fardo 12 un)", "cx", 13.80, 8, 365),
        ("Suco de laranja integral", "L", 9.90, 10, 60),
        ("Cerveja lata 350 ml (cx 12 un)", "cx", 38.40, 7, 270),
        ("Água com gás 500 ml (fardo 12 un)", "cx", 16.20, 2, 365),
        ("Chá mate 1,5 L", "un", 6.90, 3, 120),
    ]},
    "Limpeza": {"prefixo": "LIM", "fornecedor": "Higiclean Distribuidora", "entrega": [4], "itens": [
        ("Detergente neutro galão 5 L", "un", 14.90, 3, None),
        ("Desinfetante galão 5 L", "un", 16.50, 2, None),
        ("Álcool 70%", "L", 7.90, 4, None),
        ("Sabão em pó 5 kg", "un", 39.00, 1, None),
        ("Esponja dupla face (pct 10 un)", "un", 8.90, 2, None),
        ("Saco de lixo 100 L (rolo 50 un)", "un", 24.00, 3, None),
    ]},
    "Descartáveis": {"prefixo": "DES", "fornecedor": "EmbalaFácil Descartáveis", "entrega": [2], "itens": [
        ("Copo descartável 200 ml (cx 2.500 un)", "cx", 98.00, 0.5, None),
        ("Guardanapo de papel (pct 1.000 un)", "un", 12.50, 4, None),
        ("Marmitex alumínio nº 8 (cx 100 un)", "cx", 34.00, 2, None),
        ("Luva descartável (cx 100 un)", "cx", 21.00, 2, None),
        ("Papel toalha interfolha (fardo 1.000 fl)", "un", 18.90, 2, None),
        ("Filme PVC 28 cm x 300 m", "un", 32.00, 0.6, None),
        ("Pote plástico 500 ml c/ tampa (cx 50 un)", "cx", 45.00, 1, None),
    ]},
}

CLIENTES = ["Restaurante Sabor da Serra", "Cantina Bella Nonna", "Padaria Pão Dourado",
            "Lanchonete Esquina 23", "Hotel Recanto das Águas", "Bistrô Alecrim",
            "Pizzaria Forno a Lenha", "Refeitório Metalfix", "Buffet Doce Festa",
            "Mercadinho Bom Preço", "Hamburgueria Brasa & Pão", "Café Grão Fino"]
DESTINOS_TRANSF = ["CD Filial Norte", "Loja Centro"]
MOTIVOS_PERDA = ["Avaria no transporte", "Produto vencido", "Quebra na armazenagem"]

# Produtos cujo fornecedor "atrasou" (sem compras nos últimos N dias)
ATRASOS = {"LAT-0002": 45, "BEB-0004": 40, "CAR-0003": 15, "MER-0008": 12,
           "CON-0002": 17, "DES-0003": 30, "LIM-0003": 16}
# Produtos que recebem um lote com validade curta na última compra
VALIDADE_CURTA = ["MER-0005", "CON-0006", "CAR-0005", "BEB-0003", "LAT-0003"]


def _arredondar(qtd: float, unidade: str) -> float:
    return float(max(1, round(qtd))) if unidade in ("un", "cx") else round(qtd, 1)


def montar_produtos(rng: random.Random) -> list[dict]:
    produtos = []
    for categoria, info in CATALOGO.items():
        for n, (nome, unidade, custo, demanda, validade) in enumerate(info["itens"], start=1):
            produtos.append({
                "sku": f"{info['prefixo']}-{n:04d}", "nome": nome, "categoria": categoria,
                "unidade": unidade, "custo_unitario": custo,
                "preco_venda": round(custo * rng.uniform(1.25, 1.45), 2),
                "estoque_minimo": _arredondar(demanda * 7, unidade),  # ~1 semana de giro
                "fornecedor": info["fornecedor"], "controla_validade": int(validade is not None),
                "_demanda": demanda, "_validade": validade, "_entrega": info["entrega"],
            })
    return produtos


def criar_banco(caminho: Path = CAMINHO_DB, hoje: date | None = None, semente: int = 42) -> None:
    hoje = hoje or date.today()
    rng = random.Random(semente)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.unlink(missing_ok=True)

    con = sqlite3.connect(temporario)
    criar_tabelas(con)
    produtos = montar_produtos(rng)
    for i, p in enumerate(produtos, start=1):
        p["id"] = i
        con.execute(
            "INSERT INTO produtos (id, sku, nome, categoria, unidade, estoque_minimo, custo_unitario, "
            "preco_venda, fornecedor, controla_validade) VALUES (:id, :sku, :nome, :categoria, "
            ":unidade, :estoque_minimo, :custo_unitario, :preco_venda, :fornecedor, :controla_validade)",
            p)

    movs: list[tuple] = []   # (id, tipo, motivo, data, documento, parceiro, observacao, origem)
    itens: list[tuple] = []  # (mov_id, produto_id, qtd, custo, preco, lote, validade)
    saldo = {p["id"]: 0.0 for p in produtos}
    nota = {info["fornecedor"]: rng.randint(10_000, 60_000) for info in CATALOGO.values()}
    ultima_compra: dict[int, int] = {}  # produto_id -> índice do item na lista
    inicio = hoje - timedelta(days=DIAS_HISTORICO)
    pedido = 0

    def nova_mov(tipo, motivo, dia, documento, parceiro, obs=None, origem="manual"):
        movs.append((len(movs) + 1, tipo, motivo, dia.isoformat(), documento, parceiro, obs, origem))
        return len(movs)

    def entrada_item(mov_id, p, qtd, dia, lote_prefixo="L"):
        validade = None
        if p["_validade"]:
            validade = (dia + timedelta(days=int(p["_validade"] * rng.uniform(0.85, 1.1)))).isoformat()
        custo = round(p["custo_unitario"] * rng.uniform(0.95, 1.05), 2)
        lote = f"{lote_prefixo}{dia:%y%m%d}-{p['id']:02d}" if p["_validade"] else None
        itens.append((mov_id, p["id"], qtd, custo, None, lote, validade))
        saldo[p["id"]] = round(saldo[p["id"]] + qtd, 3)
        return len(itens) - 1

    def saida_item(mov_id, p, qtd, preco=True):
        qtd = round(min(qtd, saldo[p["id"]]), 3)
        if qtd <= 0:
            return False
        itens.append((mov_id, p["id"], qtd, p["custo_unitario"],
                      p["preco_venda"] if preco else None, None, None))
        saldo[p["id"]] = round(saldo[p["id"]] - qtd, 3)
        return True

    # Carga inicial entre 1,6x e 3,5x o mínimo (estoques "dessincronizados", como na vida real)
    for fornecedor in nota:
        mov = nova_mov("Entrada", "Compra", inicio, f"NF {nota[fornecedor]}", fornecedor,
                       "Saldo de implantação do sistema", "carga inicial")
        for p in (x for x in produtos if x["fornecedor"] == fornecedor):
            entrada_item(mov, p, _arredondar(p["estoque_minimo"] * rng.uniform(1.6, 3.5), p["unidade"]), inicio)

    for d in range(1, DIAS_HISTORICO + 1):
        dia = inicio + timedelta(days=d)
        restante = (hoje - dia).days
        crescimento = 0.9 + 0.2 * d / DIAS_HISTORICO        # leve crescimento no semestre
        semana = {4: 1.15, 5: 1.25, 6: 0.0}.get(dia.weekday(), 1.0)  # sex/sáb fortes, domingo fechado

        # --- compras: cada fornecedor entrega em dias fixos da semana
        for fornecedor in nota:
            candidatos = [p for p in produtos if p["fornecedor"] == fornecedor
                          and dia.weekday() in p["_entrega"]
                          and not (p["sku"] in ATRASOS and restante <= ATRASOS[p["sku"]])
                          and saldo[p["id"]] < 2 * p["estoque_minimo"]]
            if not candidatos:
                continue
            nota[fornecedor] += rng.randint(3, 40)
            mov = nova_mov("Entrada", "Compra", dia, f"NF {nota[fornecedor]}", fornecedor)
            for p in candidatos:
                alvo = rng.uniform(2.8, 4.0) * p["estoque_minimo"]
                qtd = _arredondar(alvo - saldo[p["id"]], p["unidade"])
                ultima_compra[p["id"]] = entrada_item(mov, p, qtd, dia)

        if semana == 0:
            continue

        # --- vendas do dia, distribuídas entre 4 a 7 pedidos
        n_pedidos = rng.randint(4, 7)
        ids_pedidos = []
        for _ in range(n_pedidos):
            pedido += 1
            ids_pedidos.append(nova_mov("Saída", "Venda", dia, f"PED-{pedido:06d}", rng.choice(CLIENTES)))
        usados = set()
        for p in produtos:
            media = p["_demanda"] * crescimento * semana
            qtd = _arredondar(max(0.0, rng.gauss(media, media * 0.35)), p["unidade"])
            if qtd > 0 and rng.random() < min(1.0, 0.6 + media / 10):
                mov = rng.choice(ids_pedidos)
                if saida_item(mov, p, qtd):
                    usados.add(mov)
        # pedido que ficou sem item (produto zerado) é descartado
        for mov in ids_pedidos:
            if mov not in usados:
                movs[mov - 1] = None

        # --- eventos esporádicos
        if rng.random() < 0.14:  # perda de perecível
            p = rng.choice([x for x in produtos if x["_validade"] or x["categoria"] == "Hortifrúti"])
            mov = nova_mov("Saída", "Perda", dia, None, "Descarte", rng.choice(MOTIVOS_PERDA))
            if not saida_item(mov, p, _arredondar(p["estoque_minimo"] * 0.08, p["unidade"]), preco=False):
                movs[mov - 1] = None
        if rng.random() < 0.07:  # transferência para filial
            pedido += 1
            mov = nova_mov("Saída", "Transferência", dia, f"TRF-{pedido:06d}", rng.choice(DESTINOS_TRANSF))
            ok = [saida_item(mov, p, _arredondar(p["estoque_minimo"] * 0.4, p["unidade"]), preco=False)
                  for p in rng.sample(produtos, 3)]
            if not any(ok):
                movs[mov - 1] = None
        if rng.random() < 0.08:  # devolução de cliente
            p = rng.choice(produtos)
            mov = nova_mov("Entrada", "Devolução de cliente", dia, f"DEV-{d:04d}", rng.choice(CLIENTES),
                           "Pedido entregue em duplicidade")
            entrada_item(mov, p, _arredondar(p["estoque_minimo"] * 0.1, p["unidade"]), dia, "DV")

    # Lotes com validade curta na última compra de alguns produtos
    for sku in VALIDADE_CURTA:
        p = next(x for x in produtos if x["sku"] == sku)
        if p["id"] in ultima_compra:
            i = ultima_compra[p["id"]]
            itens[i] = itens[i][:6] + ((hoje + timedelta(days=rng.randint(6, 26))).isoformat(),)

    # remove cabeçalhos descartados e renumera os itens
    novos_ids, validos = {}, []
    for mov in movs:
        if mov is not None:
            novos_ids[mov[0]] = len(validos) + 1
            validos.append((novos_ids[mov[0]],) + mov[1:])
    con.executemany("INSERT INTO movimentacoes (id, tipo, motivo, data, documento, parceiro, "
                    "observacao, origem) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", validos)
    con.executemany("INSERT INTO itens_movimentacao (movimentacao_id, produto_id, quantidade, "
                    "custo_unitario, preco_unitario, lote, validade) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(novos_ids[i[0]],) + i[1:] for i in itens if i[0] in novos_ids])
    con.commit()
    con.close()
    temporario.replace(caminho)  # só "publica" o arquivo quando está completo


if __name__ == "__main__":
    CAMINHO_DB.unlink(missing_ok=True)
    criar_banco()
    con = sqlite3.connect(CAMINHO_DB)
    for tabela in ("produtos", "movimentacoes", "itens_movimentacao"):
        print(f"{tabela}: {con.execute(f'SELECT COUNT(*) FROM {tabela}').fetchone()[0]} registros")
    print(f"Banco gerado em {CAMINHO_DB}")
