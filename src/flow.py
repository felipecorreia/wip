import logging
import asyncio
from typing import TypedDict, Optional, Any
from uuid import uuid4

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langsmith import traceable

# Imports dos nossos módulos e schemas
from .schemas import Artista, Contato, Link, TipoContato, EstiloMusical, EstadoConversa, DadosExtraidos
from .database import SupabaseManager
from .llm_extractor import extrair_dados_com_llm
from .llm_analyzer import analisar_mensagem_llm
from .message_humanizer import MessageHumanizer
from .llm_analyzer import AnaliseIntent


logger = logging.getLogger(__name__)

# --- Definição do Estado do Grafo ---

class AgentState(TypedDict):
    """Estado unificado do agente LangGraph."""
    # Estado da conversa (reutilizar estrutura existente)
    estado_conversa: EstadoConversa
    
    # Dados da mensagem atual
    mensagem_usuario: str
    telefone: str
    
    # Dados do artista
    artista: Optional[Artista]
    dados_extraidos: Optional[DadosExtraidos]
    analise_intent: Optional[AnaliseIntent]
    
    # Controle de fluxo
    next_action: str
    availability_found: bool
    partner_options: list
    user_accepts_alternative: bool
    
    # Saída
    final_message: str

# --- Nós do LangGraph ---
@traceable
async def router_node(state: AgentState) -> AgentState:
    """
    Nó roteador principal. Suas responsabilidades são:
    1.  Verificar se o artista já existe no banco de dados.
    2.  Analisar a mensagem do usuário para extrair intenção e entidades.
    3.  Normalizar e atualizar os dados coletados no estado da conversa.
    4.  Garantir que o objeto state['artista'] exista se o cadastro estiver completo.
    5.  NÃO decide o próximo passo, apenas prepara o estado para o roteador.
    """
    from .database import SupabaseManager
    from .llm_analyzer import analisar_mensagem_llm
    from .schemas import Artista # Certifique-se de que Artista está importado

    supabase = SupabaseManager()
    telefone = state["telefone"]
    mensagem = state["mensagem_usuario"]
    
    # 1. Verificar se o artista já existe no banco
    artista_existente = supabase.buscar_artista_por_telefone(telefone)
    state["artista"] = artista_existente
    
    # 2. Analisar a intenção e entidades com LLM
    analise = await analisar_mensagem_llm(
        mensagem=mensagem,
        historico=state["estado_conversa"].mensagens_historico,
        dados_coletados=state["estado_conversa"].dados_coletados,
        artista_existente=bool(artista_existente)
    )
    state["analise_intent"] = analise
    logger.info(f"DEBUG: 'analise_intent' foi adicionado ao estado. Conteúdo: {state.get('analise_intent')}")

    
    # 3. Normalizar e atualizar os dados coletados no estado
    if analise.entidades:
        entidades_dict = analise.entidades.model_dump(exclude_none=True)
        
        for campo, valor in entidades_dict.items():
            if valor is not None and isinstance(valor, str):
                if campo == 'estilo_musical':
                    valor_normalizado = valor.lower().strip()
                elif campo in ['nome', 'cidade']:
                    valor_normalizado = valor.strip().title()
                else:
                    valor_normalizado = valor.strip()
                state["estado_conversa"].dados_coletados[campo] = valor_normalizado
            elif valor is not None:
                state["estado_conversa"].dados_coletados[campo] = valor
    
    # 4. Garantir a consistência do objeto state['artista'] em memória
    dados_coletados = state["estado_conversa"].dados_coletados
    campos_obrigatorios = ["nome", "estilo_musical", "cidade"]
    cadastro_completo = all(dados_coletados.get(campo) for campo in campos_obrigatorios)

    if cadastro_completo and not state.get("artista"):
        # Se o cadastro está completo nos dados, mas o objeto não foi carregado do banco,
        # criamos uma instância em memória para os nós seguintes usarem.
        logger.info("Cadastro completo detectado em dados coletados. Criando objeto Artista em memória.")
        try:
            artista_em_memoria = Artista(
                nome=dados_coletados.get("nome"),
                cidade=dados_coletados.get("cidade"),
                estilo_musical=dados_coletados.get("estilo_musical")
            )
            state["artista"] = artista_em_memoria
        except Exception as e:
            logger.error(f"Falha ao criar objeto Artista em memória a partir dos dados coletados: {e}")
            state["artista"] = None

    # Log final antes de retornar o estado preparado
    logger.info(
        f"Router Node Concluído. "
        f"Artista no estado: {bool(state.get('artista'))}, "
        f"Intenção detectada: {analise.intencao if analise else 'N/A'}"
    )
    
    return state


