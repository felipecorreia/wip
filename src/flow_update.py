"""
Fluxo específico para atualização de dados de artistas existentes
"""

import logging
import re
from typing import Optional
from .schemas import Artista, EstadoConversa, Link
from .database import SupabaseManager

logger = logging.getLogger(__name__)


def extrair_links_da_mensagem(mensagem: str) -> dict:
    """Extrai links de redes sociais da mensagem"""
    links = {}
    msg_lower = mensagem.lower()
    
    # Instagram
    if "@" in mensagem:
        # Extrair @username
        import re
        instagram_match = re.search(r'@(\w+)', mensagem)
        if instagram_match:
            username = instagram_match.group(1)
            links['instagram'] = f"https://instagram.com/{username}"
            logger.info(f"Instagram extraído: {username}")
    
    # YouTube
    if "youtube" in msg_lower or "yt" in msg_lower:
        # Tentar extrair URL ou canal
        if "youtube.com" in msg_lower or "youtu.be" in msg_lower:
            # URL completa fornecida
            youtube_match = re.search(r'(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[\w\-]+)', mensagem)
            if youtube_match:
                links['youtube'] = youtube_match.group(1)
        elif "/" in mensagem:
            # Formato: youtube/channel
            channel_match = re.search(r'youtube[/\s]+(\S+)', mensagem, re.IGNORECASE)
            if channel_match:
                links['youtube'] = f"https://youtube.com/{channel_match.group(1)}"
    
    # Spotify
    if "spotify" in msg_lower:
        if "spotify.com" in msg_lower:
            spotify_match = re.search(r'(https?://(?:open\.)?spotify\.com/[\w\-/]+)', mensagem)
            if spotify_match:
                links['spotify'] = spotify_match.group(1)
        elif "spotify" in msg_lower:
            # Formato: spotify/artist
            artist_match = re.search(r'spotify[/\s]+(\S+)', mensagem, re.IGNORECASE)
            if artist_match:
                links['spotify'] = f"https://open.spotify.com/artist/{artist_match.group(1)}"
    
    return links


async def processar_atualizacao_dados(
    artista: Artista,
    mensagem: str,
    estado: EstadoConversa,
    supabase: SupabaseManager
) -> str:
    """
    Processa atualização de dados para artista existente
    Retorna resposta direta sem usar LangGraph
    """
    try:
        logger.info(f"Processando atualização de dados para {artista.nome}")
        
        # Extrair links da mensagem
        novos_links = extrair_links_da_mensagem(mensagem)
        
        if novos_links:
            # Atualizar links do artista
            if not artista.links:
                artista.links = Link()
            
            for plataforma, url in novos_links.items():
                setattr(artista.links, plataforma, url)
                logger.info(f"Link {plataforma} atualizado: {url}")
            
            # Salvar artista atualizado
            resultado = supabase.salvar_artista(artista)
            
            if resultado["success"]:
                # Verificar se agora está completo
                tem_links_suficientes = bool(
                    artista.links.instagram or 
                    artista.links.youtube or 
                    artista.links.spotify
                )
                
                if tem_links_suficientes:
                    resposta = (
                        f"Perfeito, {artista.nome}! 🎉\n\n"
                        f"Seus links foram atualizados com sucesso:\n"
                    )
                    
                    if artista.links.instagram:
                        resposta += f"📸 Instagram: {artista.links.instagram}\n"
                    if artista.links.youtube:
                        resposta += f"📺 YouTube: {artista.links.youtube}\n"
                    if artista.links.spotify:
                        resposta += f"🎵 Spotify: {artista.links.spotify}\n"
                    
                    resposta += (
                        f"\nAgora seu cadastro está completo! "
                        f"Como posso ajudar hoje?\n\n"
                        f"📅 **Agenda** - ver datas disponíveis\n"
                        f"📝 **Dados** - atualizar informações\n"
                        f"🏠 **Casa** - sobre a Cervejaria"
                    )
                    
                    # Marcar que não precisa mais do LangGraph
                    estado.etapa_atual = "menu_principal"
                    estado.precisa_langgraph = False
                else:
                    # Ainda faltam links
                    resposta = (
                        f"Ótimo! Já anotei:\n"
                    )
                    
                    for plataforma, url in novos_links.items():
                        resposta += f"• {plataforma.title()}: {url}\n"
                    
                    resposta += "\nVocê tem perfil em outras plataformas? (YouTube, Spotify, etc)"
                    estado.etapa_atual = "completar_dados"
            else:
                resposta = "Ops, tive um problema ao salvar seus dados. Pode tentar novamente?"
                logger.error(f"Erro ao salvar artista: {resultado.get('error')}")
        else:
            # Não conseguiu extrair links, pedir de forma mais clara
            resposta = (
                f"{artista.nome}, não consegui identificar os links na sua mensagem.\n\n"
                f"Por favor, me envie assim:\n"
                f"• Instagram: @seu_usuario\n"
                f"• YouTube: youtube.com/seu_canal\n"
                f"• Spotify: link do seu perfil\n\n"
                f"Pode me enviar pelo menos um deles?"
            )
            estado.etapa_atual = "completar_dados"
        
        return resposta
        
    except Exception as e:
        logger.error(f"Erro ao processar atualização: {str(e)}")
        return "Desculpe, tive um problema. Pode repetir seus links?"


async def processar_completar_cadastro(
    artista: Artista,
    mensagem: str,
    estado: EstadoConversa,
    supabase: SupabaseManager
) -> str:
    """
    Processa mensagem quando artista precisa completar cadastro
    """
    try:
        # Verificar o que falta
        falta_estilo = not artista.estilo_musical
        falta_links = not artista.links or (
            not artista.links.instagram and 
            not artista.links.youtube and 
            not artista.links.spotify
        )
        
        if falta_links:
            # Processar atualização de links
            return await processar_atualizacao_dados(artista, mensagem, estado, supabase)
        
        elif falta_estilo:
            # TODO: Implementar atualização de estilo musical
            estado.etapa_atual = "menu_principal" 
            estado.precisa_langgraph = False
            return "Função de atualização de estilo em desenvolvimento. Por enquanto, você já pode usar o menu principal!"
        
        else:
            # Dados completos, voltar ao menu
            estado.etapa_atual = "menu_principal"
            estado.precisa_langgraph = False
            return (
                f"Seus dados já estão completos, {artista.nome}! "
                f"Como posso ajudar?\n\n"
                f"📅 **Agenda** - ver datas disponíveis\n"
                f"📝 **Dados** - atualizar informações\n"
                f"🏠 **Casa** - sobre a Cervejaria"
            )
            
    except Exception as e:
        logger.error(f"Erro ao completar cadastro: {str(e)}")
        return "Desculpe, tive um problema. Pode repetir?"