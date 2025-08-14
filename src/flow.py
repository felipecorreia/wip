import logging
from typing import TypedDict, Annotated, Any, Optional
from uuid import UUID
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langsmith import traceable
from .schemas import Artista, Contato, Link, TipoContato, EstiloMusical, EstadoConversa, DadosExtraidos
from .database import SupabaseManager
from .llm_config import (
    processar_mensagem_llm_with_fallback, 
    extrair_dados_mensagem_with_fallback, 
    gerar_resposta_contextual,
    validar_dados_completos,
    EnhancedLLMConfig
)

logger = logging.getLogger(__name__)


class EstadoFluxo(TypedDict):
    """Estado do fluxo de conversação"""
    mensagem_usuario: str
    telefone: str
    artista_atual: Optional[Artista]
    dados_coletados: dict[str, Any]
    etapa: str
    resposta_bot: str
    finalizado: bool
    erro: Optional[str]
    tentativas: int


def verificar_dados_completos(artista: Artista) -> bool:
    """Verifica se artista tem dados mínimos para shows"""
    # Dados essenciais: nome, estilo, pelo menos um link
    tem_nome = bool(artista.nome)
    tem_estilo = bool(artista.estilo_musical)
    tem_links = bool(artista.links and (
        artista.links.instagram or 
        artista.links.youtube or 
        artista.links.spotify
    ))
    return tem_nome and tem_estilo and tem_links


@traceable
def no_recepcao(state: EstadoFluxo) -> EstadoFluxo:
    """Nó inicial - verifica se é artista novo ou existente"""
    try:
        telefone = state["telefone"]
        supabase = SupabaseManager()
        
        # Buscar artista existente
        artista_existente = supabase.buscar_artista_por_telefone(telefone)
        
        if artista_existente:
            state["artista_atual"] = artista_existente
            
            # Verificar se dados estão completos
            if verificar_dados_completos(artista_existente):
                # Menu completo para artistas com dados
                state["etapa"] = "menu_principal"
                state["resposta_bot"] = (
                    f"Olá {artista_existente.nome}! WIP da Cervejaria Bragantina aqui 🍺\n\n"
                    f"Como posso ajudar hoje?\n\n"
                    f"📅 **Agenda** - ver datas disponíveis para shows\n"
                    f"📝 **Dados** - atualizar suas informações\n"
                    f"🏠 **Casa** - saber mais sobre a Cervejaria\n\n"
                    f"O que você gostaria?"
                )
            else:
                # Artista existe mas precisa completar dados
                state["etapa"] = "completar_dados"
                state["resposta_bot"] = (
                    f"Olá {artista_existente.nome}! WIP da Cervejaria Bragantina aqui 🍺\n\n"
                    f"Notei que seu cadastro está incompleto. "
                    f"Para agendar shows, preciso de algumas informações:\n\n"
                )
                # Listar o que falta
                if not artista_existente.estilo_musical:
                    state["resposta_bot"] += "• Estilo musical\n"
                if not artista_existente.links or (
                    not artista_existente.links.instagram and 
                    not artista_existente.links.youtube and 
                    not artista_existente.links.spotify
                ):
                    state["resposta_bot"] += "• Links das redes sociais\n"
                
                state["resposta_bot"] += "\nVamos completar seu cadastro?"
            
            state["finalizado"] = False  # Continuar processamento
            logger.info(f"Artista existente reconhecido: {artista_existente.nome}")
        else:
            state["etapa"] = "coleta_nome"
            state["resposta_bot"] = (
                "Olá! Sou a WIP, assistente virtual da Cervejaria Bragantina 🍺\n\n"
                "Vamos cadastrar você para tocar aqui na casa?\n"
                "Para começar, qual é o seu nome ou nome da sua banda?"
            )
            logger.info(f"Novo artista iniciando cadastro: {telefone}")
        
        state["erro"] = None
        return state
        
    except Exception as e:
        logger.error(f"Erro no nó de recepção: {str(e)}")
        state["erro"] = str(e)
        state["resposta_bot"] = (
            "Desculpe, tive um problema técnico. "
            "Tente novamente em alguns instantes."
        )
        return state