@traceable
def user_management_node(state: AgentState) -> AgentState:
    """
    Nó de gerenciamento de usuários. Focado em criar ou atualizar o artista no banco.
    Aproveita os validadores definidos em schemas.py.
    """
    from .database import SupabaseManager
    from .schemas import DadosExtraidos, Artista, Contato, TipoContato, Link
    from uuid import uuid4

    supabase = SupabaseManager()
    dados_coletados = state["estado_conversa"].dados_coletados
    
    # 1. Verificar se temos os dados básicos
    campos_obrigatorios = ["nome", "estilo_musical", "cidade"]
    dados_completos = all(dados_coletados.get(campo) for campo in campos_obrigatorios)

    if not dados_completos:
        # Lógica para pedir dados faltantes (como já definido antes)
        nome = dados_coletados.get("nome")
        
        # Define a saudação padrão
        saudacao = f"Boa, {nome}! Sou a WIP, assistente virtual aqui da Cervejaria. É comigo que os artistas fazem o primeiro contato para fazer show por aqui" if nome else "Opah!! Sou a WIP, assistente virtual aqui da Cervejaria. É comigo que os artistas fazem o primeiro contato para fazer show por aqui"



        # Define a próxima pergunta
        if not nome:
            pergunta = "Para começar, qual o nome da sua banda ou seu nome artístico?"
            state["final_message"] = f"{saudacao} {pergunta}"
        elif not dados_coletados.get("estilo_musical"):
            pergunta = "Qual é o estilo musical de vocês?"
            state["final_message"] = f"{saudacao}\n\n{pergunta}"
        else: # Falta a cidade
            pergunta = "E de qual cidade vocês são?"
            state["final_message"] = f"{saudacao}\n\n{pergunta}"
            
        return state

    # 2. Se os dados estão completos, vamos criar ou atualizar.
    
    # Normalizar dados usando o schema DadosExtraidos para rodar os validadores
    try:
        dados_normalizados = DadosExtraidos(**dados_coletados)
    except Exception as e:
        logger.error(f"Erro de validação ao normalizar dados coletados: {e}")
        state["final_message"] = "Notei um problema com os dados que você enviou. Podemos tentar novamente?"
        return state

    artista_no_banco = supabase.buscar_artista_por_telefone(state["telefone"])

    if artista_no_banco:
        # --- FLUXO DE ATUALIZAÇÃO ---
        logger.info(f"Artista {artista_no_banco.nome} encontrado. Atualizando.")
        artista_atualizado = artista_no_banco
        artista_atualizado.nome = dados_normalizados.nome or artista_atualizado.nome
        artista_atualizado.cidade = dados_normalizados.cidade or artista_atualizado.cidade
        artista_atualizado.estilo_musical = dados_normalizados.estilo_musical or artista_atualizado.estilo_musical
        
        if dados_normalizados.instagram:
            if not artista_atualizado.links: artista_atualizado.links = Link()
            artista_atualizado.links.instagram = dados_normalizados.instagram
        
        resultado = supabase.atualizar_artista(artista_atualizado)
        if resultado.get("success"):
            state["artista"] = artista_atualizado
            state["final_message"] = f"Perfeito, {artista_atualizado.nome}! Seus dados foram atualizados."
        else:
            state["final_message"] = "Houve um problema ao atualizar seus dados."

    else:
        # --- FLUXO DE CRIAÇÃO ---
        logger.info("Artista não encontrado. Criando novo registro.")
        try:
            novo_artista = Artista(
                id=uuid4(),
                nome=dados_normalizados.nome,
                cidade=dados_normalizados.cidade,
                estilo_musical=dados_normalizados.estilo_musical,
                contatos=[Contato(tipo=TipoContato.WHATSAPP, valor=state["telefone"].replace("whatsapp:", ""), principal=True)],
                links=Link(instagram=dados_normalizados.instagram) if dados_normalizados.instagram else None
            )
            
            tenant_id = "b2894499-6bf5-4e91-8853-fa16c59ddf40"
            resultado = supabase.salvar_artista(novo_artista, tenant_id=tenant_id)
            
            if resultado.get("success"):
                state["artista"] = novo_artista
                state["estado_conversa"].artista_id = novo_artista.id
                state["final_message"] = (
                    f"Perfeito, {novo_artista.nome}! Cadastro básico completo.\n\n"
                    "Para conhecer seu trabalho, pode me enviar os links das suas redes sociais (Instagram, YouTube, etc.)?"
                )
            else:
                state["final_message"] = "Houve um problema ao criar seu cadastro."
        except Exception as e:
            logger.error(f"Erro ao criar objeto Artista ou salvar no banco: {e}")
            state["final_message"] = "Ocorreu um erro ao processar seu cadastro. A equipe já foi notificada."

    return state

