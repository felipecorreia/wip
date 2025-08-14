import logging
from typing import Any

from .schemas import EstadoConversa
from .database import SupabaseManager

logger = logging.getLogger(__name__)

def reiniciar_conversa(telefone: str, supabase: SupabaseManager) -> EstadoConversa:
    """Reinicia uma conversa, limpando o estado no banco e retornando um novo estado."""
    try:
        telefone_limpo = telefone.replace("whatsapp:", "")
        
        # Cria um novo estado de conversa vazio
        novo_estado = EstadoConversa()
        
        # Salva/sobrescreve o estado no banco de dados
        supabase.salvar_estado_conversa(telefone_limpo, novo_estado)
        
        logger.info(f"Conversa reiniciada para telefone: {telefone_limpo}")
        return novo_estado
        
    except Exception as e:
        logger.error(f"Erro ao reiniciar conversa para {telefone}: {e}")
        # Retorna um estado vazio em caso de erro para não quebrar a aplicação
        return EstadoConversa()

def obter_progresso_conversa(estado: EstadoConversa) -> dict[str, Any]:
    """Calcula o progresso atual da coleta de dados em uma conversa."""
    dados = estado.dados_coletados
    
    campos_essenciais = ["nome", "estilo_musical"]
    campos_links = ["instagram", "youtube", "spotify"]
    
    # Conta quantos campos essenciais foram preenchidos
    essenciais_preenchidos = sum(1 for campo in campos_essenciais if dados.get(campo))
    
    # Verifica se pelo menos um link foi fornecido
    links_preenchidos = 1 if any(dados.get(link) for link in campos_links) else 0
    
    total_campos = len(campos_essenciais) + 1 # +1 representa a necessidade de "pelo menos um link"
    campos_preenchidos = essenciais_preenchidos + links_preenchidos
    
    progresso = (campos_preenchidos / total_campos) * 100 if total_campos > 0 else 0
    
    return {
        "progresso_percentual": round(progresso, 1),
        "etapa_atual": estado.etapa_atual,
        "dados_coletados": len(dados)
    }
