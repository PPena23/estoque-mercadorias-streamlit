"""Produtos: catálogo, cadastro e edição com validação em st.form."""

import re

import streamlit as st

import db
from componentes import avisar, cabecalho_pagina, estado_vazio, filtros_atuais
from componentes.tabelas import botoes_exportacao, formato_br
from servicos import estoque as est

PADRAO_SKU = re.compile(r"^[A-Z]{3}-\d{4}$")
PREFIXOS = {"Mercearia": "MER", "Laticínios": "LAT", "Carnes": "CAR", "Congelados": "CON",
            "Hortifrúti": "HOR", "Bebidas": "BEB", "Limpeza": "LIM", "Descartáveis": "DES"}

st.session_state.setdefault("form_prod", 0)
todos = db.ler_produtos(incluir_inativos=True)


def proximo_sku(categoria: str) -> str:
    prefixo = PREFIXOS[categoria]
    numeros = todos.loc[todos["sku"].str.startswith(prefixo), "sku"].str[-4:].astype(int)
    return f"{prefixo}-{(numeros.max() if len(numeros) else 0) + 1:04d}"


def validar(dados: dict, produto_id: int | None = None) -> list[str]:
    erros = []
    if len(dados["nome"]) < 3:
        erros.append("O nome precisa ter pelo menos 3 caracteres.")
    if dados["sku"] and not PADRAO_SKU.match(dados["sku"]):
        erros.append("SKU no formato AAA-0000 (ex.: MER-0014).")
    elif dados["sku"] and db.sku_existe(dados["sku"], ignorar_id=produto_id):
        erros.append(f"Já existe um produto com o SKU {dados['sku']}.")
    if not dados["fornecedor"]:
        erros.append("Informe o fornecedor principal.")
    if dados["preco_venda"] < dados["custo_unitario"]:
        erros.append("O preço de venda está menor que o custo — confira os valores.")
    if dados["unidade"] in ("un", "cx") and dados["estoque_minimo"] != int(dados["estoque_minimo"]):
        erros.append("Para un/cx o estoque mínimo deve ser inteiro.")
    return erros


def formulario(chave: str, atual: dict | None = None) -> dict | None:
    """Formulário único para criar e editar. Devolve os dados só se válidos."""
    atual = atual or {}
    fornecedores = sorted(todos["fornecedor"].unique())
    with st.form(chave):
        c1, c2, c3 = st.columns([2.4, 1.2, 1])
        nome = c1.text_input("Nome do produto *", value=atual.get("nome", ""), max_chars=80)
        categoria = c2.selectbox("Categoria *", est.CATEGORIAS,
                                 index=est.CATEGORIAS.index(atual["categoria"]) if atual else 0)
        sku = c3.text_input("SKU", value=atual.get("sku", ""), placeholder="automático",
                            help="Em branco = próximo código da categoria.", disabled=bool(atual))
        c1, c2, c3, c4 = st.columns(4)
        unidade = c1.selectbox("Unidade *", est.UNIDADES,
                               index=est.UNIDADES.index(atual["unidade"]) if atual else 0)
        minimo = c2.number_input("Estoque mínimo *", min_value=0.0, step=1.0, format="%.1f",
                                 value=float(atual.get("estoque_minimo", 10)))
        custo = c3.number_input("Custo unitário (R$) *", min_value=0.0, step=0.1, format="%.2f",
                                value=float(atual.get("custo_unitario", 0.0)))
        preco = c4.number_input("Preço de venda (R$) *", min_value=0.0, step=0.1, format="%.2f",
                                value=float(atual.get("preco_venda", 0.0)))
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        fornecedor = c1.selectbox("Fornecedor principal *", fornecedores, accept_new_options=True,
                                  index=fornecedores.index(atual["fornecedor"]) if atual else None,
                                  placeholder="Escolha ou digite um novo")
        validade = c2.toggle("Controla validade (lote)", value=bool(atual.get("controla_validade", False)))
        if custo and preco:
            st.caption(f"Margem sobre o preço: {(preco - custo) / preco * 100:.1f}%".replace(".", ",")
                       + " (atualiza ao salvar)")
        enviado = st.form_submit_button("Salvar produto", type="primary", icon=":material/save:")

    if not enviado:
        return None
    dados = {"nome": nome.strip(), "categoria": categoria, "sku": sku.strip().upper(),
             "unidade": unidade, "estoque_minimo": minimo, "custo_unitario": round(custo, 2),
             "preco_venda": round(preco, 2), "fornecedor": (fornecedor or "").strip(),
             "controla_validade": int(validade)}
    erros = validar(dados, atual.get("id"))
    if erros:
        st.error("Corrija antes de salvar:\n\n" + "\n".join(f"- {e}" for e in erros), icon=":material/error:")
        return None
    return dados


