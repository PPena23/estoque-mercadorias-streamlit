"""Importar nota com IA: texto livre -> JSON estruturado (Gemini) -> conferência -> entrada."""

from datetime import date

import pandas as pd
import streamlit as st
from google.genai import errors
from pydantic import ValidationError

import db
from componentes import cabecalho_pagina, estado_vazio, titulo_secao
from componentes.dialogos import confirmar_movimentacao
from componentes.tabelas import col_data, col_moeda, col_qtd, rotulos_produtos
from servicos import estoque as est
from servicos import ia

st.session_state.setdefault("ia_versao", 0)  # muda a key do editor quando chega uma nota nova

produtos = db.ler_produtos()
rotulos = rotulos_produtos(produtos)
rotulo_por_sku = {r.split(" · ")[0]: r for r in rotulos}
unidade_por_id = produtos.set_index("id")["unidade"]
chave = ia.ler_chave()


def carregar_exemplo(nome: str) -> None:
    st.session_state.texto_nota = ia.texto_exemplo(nome)
    st.session_state.exemplo_atual = nome


def guardar_resultado(nota: ia.NotaExtraida, origem: str) -> None:
    grade = ia.casar_itens(nota, produtos)
    grade["produto"] = grade["sku"].map(rotulo_por_sku)
    st.session_state.nota_ia = {"nota": nota.model_dump(), "grade": grade, "origem": origem}
    st.session_state.ia_versao += 1


def descartar() -> None:
    st.session_state.pop("nota_ia", None)
    st.session_state.ia_versao += 1


cabecalho_pagina(
    "Importar nota com IA",
    "Cole o texto de uma nota fiscal ou pedido: o Gemini devolve os dados em JSON estruturado, "
    "o app sugere os SKUs e você confirma antes de lançar a entrada.",
    "Inteligência artificial · Saída estruturada",
    lateral="Gemini · <strong>response_schema</strong> (Pydantic)<br>"
            "casamento de SKU com <strong>difflib</strong>")

# ------------------------------------------------------------------ configuração
if not chave:
    with st.container(key="cartao_setup"):
        st.markdown("#### :material/key: Falta configurar a chave do Gemini")
        st.markdown("""
A extração com IA precisa de uma chave gratuita do Google AI Studio. **O resto do app funciona
normalmente sem ela** — e você ainda pode testar este fluxo com o *modo demonstração* abaixo.

1. Gere a chave em **aistudio.google.com** → *Get API key*.
2. Crie `.streamlit/secrets.toml` (veja `secrets.toml.example`) com `GEMINI_API_KEY = "sua-chave"`,
   ou defina a variável de ambiente `GEMINI_API_KEY`. No Streamlit Cloud: *Settings → Secrets*.
3. Recarregue a página.""")
    modelo = None
else:
    try:
        modelos = ia.modelos_disponiveis(chave)
    except errors.APIError as e:
        st.error(ia.mensagem_erro(e))
        st.stop()
    with st.expander("Configurações da IA", icon=":material/tune:"):
        modelo = st.selectbox("Modelo", modelos, key="modelo_ia", persist_state="session",
                              help="Flash-Lite primeiro: gasta menos da cota gratuita. "
                                   "Também é usado no Resumo inteligente do Painel.")

# ------------------------------------------------------------------ 1. texto
titulo_secao("1. Texto da nota ou do pedido", "Use um dos exemplos fictícios ou cole o seu.")
c1, c2, _ = st.columns([1, 1.4, 1.6])
for col, nome in zip((c1, c2), ia.EXEMPLOS):
    col.button(f"Exemplo: {nome}", on_click=carregar_exemplo, args=(nome,), icon=":material/description:",
               width="stretch")
texto = st.text_area("Texto", key="texto_nota", height=280, persist_state="session", label_visibility="collapsed",
                     placeholder="Cole aqui o conteúdo da nota fiscal, DANFE, e-mail ou pedido...")

b1, b2, _ = st.columns([1, 1.2, 2])
extrair = b1.button("Extrair com IA", type="primary", icon=":material/auto_awesome:",
                    disabled=not (chave and texto.strip()), width="stretch")
exemplo = st.session_state.get("exemplo_atual")
eh_exemplo = bool(exemplo) and texto.strip() == ia.texto_exemplo(exemplo).strip()
simular = b2.button("Modo demonstração (sem IA)", icon=":material/play_circle:", width="stretch",
                    disabled=not eh_exemplo,
                    help="Usa o resultado pré-pronto de um dos exemplos, para ver o fluxo sem chave de API.")

if extrair:
    with st.status("Lendo a nota com o Gemini...", expanded=True) as status:
        try:
            st.write(f"Enviando o texto ao modelo **{modelo}** com o esquema `NotaExtraida`...")
            nota = ia.extrair_nota(chave, modelo, texto)
            st.write(f"JSON validado pelo Pydantic: **{len(nota.itens)} itens** de *{nota.fornecedor}*.")
            st.write("Comparando descrições com o catálogo (difflib)...")
            guardar_resultado(nota, "ia")
            status.update(label="Nota lida — confira os itens abaixo", state="complete", expanded=False)
        except errors.APIError as e:
            status.update(label="Falha na chamada ao Gemini", state="error")
            st.error(ia.mensagem_erro(e))
        except ValidationError:
            status.update(label="Resposta fora do formato esperado", state="error")
            st.error("O modelo devolveu um JSON incompleto. Tente de novo ou outro modelo.")
