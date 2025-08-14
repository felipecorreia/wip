import logging
from typing import Optional

from .llm_config import EnhancedLLMConfig
from .schemas import DadosExtraidos

logger = logging.getLogger(__name__)

async def extrair_dados_com_llm(mensagem: str, historico_recente: Optional[list[str]] = None) -> DadosExtraidos:
    """
    Usa um LLM para extrair entidades da mensagem do usuário de forma estruturada.

    Args:
        mensagem: A mensagem mais recente do usuário.
        historico_recente: Uma lista opcional de mensagens anteriores para dar contexto.

    Returns:
        Um objeto Pydantic DadosExtraidos com as informações encontradas.
    """
    llm_config = EnhancedLLMConfig()
    
    # Pega o provedor de LLM disponível (Groq, OpenAI, etc.) que já tem fallback
    try:
        provider_name, llm = llm_config.get_available_provider()
        logger.info(f"Usando provedor de LLM: {provider_name}")
    except Exception as e:
        logger.error(f"Nenhum provedor de LLM disponível: {e}")
        # Retorna um objeto vazio para não quebrar o fluxo principal
        return DadosExtraidos()

    # Adiciona o schema Pydantic para garantir uma saída estruturada e confiável
    structured_llm = llm.with_structured_output(DadosExtraidos)

    # Constrói o histórico para dar mais contexto ao LLM
    contexto_conversa = ""
    if historico_recente:
        contexto_conversa = "\nContexto da conversa anterior:\n" + "\n".join(historico_recente)

    # Prompt que instrui o LLM sobre o que fazer.
    # É aqui que a "engenharia de prompt" acontece.
    prompt = f"""
    Você é um assistente especialista em analisar mensagens de músicos que entram em contato com uma casa de shows.
    Sua tarefa é extrair as seguintes informações da MENSAGEM MAIS RECENTE DO USUÁRIO: nome da banda/artista, cidade de origem,
    estilo musical e links para redes sociais (Instagram, YouTube, Spotify).

    Use o contexto da conversa anterior, se disponível, para ajudar a entender a mensagem atual, mas extraia os dados SOMENTE da mensagem mais recente.
    Se uma informação não estiver presente na mensagem mais recente, deixe o campo correspondente como nulo. Não invente informações.

    {contexto_conversa}

    MENSAGEM MAIS RECENTE DO USUÁRIO:
    ---
    {mensagem}
    ---
    """

    try:
        logger.info(f"Enviando para extração de dados com LLM: '{mensagem[:70]}...'")
        dados_extraidos = await structured_llm.ainvoke(prompt)
        logger.info(f"Dados extraídos pelo LLM: {dados_extraidos.model_dump(exclude_unset=True)}")

        return dados_extraidos
    except Exception as e:
        logger.error(f"Erro na chamada ao LLM para extração de dados: {e}")
        # Retorna um objeto vazio em caso de erro
        return DadosExtraidos()


