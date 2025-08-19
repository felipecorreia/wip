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
        
        # Primeira mensagem - verificar se já contém dados antes de enviar boas vindas
        if etapa in ["inicio", "recepcao", ""]:
            # Tentar extrair dados da primeira mensagem usando LLM
            from .llm_extractor import extrair_dados_com_llm
            
            try:
                dados_extraidos = await extrair_dados_com_llm(mensagem)
                logger.info(f"Dados extraídos da primeira mensagem: {dados_extraidos.model_dump(exclude_unset=True)}")
                
                # Se encontrou nome na primeira mensagem, pular direto para próxima etapa
                if dados_extraidos.nome:
                    estado.dados_coletados["nome"] = dados_extraidos.nome
                    
                    # Verificar se tem estilo também
                    if dados_extraidos.estilo_musical:
                        estado.dados_coletados["estilo_musical"] = dados_extraidos.estilo_musical
                        
                        # Verificar se tem cidade
                        if dados_extraidos.cidade:
                            estado.dados_coletados["cidade"] = dados_extraidos.cidade
                            
                            # Verificar se tem links
                            if dados_extraidos.instagram or dados_extraidos.youtube or dados_extraidos.spotify:
                                if dados_extraidos.instagram:
                                    estado.dados_coletados["instagram"] = dados_extraidos.instagram
                                if dados_extraidos.youtube:
                                    estado.dados_coletados["youtube"] = dados_extraidos.youtube
                                if dados_extraidos.spotify:
                                    estado.dados_coletados["spotify"] = dados_extraidos.spotify
                                
                                # Tem todos os dados - processar como coleta de links
                                estado.etapa_atual = "coleta_links"
                                mensagem = "links_fornecidos"  # Flag para processar direto
                                etapa = "coleta_links"
                            else:
                                # Falta só os links
                                estado.etapa_atual = "coleta_links"
                                return (
                                    f"Show de bola, {dados_extraidos.nome}! "
                                    f"Anotei aqui que {'o som é ' + dados_extraidos.estilo_musical if dados_extraidos.estilo_musical else 'você é'} "
                                    f"{'de ' + dados_extraidos.cidade if dados_extraidos.cidade else ''}.\n\n"
                                    f"Para fechar, só preciso que me envie o link do seu Instagram, YouTube ou Spotify "
                                    f"para eu conhecer seu trabalho."
                                )
                        else:
                            # Tem nome e estilo, falta cidade
                            estado.etapa_atual = "coleta_cidade"
                            return (
                                f"Show de bola, {dados_extraidos.nome}! "
                                f"Anotei aqui que o som é {dados_extraidos.estilo_musical}. 🎵\n\n"
                                f"De qual cidade você é?"
                            )
                    else:
                        # Tem só o nome, perguntar estilo
                        estado.etapa_atual = "coleta_estilo"
                        return (
                            f"Prazer, {dados_extraidos.nome}! 🎸\n\n"
                            f"Qual é o seu estilo musical principal?\n"
                            f"(Rock, MPB, Samba, Pop, Sertanejo, etc)"
                        )
                else:
                    # Não encontrou nome - enviar boas vindas normal
                    estado.etapa_atual = "coleta_nome"
                    return (
                        "Olá! Sou a WIP, assistente virtual da Cervejaria Bragantina\n\n"
                        "Sou responsável por organizar a agenda de shows da Bragantina.\n"
                        "Antes de começar já me diz qual seu nome ou nome da sua banda?"
                    )
                    
            except Exception as e:
                logger.warning(f"Erro ao extrair dados da primeira mensagem: {str(e)}")
                # Em caso de erro, continuar com fluxo normal
                estado.etapa_atual = "coleta_nome"
                return (
                    "Olá! Sou a WIP, assistente virtual da Cervejaria Bragantina\n\n"
                    "Sou responsável por organizar a agenda de shows da Bragantina.\n"
                    "Antes de começar já me diz qual seu nome ou nome da sua banda?"
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
            # Se já tem links coletados via LLM (flag especial)
            if mensagem == "links_fornecidos" and (
                estado.dados_coletados.get("instagram") or 
                estado.dados_coletados.get("youtube") or 
                estado.dados_coletados.get("spotify")
            ):
                # Pular direto para persistir os dados
                pass
            else:
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

            # Persiste dados no supabase
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
                        f" Perfeito, {nome}! Já tenho todas suas informações!!\n\n"
                        f" Resumo:\n"
                        f"• Nome: {artista.nome}\n"
                        f"• Estilo: {artista.estilo_musical.value if hasattr(artista.estilo_musical, 'value') else artista.estilo_musical if artista.estilo_musical else 'Não informado'}\n"
                        f"• Cidade: {artista.cidade}\n"
                        f"• WhatsApp: {telefone_limpo}\n\n"
                        f"Agora as informações da sua banda conseguimos avançar! \n\n"
                        f"Do que você precisa,{nome} \n\n"
                        f"📅 *Agenda* - ver datas disponíveis\n"
                        f"📝 *Dados* - atualizar informações\n"
                        f"🏠 *Casa* - sobre a Cervejaria"
                    )
                else:
                    # Erro ao salvar
                    logger.error(f"Erro ao salvar artista: {resultado.get('error')}")
                    return (
                        f"Ops, {estado.dados_coletados.get('nome')}! "
                        f"Tive um probleminha por aqui.\n\n"
                        f"Posso te chamarem alguns instantes?"
                    )
                    
            except Exception as e:
                logger.error(f"Erro ao criar artista: {str(e)}")
                return (
                    "Desculpe, Tive um probleminha por aqui. "
                    "Posso te chamar depois pra terminar o papo?"
                )
        
        # Estado desconhecido - resetar
        else:
            estado.etapa_atual = "coleta_nome"
            return (
                "Beleza, vamos recomeçar do zero.\n"
                "Qual é o seu nome artístico ou da banda?"
            )
            
    except Exception as e:
        logger.error(f"Erro no fluxo de novo usuário: {str(e)}")
        return "Desculpe, tive um problema. Pode repetir?"