@traceable
def availability_check_node(state: AgentState) -> AgentState:
    """
    Nó de verificação de disponibilidade de agenda.
    Verifica datas disponíveis para shows.
    """
    import random
    from datetime import datetime, timedelta
    
    # Mock de datas disponíveis (implementar integração real depois)
    hoje = datetime.now()
    
    # Dias da semana em português
    dias_semana = {
        'Monday': 'Segunda-feira',
        'Tuesday': 'Terça-feira', 
        'Wednesday': 'Quarta-feira',
        'Thursday': 'Quinta-feira',
        'Friday': 'Sexta-feira',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo'
    }
    
    # Gerar datas disponíveis (sextas e sábados das próximas 4 semanas)
    datas_disponiveis = []
    for dias in range(7, 30):
        data = hoje + timedelta(days=dias)
        # Apenas sextas (4) e sábados (5)
        if data.weekday() in [4, 5]:
            datas_disponiveis.append(data)
    
    # Simular disponibilidade (70% de chance de ter agenda)
    tem_disponibilidade = random.random() > 0.3
    
    if tem_disponibilidade and state["artista"]:
        state["availability_found"] = True
        
        # Pegar 2-3 datas aleatórias disponíveis
        num_datas = min(3, len(datas_disponiveis))
        datas_selecionadas = random.sample(datas_disponiveis, num_datas)
        datas_selecionadas.sort()
        
        # Formatar as datas
        datas_str = ""
        for data in datas_selecionadas:
            dia_semana = dias_semana.get(data.strftime('%A'), data.strftime('%A'))
            datas_str += f"• {dia_semana}, {data.strftime('%d/%m')} - 20h às 23h\n"
        
        state["final_message"] = (
            f"Olá {state['artista'].nome}! \n\n"
            f"Verificando nossa agenda... Temos estas datas disponíveis:\n\n"
            f"{datas_str}\n"
            f"Qual data seria melhor para vocês? Ou preferem que eu sugira outras opções?"
        )
    elif state["artista"]:
        state["availability_found"] = False
        state["final_message"] = (
            f"Olá {state['artista'].nome}!\n\n"
            f"Infelizmente não temos datas disponíveis no momento na Cervejaria Bragantina. \n\n"
            f"Mas não se preocupe! Fazemos parte de uma rede de casas parceiras."
        )
    else:
        # Se não tem artista cadastrado
        state["availability_found"] = False
        state["final_message"] = (
            "Para verificar nossa agenda, primeiro preciso que você faça seu cadastro.\n"
            "Por favor, me informe o nome da banda, estilo musical e cidade."
        )
    
    artista_nome = state.get('artista').nome if state.get('artista') else 'N/A'
    logger.info(f"Availability Check: Artista {artista_nome}, Disponibilidade: {state['availability_found']}")
    
    return state

