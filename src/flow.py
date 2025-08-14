import logging
import asyncio
from typing import TypedDict, Optional, Any
from uuid import uuid4

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langsmith import traceable

# Imports dos nossos módulos e schemas
from .schemas import Artista, Contato, Link, TipoContato, EstiloMusical, EstadoConversa
from .database import SupabaseManager
from .llm_extractor import extrair_dados_com_llm # <-- Nossa nova função!

logger = logging.getLogger(__name__)

# --- Definição do Estado do Grafo ---

class EstadoFluxo(TypedDict):
    """Estado do fluxo de conversação do LangGraph."""
    mensagem_usuario: str
    telefone: str
    estado_conversa: EstadoConversa
    resposta_bot: str
    finalizado: bool
    tentativas_coleta: int

# --- Funções Auxiliares do Grafo ---

def dados_sao_suficientes(dados: dict[str, Any]) -> bool:
    """Verifica se os dados mínimos para criar um artista foram coletados."""
    tem_nome = "nome" in dados and dados["nome"]
    tem_estilo = "estilo_musical" in dados and dados["estilo_musical"]
    tem_link = any(key in dados and dados[key] for key in ["instagram", "youtube", "spotify"])
    return tem_nome and tem_estilo and tem_link

# --- Nós do LangGraph ---

@traceable
def no_recepcao(state: EstadoFluxo) -> EstadoFluxo:
    """
    Nó inicial. Verifica se o artista já existe e direciona o fluxo.
    Se for novo, envia uma saudação e prepara para a coleta de dados.
    """
    telefone = state["telefone"]
    supabase = SupabaseManager()
    
    artista_existente = supabase.buscar_artista_por_telefone(telefone)
    
    if artista_existente and dados_sao_suficientes(artista_existente.model_dump()):
        logger.info(f"Artista existente e completo encontrado: {artista_existente.nome}")
        state["resposta_bot"] = (
            f"Olá {artista_existente.nome}, que bom te ver de novo! 👋\n\n"
            "Como posso te ajudar hoje? (Ex: ver agenda, atualizar dados, etc.)"
        )
        state["finalizado"] = True # Finaliza o fluxo por aqui por enquanto
    else:
        logger.info(f"Novo artista ou cadastro incompleto para {telefone}. Iniciando coleta.")
        state["resposta_bot"] = (
            "Olá! Sou a WIP, assistente de agendamento da Cervejaria Bragantina 🍺\n\n"
            "Que legal que você chegou por aqui! Para começar, me conta um pouco sobre você ou sua banda. "
            "Pode me dizer seu nome, estilo, cidade e já mandar o link do seu som (Instagram, YouTube, etc.)."
        )
        state["finalizado"] = False
        
    return state

@traceable
def no_coleta_dados(state: EstadoFluxo) -> EstadoFluxo:
    """
    Nó principal de coleta. Usa o LLM para extrair dados da mensagem do usuário
    e gera uma resposta contextual pedindo as informações que faltam.
    """
    mensagem = state["mensagem_usuario"]
    estado_conversa = state["estado_conversa"]
    state["tentativas_coleta"] += 1

    
    # Chama nossa função de extração com LLM
    dados_extraidos_obj = asyncio.run(
        extrair_dados_com_llm(mensagem, estado_conversa.mensagens_historico)
    )
    dados_extraidos_dict = dados_extraidos_obj.model_dump(exclude_unset=True)
    
    # Atualiza os dados coletados no estado
    estado_conversa.dados_coletados.update(dados_extraidos_dict)
    
    # Gera uma resposta inteligente com base no que falta
    dados_coletados = estado_conversa.dados_coletados
    nome_artista = dados_coletados.get("nome", "você") # Pega o nome do artista se já souber

    if not dados_coletados.get("nome"):
        state["resposta_bot"] = "Recebido! Para começar, pode me dizer qual o nome da sua banda ou projeto musical?"
    elif not dados_coletados.get("estilo_musical"):
        state["resposta_bot"] = f"Prazer, {nome_artista}! E qual o estilo de som de vocês (rock, pop, mpb...)?"
    elif not any(key in dados_coletados and dados_coletados[key] for key in ["instagram", "youtube", "spotify"]):
        # Esta é a resposta mais importante para a conversa parcial
        state["resposta_bot"] = f"Show de bola, {nome_artista}! Anotei aqui que o som é {dados_coletados.get('estilo_musical')}. Para fechar, só preciso que me envie o link do seu Instagram, YouTube ou Spotify para eu conhecer seu trabalho."
    else:
        # Se já tem tudo, agradece e avisa que está finalizando
        state["resposta_bot"] = f"Perfeito, {nome_artista}! Recebi tudo que precisava. Só um momento enquanto finalizo seu cadastro..."

    state["finalizado"] = False
    return state