@traceable
def no_coleta_dados(state: EstadoFluxo) -> EstadoFluxo:
    """Nó de coleta de dados usando LLM"""
    try:
        mensagem = state["mensagem_usuario"]
        etapa = state["etapa"]
        dados = state["dados_coletados"]
        tentativas = state.get("tentativas", 0)
        
        # Extrair dados da mensagem atual using fallback system
        dados_extraidos = extrair_dados_mensagem_with_fallback(mensagem, etapa)
        
        # Atualizar dados coletados com os novos dados
        if dados_extraidos.dict(exclude_unset=True):
            for campo, valor in dados_extraidos.dict(exclude_unset=True).items():
                if valor is not None and campo != "confianca":
                    dados[campo] = valor
                    logger.debug(f"Dado coletado - {campo}: {valor}")
        
        # Gerar resposta contextual
        resposta = gerar_resposta_contextual(dados, etapa, mensagem)
        
        # Determinar próxima etapa - SIMPLIFICADO para evitar loops
        dados_suficientes, campos_faltantes = validar_dados_completos(dados)
        
        # Limite de tentativas para evitar loops infinitos
        if tentativas >= 10:
            logger.warning(f"Limite de tentativas atingido para {telefone}")
            proxima_etapa = "validacao"  # Forçar validação mesmo sem dados completos
        elif dados_suficientes:
            proxima_etapa = "validacao"
            logger.info("Dados suficientes coletados, passando para validação")
        else:
            # Continuar coletando dados
            if not dados.get("nome"):
                proxima_etapa = "coleta_nome"
            elif not dados.get("cidade"):
                proxima_etapa = "coleta_cidade"
            elif not dados.get("estilo_musical"):
                proxima_etapa = "coleta_estilo"
            elif not any(dados.get(link) for link in ["instagram", "youtube", "spotify"]):
                proxima_etapa = "coleta_links"
            else:
                proxima_etapa = "validacao"  # Ir para validação se chegou até aqui
        
        state["dados_coletados"] = dados
        state["etapa"] = proxima_etapa
        state["resposta_bot"] = resposta
        state["tentativas"] = tentativas + 1
        state["erro"] = None
        
        return state
        
    except Exception as e:
        logger.error(f"Erro no nó de coleta de dados: {str(e)}")
        state["erro"] = str(e)
        state["resposta_bot"] = (
            "Desculpe, não consegui processar sua mensagem. "
            "Pode repetir de forma mais simples?"
        )
        return state


@traceable
def no_validacao(state: EstadoFluxo) -> EstadoFluxo:
    """Nó de validação dos dados coletados"""
    try:
        dados = state["dados_coletados"]
        telefone = state["telefone"]
        
        # Criar contato principal (WhatsApp)
        contatos = [Contato(
            tipo=TipoContato.WHATSAPP,
            valor=telefone.replace("whatsapp:", ""),
            principal=True
        )]
        
        # Validar e normalizar estilo musical
        estilo_musical = None
        if dados.get("estilo_musical"):
            try:
                # Tentar converter para enum
                estilo_str = dados["estilo_musical"].lower()
                for estilo in EstiloMusical:
                    if estilo_str in [estilo.value, estilo.name.lower()]:
                        estilo_musical = estilo
                        break
                if not estilo_musical:
                    estilo_musical = EstiloMusical.OUTRO
            except:
                estilo_musical = EstiloMusical.OUTRO
        
        # Criar objeto Links se houver dados de redes sociais
        links = None
        links_data = {}
        for campo in ["instagram", "youtube", "spotify", "soundcloud", "bandcamp"]:
            if dados.get(campo):
                url = dados[campo]
                # Garantir que é uma URL válida
                if not url.startswith("http"):
                    if campo == "instagram":
                        url = f"https://instagram.com/{url.replace('@', '')}"
                    elif campo == "youtube":
                        url = f"https://youtube.com/{url}"
                    elif campo == "spotify":
                        url = f"https://open.spotify.com/{url}"
                links_data[campo] = url
        
        if links_data:
            links = Link(**links_data)
        
        # Criar objeto Artista
        artista = Artista(
            nome=dados.get("nome"),
            cidade=dados.get("cidade"),
            estilo_musical=estilo_musical,
            biografia=dados.get("biografia"),
            experiencia_anos=dados.get("experiencia_anos"),
            contatos=contatos,
            links=links
        )
        
        state["artista_atual"] = artista
        state["etapa"] = "salvamento"
        state["erro"] = None
        
        logger.info(f"Dados validados para artista: {artista.nome}")
        
        return state
        
    except Exception as e:
        logger.error(f"Erro na validação dos dados: {str(e)}")
        state["erro"] = str(e)
        state["etapa"] = "erro_validacao"
        state["resposta_bot"] = (
            f"Encontrei um problema com os dados fornecidos: {str(e)}. "
            f"Vamos corrigir isso juntos. Qual informação precisa ser ajustada?"
        )
        return state