if simular:
    guardar_resultado(ia.extracao_demonstracao(exemplo), "demonstração")
    st.toast("Resultado de demonstração carregado.", icon=":material/play_circle:")

# ------------------------------------------------------------------ 2. conferência
resultado = st.session_state.get("nota_ia")
st.write("")
titulo_secao("2. Confira e vincule aos produtos",
             "Desmarque o que não deve entrar. Similaridade abaixo de 45% fica sem sugestão de SKU.")
if not resultado:
    estado_vazio("Nenhuma nota lida ainda", "Carregue um exemplo e clique em Extrair com IA.", "🧾")
    st.stop()

nota = resultado["nota"]
with st.container(key="cartao_conferencia"):
    if resultado["origem"] == "demonstração":
        st.caption(":material/info: Dados de demonstração — nenhuma chamada à IA foi feita.")
    c1, c2, c3 = st.columns([2, 1, 1])
    fornecedor = c1.text_input("Fornecedor", value=nota["fornecedor"], key=f"ia_forn_{st.session_state.ia_versao}")
    numero = c2.text_input("Nº do documento", value=nota["numero"], key=f"ia_num_{st.session_state.ia_versao}")
    emissao = pd.to_datetime(nota["data_emissao"], errors="coerce")
    data_mov = c3.date_input("Data da entrada", max_value=date.today(), format="DD/MM/YYYY",
                             value=min(emissao.date(), date.today()) if pd.notna(emissao) else date.today(),
                             key=f"ia_data_{st.session_state.ia_versao}")

    grade = st.data_editor(
        resultado["grade"], hide_index=True, placeholder="", key=f"ia_grade_{st.session_state.ia_versao}",
        column_order=["importar", "descricao", "produto", "similaridade", "quantidade", "unidade_nota",
                      "custo_unitario", "lote", "validade"],
        disabled=["descricao", "similaridade", "unidade_nota"],
        column_config={
            "importar": st.column_config.CheckboxColumn("Lançar", width="small"),
            "descricao": st.column_config.TextColumn("Descrição lida pela IA", width="medium"),
            "produto": st.column_config.SelectboxColumn("Produto no catálogo", options=list(rotulos), width="large"),
            "similaridade": st.column_config.ProgressColumn("Similaridade", min_value=0, max_value=100, format="%d%%"),
            "quantidade": col_qtd("Qtd.", min_value=0.1),
            "unidade_nota": "Un. nota",
            "custo_unitario": col_moeda("Custo unit.", min_value=0.0),
            "lote": "Lote",
            "validade": col_data("Validade"),
        })

    with st.expander("Ver JSON devolvido pela IA", icon=":material/data_object:"):
        st.json(nota)

    selecionados = grade[grade["importar"]]
    sem_produto = selecionados["produto"].isna().sum()
    pares = selecionados.dropna(subset=["produto"])
    divergentes = [f"{r.descricao} (nota: {r.unidade_nota}, catálogo: {unidade_por_id[rotulos[r.produto]]})"
                   for r in pares.itertuples() if r.unidade_nota.lower() != unidade_por_id[rotulos[r.produto]].lower()]
    if sem_produto:
        st.warning(f"{sem_produto} item(ns) marcados sem produto vinculado — escolha o produto ou desmarque.",
                   icon=":material/link_off:")
    if divergentes:
        st.warning("Unidade diferente do cadastro, confira a conversão: " + "; ".join(divergentes),
                   icon=":material/straighten:")

    c1, c2, _ = st.columns([1.2, 1, 2])
    registrar = c1.button("3. Registrar entrada", type="primary", icon=":material/input:", width="stretch")
    c2.button("Descartar", on_click=descartar, icon=":material/delete:", width="stretch")

if registrar:
    erros = []
    if not fornecedor.strip():
        erros.append("Informe o fornecedor.")
    if sem_produto:
        erros.append("Há itens marcados sem produto vinculado.")
    itens_df = pares.assign(produto_id=pares["produto"].map(rotulos))
    erros_itens, prontos = est.validar_itens("Entrada", itens_df, data_mov)
    erros += erros_itens
    if erros:
        st.error("Não foi possível registrar:\n\n" + "\n".join(f"- {e}" for e in erros), icon=":material/error:")
    else:
        confirmar_movimentacao(
            {"tipo": "Entrada", "motivo": "Compra", "data": data_mov.isoformat(),
             "documento": f"NF {numero.strip()}" if numero.strip() else None,
             "parceiro": fornecedor.strip(), "origem": "ia", "observacao": "Importada com IA"},
            prontos, descartar)