@traceable
def no_salvamento(state: EstadoFluxo) -> EstadoFluxo:
    """
    Nó final. Salva o artista no banco de dados e envia a resposta final
    com a análise do "Bot Curador" e a oferta da lista de furos.
    """
    dados = state["estado_conversa"].dados_coletados
    telefone = state["telefone"]
    supabase = SupabaseManager()

    try:
        # Mapeia o estilo para o Enum (com fallback para "outro")
        estilo_str = dados.get("estilo_musical", "outro").lower()
        estilo_musical = next((estilo for estilo in EstiloMusical if estilo.value == estilo_str), EstiloMusical.OUTRO)

        # Cria o objeto Artista para salvar
        artista = Artista(
            id=uuid4(),
            nome=dados.get("nome"),
            cidade=dados.get("cidade"),
            estilo_musical=estilo_musical,
            links=Link(
                instagram=dados.get("instagram"),
                youtube=dados.get("youtube"),
                spotify=dados.get("spotify")
            ),
            contatos=[Contato(tipo=TipoContato.WHATSAPP, valor=telefone.replace("whatsapp:", ""), principal=True)]
        )

        # Salva no banco de dados
        tenant_id = "b2894499-6bf5-4e91-8853-fa16c59ddf40" # Cervejaria Bragantina
        resultado = supabase.salvar_artista(artista, tenant_id=tenant_id)
        if not resultado["success"]:
            raise Exception(resultado.get("error", "Erro desconhecido ao salvar artista."))

        logger.info(f"Artista {artista.nome} salvo com sucesso.")
        state["estado_conversa"].artista_id = artista.id

        # --- Lógica do "Bot Curador" (Mockada) ---
        
        # 1. Feedback personalizado sobre o material
        feedback_curador = "Dei uma olhada no seu material, o trabalho é muito profissional! Parabéns! 👏"
        
        # 2. Resposta da agenda com oferta da lista de furos
        resposta_agenda = (
            f"Seu cadastro na nossa rede de talentos foi concluído com sucesso. ✅\n\n"
            f"Sobre a agenda da Cervejaria Bragantina, as datas deste mês já estão fechadas, "
            f"mas tenho uma oportunidade legal pra você: a WIP gerencia a agenda de várias casas de show e sempre aparecem "
            f"oportunidades para cobrir furos de última hora.\n\n"
            f"**Gostaria de entrar na nossa lista de substitutos?** Assim, você pode ser chamado para tocar a qualquer momento!"
        )

        state["resposta_bot"] = f"{feedback_curador}\n\n{resposta_agenda}"

    except Exception as e:
        logger.error(f"Erro no nó de salvamento: {e}")
        state["resposta_bot"] = "Opa, tive um problema para finalizar seu cadastro. Poderia tentar me enviar sua última informação novamente?"

    state["finalizado"] = True
    return state

# --- Lógica de Roteamento do Grafo ---

def determinar_rota(state: EstadoFluxo) -> str:
    """Determina qual nó executar a seguir."""
    if state["tentativas_coleta"] >= 3:
        logger.warning(f"Limite de 3 tentativas de coleta atingido para {state['telefone']}. Finalizando fluxo.")
        # Prepara uma mensagem de erro amigável antes de finalizar
        state["resposta_bot"] = "Parece que estou com dificuldade para processar sua mensagem. Poderia tentar novamente mais tarde ou contatar nosso suporte?"
        return END

    if state["finalizado"]:
        return END
    
    if not state["estado_conversa"].dados_coletados:
        # Na primeira vez, não deve ir para recepção de novo, então direcionamos para coleta
        return "coleta_dados"
        
    if dados_sao_suficientes(state["estado_conversa"].dados_coletados):
        return "salvamento"
    
    return "coleta_dados"


# --- Função Principal de Construção e Execução do Grafo ---

def criar_fluxo_artista() -> StateGraph:
    """Cria e compila o StateGraph para o fluxo de conversação."""
    workflow = StateGraph(EstadoFluxo)

    workflow.add_node("recepcao", no_recepcao)
    workflow.add_node("coleta_dados", no_coleta_dados)
    workflow.add_node("salvamento", no_salvamento)

    workflow.set_entry_point("recepcao")

    workflow.add_conditional_edges(
        "recepcao",
        lambda s: END if s["finalizado"] else "coleta_dados"
    )
    workflow.add_conditional_edges(
        "coleta_dados",
        determinar_rota,
        {
            "salvamento": "salvamento",
            "coleta_dados": "coleta_dados", # Permite loop para coletar mais dados
            END: END 
        }
    )
    workflow.add_edge("salvamento", END)
    
    # Usar um checkpointer em memória para conversas curtas
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

# Instância global do fluxo compilado para reutilização
fluxo_compilado = criar_fluxo_artista()

async def processar_fluxo_artista(
    telefone: str, 
    mensagem: str, 
    estado: EstadoConversa
) -> str:
    """
    Função principal que invoca o LangGraph para processar a mensagem do usuário.
    """
    try:
        # Prepara o estado inicial para esta execução do grafo
        estado_inicial = {
            "mensagem_usuario": mensagem,
            "telefone": telefone,
            "estado_conversa": estado,
            "resposta_bot": "",
            "finalizado": False,
            "tentativas_coleta": 0
        }
        
        # Configura o ID da thread para manter a memória da conversa
        config = {"configurable": {"thread_id": telefone}}
        
        # Invoca o fluxo
        resultado_final = await fluxo_compilado.ainvoke(estado_inicial, config)
        
        # Atualiza o estado da conversa principal com os dados do grafo
        estado.dados_coletados = resultado_final["estado_conversa"].dados_coletados
        if resultado_final["estado_conversa"].artista_id:
            estado.artista_id = resultado_final["estado_conversa"].artista_id
        
        # Adiciona a mensagem ao histórico
        estado.mensagens_historico.append(f"Usuário: {mensagem}")
        estado.mensagens_historico.append(f"Bot: {resultado_final['resposta_bot']}")
        # Limita o histórico para as últimas 10 trocas
        estado.mensagens_historico = estado.mensagens_historico[-20:]
        
        logger.info(f"Fluxo LangGraph concluído para {telefone}. Resposta: {resultado_final['resposta_bot'][:70]}...")
        return resultado_final["resposta_bot"]
        
    except Exception as e:
        logger.error(f"Erro crítico ao processar o fluxo do artista: {e}", exc_info=True)
        return "Desculpe, ocorreu um problema técnico. Por favor, tente enviar sua mensagem novamente."