@traceable
def partner_network_node(state: AgentState) -> AgentState:
    """
    Nó de rede de parceiros.
    Busca casas parceiras quando não há disponibilidade na casa principal.
    """
    # Mock de casas parceiras (implementar consulta real depois)
    casas_parceiras = [
        {
            "nome": "Casa do Rock", 
            "cidade": "São Paulo", 
            "estilos": ["rock", "metal", "punk"],
            "capacidade": 150
        },
        {
            "nome": "Sertão Bar", 
            "cidade": "Campinas", 
            "estilos": ["sertanejo", "sertanejo universitário", "forró"],
            "capacidade": 200
        },
        {
            "nome": "Blues House", 
            "cidade": "Santos", 
            "estilos": ["blues", "jazz", "mpb"],
            "capacidade": 100
        },
        {
            "nome": "Pop Station", 
            "cidade": "Jundiaí", 
            "estilos": ["pop", "pop rock", "indie"],
            "capacidade": 180
        },
        {
            "nome": "Acústico Lounge", 
            "cidade": "São Paulo", 
            "estilos": ["mpb", "acústico", "folk"],
            "capacidade": 80
        },
        {
            "nome": "Reggae Roots", 
            "cidade": "Guarujá", 
            "estilos": ["reggae", "ska", "dub"],
            "capacidade": 120
        }
    ]
    
    if state["artista"]:
        # Filtrar por estilo musical do artista
        artista = state["artista"]
        estilo_artista = artista.estilo_musical.value if artista.estilo_musical else "outro"
        
        # Buscar casas compatíveis
        opcoes_compativeis = []
        for casa in casas_parceiras:
            # Verificar se o estilo do artista está nos estilos da casa
            for estilo_casa in casa["estilos"]:
                if estilo_artista.lower() in estilo_casa.lower() or estilo_casa.lower() in estilo_artista.lower():
                    opcoes_compativeis.append(casa)
                    break
        
        # Se não encontrou compatível, pegar casas da mesma cidade
        if not opcoes_compativeis and artista.cidade:
            opcoes_compativeis = [
                casa for casa in casas_parceiras 
                if casa["cidade"].lower() == artista.cidade.lower()
            ]
        
        # Se ainda não tem opções, pegar 3 casas aleatórias
        if not opcoes_compativeis:
            import random
            opcoes_compativeis = random.sample(casas_parceiras, min(3, len(casas_parceiras)))
        
        if opcoes_compativeis:
            state["partner_options"] = opcoes_compativeis
            
            # Formatar opções de casas
            opcoes_str = ""
            for casa in opcoes_compativeis[:3]:  # Mostrar no máximo 3 opções
                estilos_str = ", ".join(casa["estilos"][:2])  # Mostrar até 2 estilos
                opcoes_str += (
                    f"🏠 **{casa['nome']}** ({casa['cidade']})\n"
                    f"   📍 Capacidade: {casa['capacidade']} pessoas\n"
                    f"   🎵 Estilos: {estilos_str}\n\n"
                )
            
            state["final_message"] = (
                f"Boa notícia, {artista.nome}! 🎉\n\n"
                f"Encontrei estas casas parceiras que podem ter interesse no trabalho de vocês:\n\n"
                f"{opcoes_str}"
                f"Gostaria que eu encaminhe seu contato para alguma delas? "
                f"Ou prefere que eu verifique todas as disponibilidades?"
            )
        else:
            state["partner_options"] = []
            state["final_message"] = (
                f"No momento não encontrei casas parceiras compatíveis com o estilo {estilo_artista}, "
                f"mas vou manter seu contato para futuras oportunidades! 📝\n\n"
                f"Assim que surgir algo, entro em contato com vocês."
            )
    else:
        # Se não tem artista cadastrado
        state["partner_options"] = []
        state["final_message"] = (
            "Para buscar casas parceiras, primeiro preciso conhecer melhor seu trabalho.\n"
            "Por favor, faça seu cadastro informando nome, estilo e cidade."
        )
    
    logger.info(f"Partner Network: Artista {state.get('artista', {}).get('nome', 'N/A')}, Opções encontradas: {len(state.get('partner_options', []))}")
    
    return state