@traceable
def no_salvamento(state: EstadoFluxo) -> EstadoFluxo:
    """Nó de salvamento no banco de dados"""
    try:
        artista = state["artista_atual"]
        supabase = SupabaseManager()
        
        # Salvar artista no banco
        resultado = supabase.salvar_artista(artista)
        
        if resultado["success"]:
            # Gerar resposta de confirmação
            resposta_confirmacao = f"""
Perfeito! Seu cadastro foi realizado com sucesso.

Resumo dos seus dados:
- Nome: {artista.nome}
- Cidade: {artista.cidade or 'Não informada'}
- Estilo: {artista.estilo_musical or 'Não informado'}
- Experiência: {artista.experiencia_anos or 'Não informada'} anos

Seus dados já estão em nosso sistema e você receberá oportunidades compatíveis com seu perfil.

Obrigada por se cadastrar conosco!
""".strip()
            
            state["resposta_bot"] = resposta_confirmacao
            state["finalizado"] = True
            state["etapa"] = "concluido"
            state["erro"] = None
            
            logger.info(f"Artista {artista.nome} salvo com sucesso - ID: {artista.id}")
            
        else:
            state["resposta_bot"] = (
                "Houve um problema técnico ao salvar seus dados. "
                "Por favor, tente novamente em alguns minutos."
            )
            state["etapa"] = "erro_salvamento"
            state["erro"] = resultado.get("error", "Erro desconhecido")
            
            logger.error(f"Erro ao salvar artista: {resultado.get('error')}")
        
        return state
        
    except Exception as e:
        logger.error(f"Erro no nó de salvamento: {str(e)}")
        state["erro"] = str(e)
        state["resposta_bot"] = (
            "Ocorreu um erro técnico durante o salvamento. "
            "Tente novamente mais tarde."
        )
        state["etapa"] = "erro_salvamento"
        return state


