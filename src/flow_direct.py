"""
Fluxo direto e otimizado para usuários existentes
Evita overhead do LangGraph para interações simples
"""

import logging
from typing import Optional, Tuple
from .schemas import Artista, EstadoConversa
from .database import SupabaseManager

logger = logging.getLogger(__name__)


def detectar_intencao_menu(mensagem: str) -> str:
    """
    Detecta intenção diretamente por palavras-chave
    Retorna: 'agenda', 'dados', 'casa', 'desconhecido'
    """
    msg_lower = mensagem.lower().strip()
    
    # Palavras-chave para cada opção
    palavras_agenda = ["agenda", "show", "tocar", "data", "quando", "disponível", "sexta", "sábado", "apresentar"]
    palavras_dados = ["dados", "atualizar", "mudar", "alterar", "instagram", "spotify", "youtube", "corrigir", "editar"]
    palavras_casa = ["casa", "cervejaria", "info", "informação", "local", "endereço", "onde", "horário", "funciona"]
    
    # Contar matches para cada categoria
    matches_agenda = sum(1 for palavra in palavras_agenda if palavra in msg_lower)
    matches_dados = sum(1 for palavra in palavras_dados if palavra in msg_lower)
    matches_casa = sum(1 for palavra in palavras_casa if palavra in msg_lower)
    
    # Retornar categoria com mais matches
    max_matches = max(matches_agenda, matches_dados, matches_casa)
    
    if max_matches == 0:
        return "desconhecido"
    elif matches_agenda == max_matches:
        return "agenda"
    elif matches_dados == max_matches:
        return "dados"
    else:
        return "casa"


def gerar_menu_principal(artista: Artista) -> str:
    """Gera menu principal para artista existente"""
    return (
        f"Olá {artista.nome}! WIP da Cervejaria Bragantina aqui 🍺\n\n"
        f"Como posso ajudar hoje?\n\n"
        f"📅 **Agenda** - ver datas disponíveis para shows\n"
        f"📝 **Dados** - atualizar suas informações\n"
        f"🏠 **Casa** - saber mais sobre a Cervejaria\n\n"
        f"O que você gostaria?"
    )


def responder_agenda() -> str:
    """Resposta padrão para consulta de agenda"""
    return (
        "📅 **Agenda da Cervejaria Bragantina**\n\n"
        "Próximas datas disponíveis para shows:\n\n"
        "• Sexta 23/08 - 20h às 23h\n"
        "• Sábado 24/08 - 21h às 00h\n"
        "• Sexta 30/08 - 20h às 23h\n\n"
        "Interessado em alguma data? Me diga qual você prefere!"
    )


def responder_dados(artista: Artista) -> str:
    """Resposta para atualização de dados"""
    resposta = (
        "📝 **Atualização de Dados**\n\n"
        "Seus dados atuais:\n"
        f"• Nome: {artista.nome}\n"
        f"• Cidade: {artista.cidade or 'Não informado'}\n"
        f"• Estilo: {artista.estilo_musical or 'Não informado'}\n"
    )
    
    if artista.links:
        if artista.links.instagram:
            resposta += f"• Instagram: {artista.links.instagram}\n"
        if artista.links.youtube:
            resposta += f"• YouTube: {artista.links.youtube}\n"
        if artista.links.spotify:
            resposta += f"• Spotify: {artista.links.spotify}\n"
    
    resposta += "\nO que você gostaria de atualizar?"
    return resposta


def responder_casa() -> str:
    """Resposta com informações da casa"""
    return (
        "🏠 **Cervejaria Bragantina**\n\n"
        "📍 Endereço: Rua José Domingues, 331 - Centro, Bragança Paulista/SP\n"
        "🕐 Funcionamento: Qui-Dom, 18h às 00h\n"
        "🎸 Shows: Sex e Sáb, a partir das 20h\n"
        "🍺 Cervejas artesanais e petiscos\n\n"
        "Ambiente acolhedor para música ao vivo!\n"
        "Focamos em rock, MPB e música autoral.\n\n"
        "Algo mais que você gostaria de saber?"
    )


def responder_desconhecido() -> str:
    """Resposta quando não entende a intenção"""
    return (
        "Desculpe, não entendi. Você pode me dizer se quer:\n\n"
        "• Ver a **agenda** de shows\n"
        "• Atualizar seus **dados**\n"
        "• Saber mais sobre a **casa**\n\n"
        "Como posso ajudar?"
    )


def verificar_dados_completos(artista: Artista) -> bool:
    """Verifica se artista tem dados mínimos"""
    tem_nome = bool(artista.nome)
    tem_estilo = bool(artista.estilo_musical)
    tem_links = bool(artista.links and (
        artista.links.instagram or 
        artista.links.youtube or 
        artista.links.spotify
    ))
    return tem_nome and tem_estilo and tem_links