@traceable
def information_node(state: AgentState) -> AgentState:
    """
    Nó de informações sobre a casa.
    Fornece detalhes sobre a Cervejaria Bragantina.
    """
    # Informações completas sobre a casa
    info_casa = """*Cervejaria Bragantina*

                *Localização**: Centro de Bragança Paulista - SP
                Fácil acesso pela Fernão Dias (45min de São Paulo)
                *Ambiente**: Espaço amplo com área interna e externa, ideal para shows ao vivo"""
    
    # Verificar se é uma despedida
    analise_intent = state.get("analise_intent")
    if analise_intent and hasattr(analise_intent, 'intencao') and analise_intent.intencao == "despedida":
        if state["artista"]:
            nome_artista = state["artista"].nome
            state["final_message"] = (
                f"Foi ótimo falar com você, {nome_artista}! \n\n"
                f"Obrigado pelo interesse na Cervejaria Bragantina. "
                f"Entraremos em contato em breve sobre oportunidades de shows.\n\n"
                f"Qualquer dúvida, estamos à disposição! Até logo! "
            )
        else:
            state["final_message"] = (
                f"Obrigado pelo contato! \n\n"
                f"Quando quiser fazer parte da nossa programação, é só voltar e fazer seu cadastro.\n"
                f"Até logo! "
            )
    # Informações gerais sobre a casa
    elif state["artista"]:
        nome_artista = state["artista"].nome
        state["final_message"] = (
            f"Olá {nome_artista}! Aqui estão as informações sobre nossa casa:\n\n"
            f"{info_casa}\n\n"
            f"Tem alguma dúvida específica? Posso verificar nossa agenda ou te ajudar com mais alguma coisa?"
        )
    else:
        state["final_message"] = (
            f"{info_casa}\n\n"
            f"Para fazer parte da nossa programação, faça seu cadastro informando nome, estilo e cidade!"
        )
    
    artista_nome = state.get('artista').nome if state.get('artista') else 'visitante'
    logger.info(f"Information Node: Informações fornecidas para {artista_nome}")
    
    return state

@traceable
def scheduling_node(state: AgentState) -> AgentState:
    """
    Nó de agendamento.
    Cria lead no CRM e confirma agendamento.
    """
    artista = state.get("artista")
    
    if not artista:
        state["final_message"] = (
            "Para agendar um show, primeiro preciso dos seus dados completos.\n"
            "Por favor, me diga nome da banda, estilo musical e cidade."
        )
        return state
    
    # Simular criação de lead no CRM (implementar integração real depois)
    from datetime import datetime
    
    lead_info = {
        "artista_id": str(artista.id),
        "nome": artista.nome,
        "telefone": state["telefone"],
        "estilo": artista.estilo_musical.value if hasattr(artista.estilo_musical, 'value') else (artista.estilo_musical or "Não informado"),
        "cidade": artista.cidade or "Não informada",
        "status": "aguardando_contato",
        "data_criacao": datetime.now().isoformat(),
        "origem": "whatsapp_bot"
    }
    
    # Log do lead (em produção, seria enviado para o CRM real)
    logger.info(f"Lead criado no CRM: {lead_info}")
    
    # Verificar se veio de uma seleção de data específica
    if state.get("availability_found"):
        state["final_message"] = (
            f" *Ótimo, {artista.nome}!*\n\n"
            f"Tenho todas as infos que preciso!\n\n"
            f"*Próximos passos*:\n"
            f"Agora, nossa equipe vai analisar seu material artístico\n"
            f"Alguém vai falar com você em até 24h\n"
            f" Depois disso acertaremos data, cachê, etc\n"
            f"Blz?!!"
        )
    elif state.get("partner_options"):
        # Se veio da rede de parceiros
        casas_selecionadas = state["partner_options"][:2]  # Pegar até 2 casas
        casas_str = ", ".join([casa["nome"] for casa in casas_selecionadas])
        
        state["final_message"] = (
            f"✅ **Perfeito, {artista.nome}!**\n\n"
            f"Vou encaminhar seu contato para: {casas_str}\n\n"
            f"📋 **Como funciona**:\n"
            f"• Seu perfil e links serão enviados para as casas\n"
            f"• Elas vão dar uma olhada no seu material\n"
            f"• Em até 48h você vai receber um retorno\n"
            f"• Cada casa tem suas próprias condições\n\n"
            f"Boa sorte! {artista.nome}"
        )
    else:
        # Agendamento genérico
        state["final_message"] = (
            f"*Show, {artista.nome}!*\n\n"
            f"Bom demais saber que tem interesse em tocar aqui!\n\n"
            f"Nossa equipe de produção vai te chamar em breve "
            f"para falar sobre possíveis datas e condições.\n\n"
            f"Fica ligado no WhatsApp!"
        )
    
    # Marcar no estado que o agendamento foi processado
    state["estado_conversa"].etapa_atual = "agendamento_concluido"
    
    logger.info(f"Scheduling Node: Agendamento processado para {artista.nome}")
    
    return state