@traceable
def no_menu_principal(state: EstadoFluxo) -> EstadoFluxo:
    """Processa escolha do menu principal"""
    try:
        mensagem = state["mensagem_usuario"].lower().strip()
        
        # Detectar intenção usando palavras-chave
        if any(palavra in mensagem for palavra in ["agenda", "show", "tocar", "data", "quando", "disponível"]):
            state["etapa"] = "consulta_agenda"
            state["resposta_bot"] = (
                "📅 **Agenda da Cervejaria Bragantina**\n\n"
                "Próximas datas disponíveis para shows:\n\n"
                "• Sexta 23/08 - 20h às 23h\n"
                "• Sábado 24/08 - 21h às 00h\n"
                "• Sexta 30/08 - 20h às 23h\n\n"
                "Interessado em alguma data? Me diga qual você prefere!"
            )
        elif any(palavra in mensagem for palavra in ["dados", "atualizar", "mudar", "alterar", "instagram", "spotify"]):
            state["etapa"] = "atualizar_dados"
            artista = state.get("artista_atual")
            state["resposta_bot"] = (
                "📝 **Atualização de Dados**\n\n"
                "Seus dados atuais:\n"
                f"• Nome: {artista.nome}\n"
                f"• Cidade: {artista.cidade or 'Não informado'}\n"
                f"• Estilo: {artista.estilo_musical or 'Não informado'}\n"
            )
            if artista.links:
                if artista.links.instagram:
                    state["resposta_bot"] += f"• Instagram: {artista.links.instagram}\n"
                if artista.links.youtube:
                    state["resposta_bot"] += f"• YouTube: {artista.links.youtube}\n"
                if artista.links.spotify:
                    state["resposta_bot"] += f"• Spotify: {artista.links.spotify}\n"
            
            state["resposta_bot"] += "\nO que você gostaria de atualizar?"
        elif any(palavra in mensagem for palavra in ["casa", "cervejaria", "info", "informação", "local", "endereço"]):
            state["etapa"] = "info_casa"
            state["resposta_bot"] = (
                "🏠 **Cervejaria Bragantina**\n\n"
                "📍 Endereço: Rua José Domingues, 331 - Centro, Bragança Paulista/SP\n"
                "🕐 Funcionamento: Qui-Dom, 18h às 00h\n"
                "🎸 Shows: Sex e Sáb, a partir das 20h\n"
                "🍺 Cervejas artesanais e petiscos\n\n"
                "Ambiente acolhedor para música ao vivo!\n"
                "Focamos em rock, MPB e música autoral.\n\n"
                "Algo mais que você gostaria de saber?"
            )
            state["finalizado"] = True
        else:
            # Não entendeu, repetir menu
            state["etapa"] = "menu_principal"
            state["resposta_bot"] = (
                "Desculpe, não entendi. Você pode me dizer se quer:\n\n"
                "• Ver a **agenda** de shows\n"
                "• Atualizar seus **dados**\n"
                "• Saber mais sobre a **casa**\n\n"
                "Como posso ajudar?"
            )
        
        state["erro"] = None
        return state
        
    except Exception as e:
        logger.error(f"Erro no menu principal: {str(e)}")
        state["erro"] = str(e)
        state["resposta_bot"] = "Ops, tive um problema. Pode repetir?"
        return state


def determinar_rota(state: EstadoFluxo) -> str:
    """Determina qual nó executar baseado no estado atual"""
    etapa = state["etapa"]
    
    if etapa == "artista_existente":
        return "fim"
    elif etapa == "menu_principal":
        return "menu_principal"
    elif etapa == "completar_dados":
        return "coleta_dados"
    elif etapa.startswith("coleta_"):
        return "coleta_dados"
    elif etapa == "validacao":
        return "validacao"
    elif etapa == "salvamento":
        return "salvamento"
    elif etapa in ["concluido", "erro_salvamento", "erro_validacao", "info_casa", "consulta_agenda"]:
        return "fim"
    else:
        return "coleta_dados"


def criar_fluxo_artista() -> StateGraph:
    """Cria e configura o fluxo de conversação do artista"""
    workflow = StateGraph(EstadoFluxo)
    
    # Adicionar nós
    workflow.add_node("recepcao", no_recepcao)
    workflow.add_node("coleta_dados", no_coleta_dados)
    workflow.add_node("validacao", no_validacao)
    workflow.add_node("salvamento", no_salvamento)
    workflow.add_node("menu_principal", no_menu_principal)
    
    # Definir ponto de entrada
    workflow.set_entry_point("recepcao")
    
    # Adicionar rotas condicionais
    workflow.add_conditional_edges(
        "recepcao",
        determinar_rota,
        {
            "coleta_dados": "coleta_dados",
            "menu_principal": "menu_principal",
            "fim": END
        }
    )
    
    workflow.add_conditional_edges(
        "coleta_dados",
        determinar_rota,
        {
            "coleta_dados": "coleta_dados",
            "validacao": "validacao",
            "fim": END
        }
    )
    
    workflow.add_conditional_edges(
        "validacao",
        determinar_rota,
        {
            "salvamento": "salvamento",
            "coleta_dados": "coleta_dados",
            "fim": END
        }
    )
    
    workflow.add_conditional_edges(
        "salvamento",
        determinar_rota,
        {
            "fim": END
        }
    )
    
    workflow.add_conditional_edges(
        "menu_principal",
        determinar_rota,
        {
            "menu_principal": "menu_principal",
            "coleta_dados": "coleta_dados",
            "fim": END
        }
    )
    
    # Compilar com checkpoint para persistência
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


