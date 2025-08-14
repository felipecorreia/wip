"""
Fluxo simplificado para novos usuários
Resposta rápida sem LangGraph complexo
"""

import logging
import re
from typing import Optional
from .schemas import EstadoConversa
from .database import SupabaseManager

logger = logging.getLogger(__name__)


async def processar_novo_usuario_simples(
    telefone: str,
    mensagem: str,
    estado: EstadoConversa,
    supabase: SupabaseManager
) -> str:
    """
    Processa novo usuário de forma simples e rápida
    Sem usar LangGraph para evitar timeout
    """
    try:
        telefone_limpo = telefone.replace("whatsapp:", "")
        etapa = estado.etapa_atual
        
        # Primeira mensagem - boas vindas
        if etapa in ["inicio", "recepcao", ""]:
            estado.etapa_atual = "coleta_nome"
            return (
                "Olá! Sou a WIP, assistente virtual da Cervejaria Bragantina 🍺\n\n"
                "Vamos cadastrar você para tocar aqui na casa?\n"
                "Para começar, qual é o seu nome ou nome da sua banda?"
            )
        
        # Coletar nome
        elif etapa == "coleta_nome":
            # Salvar nome simples (sem validação complexa)
            nome = mensagem.strip()
            if len(nome) < 2:
                return "Por favor, me diga seu nome artístico ou da banda."
            
            estado.dados_coletados["nome"] = nome
            estado.etapa_atual = "coleta_estilo"
            
            return (
                f"Prazer, {nome}! 🎸\n\n"
                f"Qual é o seu estilo musical principal?\n"
                f"(Rock, MPB, Samba, Pop, Sertanejo, etc)"
            )
        
        # Coletar estilo
        elif etapa == "coleta_estilo":
            estado.dados_coletados["estilo_musical"] = mensagem.strip()
            estado.etapa_atual = "coleta_cidade"
            
            return (
                f"Legal! {mensagem} é um ótimo estilo! 🎵\n\n"
                f"De qual cidade você é?"
            )
        
        # Coletar cidade
        elif etapa == "coleta_cidade":
            estado.dados_coletados["cidade"] = mensagem.strip()
            estado.etapa_atual = "coleta_links"
            
            return (
                f"Ótimo! Cidade: {mensagem}\n\n"
                f"Agora preciso de pelo menos uma rede social sua.\n"
                f"Me envie seu Instagram (com @), YouTube ou Spotify:"
            )
        
        # Coletar links
        elif etapa == "coleta_links":
            # Extrair e normalizar links
            mensagem_limpa = mensagem.strip()
            
            if "@" in mensagem_limpa:
                # Instagram detectado - extrair username
                match = re.search(r'@(\w+)', mensagem_limpa)
                if match:
                    username = match.group(1)
                    estado.dados_coletados["instagram"] = f"https://instagram.com/{username}"
                    logger.info(f"Instagram extraído: @{username} -> https://instagram.com/{username}")
                else:
                    # Fallback - assumir que é username direto
                    username = mensagem_limpa.replace("@", "").strip()
                    estado.dados_coletados["instagram"] = f"https://instagram.com/{username}"
            elif "youtube" in mensagem_limpa.lower():
                # YouTube detectado
                if "youtube.com" in mensagem_limpa or "youtu.be" in mensagem_limpa:
                    estado.dados_coletados["youtube"] = mensagem_limpa
                else:
                    # Assumir que é canal/username
                    canal = mensagem_limpa.replace("youtube", "").replace("/", "").strip()
                    estado.dados_coletados["youtube"] = f"https://youtube.com/{canal}"
            elif "spotify" in mensagem_limpa.lower():
                # Spotify detectado
                if "spotify.com" in mensagem_limpa:
                    estado.dados_coletados["spotify"] = mensagem_limpa
                else:
                    # Assumir que é artista/ID
                    artista = mensagem_limpa.replace("spotify", "").replace("/", "").strip()
                    estado.dados_coletados["spotify"] = f"https://open.spotify.com/artist/{artista}"
            elif mensagem_limpa.startswith("http"):
                # URL completa fornecida - tentar detectar plataforma
                if "instagram.com" in mensagem_limpa:
                    estado.dados_coletados["instagram"] = mensagem_limpa
                elif "youtube.com" in mensagem_limpa or "youtu.be" in mensagem_limpa:
                    estado.dados_coletados["youtube"] = mensagem_limpa
                elif "spotify.com" in mensagem_limpa:
                    estado.dados_coletados["spotify"] = mensagem_limpa
                else:
                    # URL desconhecida - salvar como Instagram por default
                    estado.dados_coletados["instagram"] = mensagem_limpa
            else:
                # Assumir que é username do Instagram sem @
                username = mensagem_limpa.strip()
                estado.dados_coletados["instagram"] = f"https://instagram.com/{username}"
                logger.info(f"Assumindo Instagram: {username} -> https://instagram.com/{username}")
            
            # Finalizar cadastro - SALVAR NO SUPABASE
            try:
                # Importar schemas necessários
                from .schemas import Artista, Contato, Link, TipoContato, EstiloMusical
                from uuid import uuid4
                
                # Criar contato WhatsApp
                contatos = [Contato(
                    tipo=TipoContato.WHATSAPP,
                    valor=telefone_limpo,
                    principal=True
                )]
                
                # Criar links se fornecidos
                links = None
                if estado.dados_coletados.get("instagram") or estado.dados_coletados.get("youtube") or estado.dados_coletados.get("spotify"):
                    links = Link(
                        instagram=estado.dados_coletados.get("instagram"),
                        youtube=estado.dados_coletados.get("youtube"),
                        spotify=estado.dados_coletados.get("spotify")
                    )
                
                # Mapear estilo musical com mapeamentos extras
                estilo_str = estado.dados_coletados.get("estilo_musical", "").lower().strip()
                estilo_musical = EstiloMusical.OUTRO  # Default
                
                # Mapeamentos especiais
                mapeamentos = {
                    "samba": EstiloMusical.MPB,
                    "pagode": EstiloMusical.MPB,
                    "bossa nova": EstiloMusical.MPB,
                    "forró": EstiloMusical.OUTRO,
                    "country": EstiloMusical.SERTANEJO,
                    "hip hop": EstiloMusical.RAP,
                    "hip-hop": EstiloMusical.RAP,
                    "electronic": EstiloMusical.ELETRONICA,
                    "techno": EstiloMusical.ELETRONICA,
                    "house": EstiloMusical.ELETRONICA
                }
                
                # Primeiro tentar mapeamento direto
                for estilo in EstiloMusical:
                    if estilo_str in [estilo.value.lower(), estilo.name.lower()]:
                        estilo_musical = estilo
                        break
                
                # Se não encontrou, tentar mapeamentos especiais
                if estilo_musical == EstiloMusical.OUTRO and estilo_str in mapeamentos:
                    estilo_musical = mapeamentos[estilo_str]
                
                logger.info(f"Estilo '{estilo_str}' mapeado para {estilo_musical}")
                
                # Criar objeto Artista
                artista = Artista(
                    id=uuid4(),
                    nome=estado.dados_coletados.get("nome"),
                    cidade=estado.dados_coletados.get("cidade"),
                    estilo_musical=estilo_musical,
                    links=links,
                    contatos=contatos
                )
                
                # Salvar no Supabase com tenant da Cervejaria Bragantina
                resultado = supabase.salvar_artista(artista, tenant_id="b2894499-6bf5-4e91-8853-fa16c59ddf40")
                
                if resultado["success"]:
                    # Sucesso - atualizar estado
                    estado.artista_id = artista.id
                    estado.etapa_atual = "menu_principal"  # Mover para menu
                    estado.precisa_langgraph = False
                    
                    logger.info(f"Artista {artista.nome} salvo com sucesso - ID: {artista.id}")
                    
                    nome = artista.nome
                    return (
                        f"🎉 Perfeito, {nome}! Cadastro concluído!\n\n"
                        f"📋 Resumo:\n"
                        f"• Nome: {artista.nome}\n"
                        f"• Estilo: {artista.estilo_musical.value if hasattr(artista.estilo_musical, 'value') else artista.estilo_musical if artista.estilo_musical else 'Não informado'}\n"
                        f"• Cidade: {artista.cidade}\n"
                        f"• WhatsApp: {telefone_limpo}\n\n"
                        f"Você já está em nosso sistema! 🍺\n\n"
                        f"Como posso ajudar?\n\n"
                        f"📅 **Agenda** - ver datas disponíveis\n"
                        f"📝 **Dados** - atualizar informações\n"
                        f"🏠 **Casa** - sobre a Cervejaria"
                    )
                else:
                    # Erro ao salvar
                    logger.error(f"Erro ao salvar artista: {resultado.get('error')}")
                    return (
                        f"Ops, {estado.dados_coletados.get('nome')}! "
                        f"Tive um probleminha ao salvar seu cadastro.\n\n"
                        f"Pode tentar novamente em alguns instantes?"
                    )
                    
            except Exception as e:
                logger.error(f"Erro ao criar artista: {str(e)}")
                return (
                    "Desculpe, tive um problema técnico ao finalizar seu cadastro. "
                    "Pode tentar novamente?"
                )
        
        # Estado desconhecido - resetar
        else:
            estado.etapa_atual = "coleta_nome"
            return (
                "Vamos recomeçar seu cadastro.\n"
                "Qual é o seu nome artístico ou da banda?"
            )
            
    except Exception as e:
        logger.error(f"Erro no fluxo de novo usuário: {str(e)}")
        return "Desculpe, tive um problema. Pode repetir?"