@traceable
def output_formatter(state: AgentState) -> AgentState:
    """
    Nó formatador de saída.
    Formata e quebra mensagens longas para o WhatsApp.
    """
    from .message_humanizer import MessageHumanizer
    
    mensagem = state.get("final_message", "")
    
    if not mensagem:
        # Se não houver mensagem final, criar uma mensagem padrão
        state["final_message"] = "Desculpe, não consegui processar sua mensagem. Por favor, tente novamente."
        return state
    
    # Usar humanizador se mensagem for muito longa
    if len(mensagem) > 300:  # Ajustado para 300 caracteres para WhatsApp
        try:
            humanizer = MessageHumanizer()
            mensagens_quebradas = humanizer.quebrar_resposta(mensagem)
            
            # Para WhatsApp, juntar com quebras de linha duplas
            # Mas limitar a 3 blocos para não ficar muito fragmentado
            if len(mensagens_quebradas) > 3:
                # Reagrupar em 3 blocos
                tamanho_bloco = len(mensagens_quebradas) // 3
                blocos = []
                for i in range(0, len(mensagens_quebradas), tamanho_bloco):
                    bloco = "\n\n".join(mensagens_quebradas[i:i+tamanho_bloco])
                    blocos.append(bloco)
                state["final_message"] = "\n\n---\n\n".join(blocos[:3])
            else:
                state["final_message"] = "\n\n".join(mensagens_quebradas)
                
        except Exception as e:
            logger.warning(f"Erro ao humanizar mensagem: {e}. Usando mensagem original.")
            # Se falhar, usar mensagem original
            state["final_message"] = mensagem
        
    # Log da formatação
    logger.info(f"Output Formatter: Mensagem formatada com {len(state['final_message'])} caracteres")
    
    return state

# --- Funções de Roteamento Condicional ---

def route_after_router(state: AgentState) -> str:
    """
    Função de roteamento principal.
    Analisa o estado e a intenção para decidir o próximo nó.
    """
    logger.info(f"DEBUG: Entrando em route_after_router. Chaves do estado recebido: {state.keys()}")
    logger.info(f"DEBUG: Conteúdo de 'analise_intent' recebido: {state.get('analise_intent')}")

    analise = state.get("analise_intent")
    artista = state.get("artista")
    
    # Fallback seguro se a análise falhar
    if not analise:
        logger.warning("Análise de intenção não encontrada no estado. Roteando para 'information' por segurança.")
        return "information"
        
    intencao = analise.intencao

    # Se a intenção é agendar E já temos um artista, vamos para a agenda.
    if intencao in ["consulta_agenda", "confirmar_show"] and artista:
        return "availability_check"
    
    # Se a intenção é de cadastro, vamos para o gerenciamento de usuário.
    elif intencao in ["cadastro_inicial", "cadastro_complemento", "atualizar_dados", "saudacao"]:
        return "user_management"
    
    # Se a intenção é uma despedida, vamos para o nó de informações (que trata despedidas).
    elif intencao == "despedida":
        return "information"
        
    # Para QUALQUER OUTRA COISA (dúvida, desconhecida, etc.):
    else:
        if artista:
            # Se já temos um artista, a dúvida mais comum é sobre agenda.
            return "availability_check"
        else:
            # Se não temos artista, tentamos o cadastro.
            return "user_management"



def route_after_availability(state: AgentState) -> str:
    """Roteamento após availability_check_node"""
    if state.get("availability_found", False):
        return "scheduling"
    else:
        return "partner_network"

def route_after_partner(state: AgentState) -> str:
    """Roteamento após partner_network_node"""
    # Simplificado: sempre vai para output_formatter
    # Em produção, poderia verificar se usuário aceita alternativa
    if state.get("partner_options"):
        # Se tem opções, pode ir para scheduling se usuário aceitar
        # Por enquanto, vamos direto para output
        return "output_formatter"
    else:
        return "output_formatter"

def route_after_user_management(state: AgentState) -> str:
    """Roteamento após user_management_node. Sempre vai para a saída."""
    # A lógica de qual pergunta fazer a seguir já foi tratada dentro do nó.
    # Agora, apenas formatamos a mensagem de saída.
    return "output_formatter"