@traceable
async def processar_fluxo_artista(
    telefone: str, 
    mensagem: str, 
    estado: EstadoConversa, 
    supabase: SupabaseManager
) -> str:
    """Função principal para processar mensagem através do fluxo"""
    try:
        # Criar instância do fluxo
        fluxo = criar_fluxo_artista()
        
        # Preparar estado inicial
        estado_inicial = {
            "mensagem_usuario": mensagem,
            "telefone": telefone,
            "artista_atual": None,
            "dados_coletados": estado.dados_coletados,
            "etapa": estado.etapa_atual if estado.etapa_atual != "inicio" else "recepcao",
            "resposta_bot": "",
            "finalizado": False,
            "erro": None,
            "tentativas": estado.tentativas_coleta
        }
        
        # Configurar thread_id para persistência
        config = {"configurable": {"thread_id": telefone}}
        
        # Executar fluxo
        resultado = await fluxo.ainvoke(estado_inicial, config)
        
        # Atualizar estado da conversa
        estado.dados_coletados = resultado["dados_coletados"]
        estado.etapa_atual = resultado["etapa"]
        estado.tentativas_coleta = resultado.get("tentativas", 0)
        estado.mensagens_historico.append(mensagem)
        
        # Manter apenas últimas 10 mensagens no histórico
        if len(estado.mensagens_historico) > 10:
            estado.mensagens_historico = estado.mensagens_historico[-10:]
        
        # Atualizar ID do artista se foi criado
        if resultado.get("artista_atual") and not estado.artista_id:
            estado.artista_id = resultado["artista_atual"].id
        
        # Salvar estado atualizado no banco
        try:
            supabase.salvar_estado_conversa(telefone, estado)
        except Exception as e:
            logger.warning(f"Erro ao salvar estado da conversa: {str(e)}")
        
        resposta = resultado["resposta_bot"]
        
        # Log da interação
        logger.info(f"Fluxo processado - Telefone: {telefone}, Etapa: {resultado['etapa']}")
        
        return resposta
        
    except Exception as e:
        logger.error(f"Erro ao processar fluxo do artista: {str(e)}")
        return (
            "Desculpe, ocorreu um problema técnico. "
            "Tente enviar sua mensagem novamente."
        )


def reiniciar_conversa(telefone: str, supabase: SupabaseManager) -> EstadoConversa:
    """Reinicia uma conversa, limpando o estado"""
    try:
        # Criar novo estado
        novo_estado = EstadoConversa(
            etapa_atual="inicio",
            dados_coletados={},
            tentativas_coleta=0,
            mensagens_historico=[]
        )
        
        # Salvar no banco
        supabase.salvar_estado_conversa(telefone, novo_estado)
        
        logger.info(f"Conversa reiniciada para telefone: {telefone}")
        return novo_estado
        
    except Exception as e:
        logger.error(f"Erro ao reiniciar conversa: {str(e)}")
        return EstadoConversa()


def obter_progresso_conversa(estado: EstadoConversa) -> dict[str, Any]:
    """Calcula o progresso atual da conversa"""
    campos_obrigatorios = ["nome"]
    campos_opcionais = ["cidade", "estilo_musical", "biografia", "experiencia_anos"]
    campos_links = ["instagram", "youtube", "spotify"]
    
    dados = estado.dados_coletados
    
    # Campos obrigatórios preenchidos
    obrigatorios_preenchidos = sum(1 for campo in campos_obrigatorios if dados.get(campo))
    
    # Campos opcionais preenchidos
    opcionais_preenchidos = sum(1 for campo in campos_opcionais if dados.get(campo))
    
    # Links preenchidos
    links_preenchidos = sum(1 for campo in campos_links if dados.get(campo))
    
    # Calcular progresso geral (0-100%)
    total_campos = len(campos_obrigatorios) + len(campos_opcionais) + len(campos_links)
    campos_preenchidos = obrigatorios_preenchidos + opcionais_preenchidos + links_preenchidos
    progresso = (campos_preenchidos / total_campos) * 100
    
    return {
        "progresso_percentual": round(progresso, 1),
        "campos_obrigatorios": obrigatorios_preenchidos,
        "campos_opcionais": opcionais_preenchidos,
        "links_preenchidos": links_preenchidos,
        "etapa_atual": estado.etapa_atual,
        "tentativas": estado.tentativas_coleta
    }