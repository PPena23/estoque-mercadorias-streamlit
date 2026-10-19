"""Componentes de interface reutilizáveis."""

from componentes.feedback import avisar, exibir_avisos
from componentes.filtros import barra_filtros, filtros_atuais, iniciar_filtros
from componentes.ui import (aplicar_estilo, cabecalho_pagina, estado_vazio,
                            grade_kpis, kpi_card, lista_insights, resumo_status, rodape,
                            status_badge, titulo_secao)

__all__ = ["avisar", "exibir_avisos", "barra_filtros", "filtros_atuais", "iniciar_filtros",
           "aplicar_estilo", "cabecalho_pagina", "estado_vazio", "grade_kpis",
           "kpi_card", "lista_insights", "resumo_status", "rodape", "status_badge", "titulo_secao"]
