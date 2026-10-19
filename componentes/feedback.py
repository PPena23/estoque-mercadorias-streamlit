"""Avisos (toasts) que sobrevivem a um st.rerun().

Depois de gravar algo, a página costuma chamar st.rerun() para redesenhar
tudo com o dado novo. O aviso entra numa fila no Session State e é exibido
no início da próxima execução (app.py chama exibir_avisos()).
"""

import streamlit as st


def avisar(mensagem: str, icone: str = ":material/check_circle:") -> None:
    st.session_state.setdefault("_avisos", []).append((mensagem, icone))


def exibir_avisos() -> None:
    for mensagem, icone in st.session_state.pop("_avisos", []):
        st.toast(mensagem, icon=icone, duration="long")