# --- Construção e Compilação do Grafo ---

def get_graph():
    """
    Constrói e compila o grafo LangGraph com todos os nós e roteamentos.
    """
    from langgraph.graph import StateGraph, END
    
    # Criar o grafo
    workflow = StateGraph(AgentState)
    
    # Adicionar todos os nós
    workflow.add_node("router", router_node)
    workflow.add_node("user_management", user_management_node)
    workflow.add_node("availability_check", availability_check_node)
    workflow.add_node("partner_network", partner_network_node)
    workflow.add_node("information", information_node)
    workflow.add_node("scheduling", scheduling_node)
    workflow.add_node("output_formatter", output_formatter)
    
    # Definir ponto de entrada
    workflow.set_entry_point("router")
    
    # Adicionar arestas condicionais após o router
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "user_management": "user_management",
            "availability_check": "availability_check",
            "information": "information"
        }
    )
    
    # Adicionar arestas condicionais após availability check
    workflow.add_conditional_edges(
        "availability_check",
        route_after_availability,
        {
            "scheduling": "scheduling",
            "partner_network": "partner_network"
        }
    )
    
    # Adicionar arestas condicionais após partner network
    workflow.add_conditional_edges(
        "partner_network",
        route_after_partner,
        {
            "output_formatter": "output_formatter"
        }
    )
    
    # Adicionar arestas condicionais após user management
    workflow.add_conditional_edges(
        "user_management",
        route_after_user_management,
        {
            "output_formatter": "output_formatter"
        }
    )
    
    # Arestas diretas para o formatter
    workflow.add_edge("information", "output_formatter")
    workflow.add_edge("scheduling", "output_formatter")
    workflow.add_edge("output_formatter", END)
    
    # Compilar o grafo
    return workflow.compile()

# --- Função Principal de Processamento ---

async def processar_mensagem(telefone: str, mensagem: str, estado_conversa: EstadoConversa) -> str:
    """
    Função principal que processa uma mensagem usando o grafo LangGraph.
    
    Args:
        telefone: Número de telefone do usuário
        mensagem: Mensagem recebida do usuário
        estado_conversa: Estado atual da conversa
    
    Returns:
        Resposta formatada para o usuário
    """
    try:
        # Criar estado inicial do grafo
        initial_state: AgentState = {
            "estado_conversa": estado_conversa,
            "mensagem_usuario": mensagem,
            "telefone": telefone,
            "artista": None,
            "dados_extraidos": None,
            "next_action": "",
            "availability_found": False,
            "partner_options": [],
            "user_accepts_alternative": False,
            "final_message": ""
        }
        
        # Obter o grafo compilado
        workflow = get_graph()
        
        # Executar o grafo
        final_state = await workflow.ainvoke(initial_state)
        
        # Atualizar histórico da conversa
        estado_conversa.mensagens_historico.append(f"Usuario: {mensagem}")
        estado_conversa.mensagens_historico.append(f"Bot: {final_state['final_message']}")
        
        # Limitar histórico a 20 mensagens (10 interações)
        if len(estado_conversa.mensagens_historico) > 20:
            estado_conversa.mensagens_historico = estado_conversa.mensagens_historico[-20:]
        
        # Atualizar dados coletados se houver
        if final_state.get("dados_extraidos"):
            dados_dict = final_state["dados_extraidos"].model_dump(exclude_unset=True, exclude_none=True)
            estado_conversa.dados_coletados.update(dados_dict)
        
        # Atualizar ID do artista se foi criado/atualizado
        if final_state.get("artista") and final_state["artista"].id:
            estado_conversa.artista_id = final_state["artista"].id
        
        logger.info(f"Mensagem processada para {telefone}. Resposta: {final_state['final_message'][:100]}...")
        
        return final_state["final_message"]
        
    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}", exc_info=True)
        return "Opa! Tive um probleminha aqui com sua mensagem, pode me enviar mais uma vez?"

# Função síncrona wrapper para compatibilidade
def processar_mensagem_sync(telefone: str, mensagem: str, estado_conversa: EstadoConversa) -> str:
    """
    Wrapper síncrono para a função assíncrona processar_mensagem.
    """
    return asyncio.run(processar_mensagem(telefone, mensagem, estado_conversa))