async def processar_usuario_existente(
    artista: Artista,
    mensagem: str,
    estado: EstadoConversa,
    supabase: SupabaseManager
) -> Tuple[str, EstadoConversa]:
    """
    Processa mensagem de usuário existente SEM usar LangGraph
    Retorna: (resposta, estado_atualizado)
    """
    try:
        # Se está no processo de completar dados
        if estado.etapa_atual == "completar_dados":
            from .flow_update import processar_completar_cadastro
            resposta = await processar_completar_cadastro(artista, mensagem, estado, supabase)
            return resposta, estado
        
        # Se dados incompletos, direcionar para completar cadastro
        if not verificar_dados_completos(artista):
            resposta = (
                f"Olá {artista.nome}! WIP da Cervejaria Bragantina aqui 🍺\n\n"
                f"Notei que seu cadastro está incompleto. "
                f"Para agendar shows, preciso de algumas informações:\n\n"
            )
            
            if not artista.estilo_musical:
                resposta += "• Estilo musical\n"
            if not artista.links or (
                not artista.links.instagram and 
                not artista.links.youtube and 
                not artista.links.spotify
            ):
                resposta += "• Links das redes sociais\n"
            
            resposta += "\nVamos completar seu cadastro?"
            
            # Marcar estado para completar dados (sem LangGraph)
            estado.etapa_atual = "completar_dados"
            estado.precisa_langgraph = False  # Usar fluxo direto
            
            return resposta, estado
        
        # Usuário com dados completos - processar diretamente
        
        # Se primeira mensagem da sessão, mostrar menu
        if estado.etapa_atual in ["inicio", "recepcao", ""]:
            resposta = gerar_menu_principal(artista)
            estado.etapa_atual = "menu_principal"
            estado.precisa_langgraph = False
            return resposta, estado
        
        # Detectar intenção e responder
        intencao = detectar_intencao_menu(mensagem)
        logger.info(f"Intenção detectada: {intencao} para mensagem: {mensagem[:50]}")
        
        if intencao == "agenda":
            resposta = responder_agenda()
            estado.etapa_atual = "consulta_agenda"
        elif intencao == "dados":
            resposta = responder_dados(artista)
            estado.etapa_atual = "atualizar_dados"
            # TODO: Implementar fluxo de atualização
        elif intencao == "casa":
            resposta = responder_casa()
            estado.etapa_atual = "info_casa"
        else:
            resposta = responder_desconhecido()
            estado.etapa_atual = "menu_principal"
        
        estado.precisa_langgraph = False
        return resposta, estado
        
    except Exception as e:
        logger.error(f"Erro no processamento direto: {str(e)}")
        # Em caso de erro, retornar mensagem genérica
        return "Desculpe, tive um problema. Pode repetir?", estado


async def processar_mensagem_otimizado(
    telefone: str,
    mensagem: str,
    estado: EstadoConversa,
    supabase: SupabaseManager
) -> str:
    """
    Função principal otimizada que decide entre fluxo direto ou LangGraph
    """
    try:
        # Limpar telefone antes de buscar
        telefone_limpo = telefone.replace("whatsapp:", "")
        logger.info(f"Processando mensagem otimizada para {telefone_limpo}: {mensagem[:50]}")
        
        # Buscar artista
        artista = supabase.buscar_artista_por_telefone(telefone_limpo)
        
        # Se não existe artista, usar fluxo simplificado para novo usuário
        if not artista:
            logger.info(f"Novo usuário detectado - usando fluxo simplificado")
            from .flow_new_user import processar_novo_usuario_simples
            return await processar_novo_usuario_simples(telefone, mensagem, estado, supabase)
        
        # Se precisa LangGraph especificamente (casos especiais)
        if estado.precisa_langgraph:
            logger.info(f"LangGraph requisitado explicitamente")
            from .flow import processar_fluxo_artista
            return await processar_fluxo_artista(telefone, mensagem, estado, supabase)
        
        logger.info(f"Usando fluxo direto para {artista.nome}")
        # Artista existe - usar fluxo direto otimizado
        resposta, estado_atualizado = await processar_usuario_existente(
            artista, mensagem, estado, supabase
        )
        
        # Salvar estado atualizado
        estado.etapa_atual = estado_atualizado.etapa_atual
        estado.precisa_langgraph = estado_atualizado.precisa_langgraph
        
        # Adicionar mensagem ao histórico
        estado.mensagens_historico.append(mensagem)
        if len(estado.mensagens_historico) > 10:
            estado.mensagens_historico = estado.mensagens_historico[-10:]
        
        # Salvar no banco com telefone limpo
        try:
            supabase.salvar_estado_conversa(telefone_limpo, estado)
        except Exception as e:
            logger.warning(f"Erro ao salvar estado: {str(e)}")
        
        logger.info(f"Resposta direta gerada em <1s para {telefone}")
        return resposta
        
    except Exception as e:
        logger.error(f"Erro no processamento otimizado: {str(e)}")
        # Fallback para LangGraph em caso de erro
        from .flow import processar_fluxo_artista
        return await processar_fluxo_artista(telefone, mensagem, estado, supabase)