@st.dialog("Confirmar alteração")
def confirmar_status(produto: dict) -> None:
    ativar = not produto["ativo"]
    if ativar:
        st.write(f"Reativar **{produto['nome']}**? Ele volta a aparecer nas movimentações.")
    else:
        st.write(f"Desativar **{produto['nome']}** ({produto['sku']})?")
        st.caption("O histórico é preservado; o produto só deixa de aparecer no estoque e nos lançamentos.")
    c1, c2 = st.columns(2)
    if c1.button("Cancelar", width="stretch"):
        st.rerun()
    if c2.button("Reativar" if ativar else "Desativar", type="primary", width="stretch"):
        db.definir_ativo(int(produto["id"]), ativar)
        avisar(f"{produto['nome']} {'reativado' if ativar else 'desativado'}.")
        st.rerun()


cabecalho_pagina("Produtos", "Cadastro de itens com regras de estoque mínimo, preço e validade.",
                 "Cadastros · Catálogo",
                 lateral=f"<strong>{int(todos['ativo'].sum())}</strong> ativos · {int((~todos['ativo']).sum())} inativos")

aba_lista, aba_novo, aba_editar = st.tabs([":material/list: Catálogo", ":material/add: Novo produto",
                                           ":material/edit: Editar / desativar"])

with aba_lista:
    _, _, categorias = filtros_atuais()
    c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
    busca = c1.text_input("Buscar", placeholder="Nome, SKU ou fornecedor", key="prod_busca")
    cats = c2.multiselect("Categorias", est.CATEGORIAS, default=categorias, key="prod_cats",
                          placeholder="Todas")
    inativos = c3.toggle("Mostrar inativos", key="prod_inativos")
    lista = todos if inativos else todos[todos["ativo"]]
    if cats:
        lista = lista[lista["categoria"].isin(cats)]
    if busca:
        alvo = busca.lower()
        lista = lista[lista[["nome", "sku", "fornecedor"]].apply(
            lambda col: col.str.lower().str.contains(alvo, regex=False)).any(axis=1)]
    if lista.empty:
        estado_vazio("Nenhum produto encontrado", "Ajuste a busca ou cadastre um novo produto.", "🏷️")
    else:
        lista = lista.assign(margem=(lista["preco_venda"] - lista["custo_unitario"]) / lista["preco_venda"] * 100)
        colunas = ["sku", "nome", "categoria", "unidade", "estoque_minimo", "custo_unitario",
                   "preco_venda", "margem", "fornecedor", "controla_validade", "ativo"]
        tabela = formato_br(lista[colunas], moedas=["custo_unitario", "preco_venda"], pcts=["margem"],
                            numeros=["estoque_minimo"])
        st.dataframe(tabela, hide_index=True, height=480, column_config={
            "sku": "SKU", "nome": st.column_config.TextColumn("Produto", width="medium"),
            "categoria": "Categoria", "unidade": "Un.",
            "estoque_minimo": "Mínimo", "custo_unitario": "Custo", "preco_venda": "Preço", "margem": "Margem",
            "fornecedor": "Fornecedor",
            "controla_validade": st.column_config.CheckboxColumn("Validade"),
            "ativo": st.column_config.CheckboxColumn("Ativo"),
        })
        botoes_exportacao({"Produtos": lista[colunas]}, "produtos", "prod")

with aba_novo:
    dados = formulario(f"novo_produto_{st.session_state.form_prod}")
    if dados:
        dados["sku"] = dados["sku"] or proximo_sku(dados["categoria"])
        db.inserir_produto(dados)
        avisar(f"Produto {dados['sku']} · {dados['nome']} cadastrado.")
        st.session_state.form_prod += 1
        st.rerun()

with aba_editar:
    rotulos = {f"{r.sku} · {r.nome}{'' if r.ativo else ' (inativo)'}": int(r.id) for r in todos.itertuples()}
    escolha = st.selectbox("Produto", list(rotulos), index=None, placeholder="Busque pelo nome ou SKU",
                           key="prod_editar")
    if not escolha:
        estado_vazio("Escolha um produto", "Selecione acima para editar os dados ou desativá-lo.", "✏️")
    else:
        produto = todos[todos["id"] == rotulos[escolha]].iloc[0].to_dict()
        dados = formulario(f"editar_{produto['id']}_{st.session_state.form_prod}", produto)
        if dados:
            dados["sku"] = produto["sku"]
            db.atualizar_produto(int(produto["id"]), dados)
            avisar(f"{dados['nome']} atualizado.")
            st.session_state.form_prod += 1
            st.rerun()
        acao = "Reativar produto" if not produto["ativo"] else "Desativar produto"
        if st.button(acao, icon=":material/block:" if produto["ativo"] else ":material/restart_alt:"):
            confirmar_status(produto)
