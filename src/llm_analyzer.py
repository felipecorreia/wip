"""
Módulo de Análise LLM Universal
Analisa todas as mensagens para extrair intenção, entidades e contexto
"""

import logging
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

from .llm_config import EnhancedLLMConfig

logger = logging.getLogger(__name__)


# Enums para classificação
class Intencao(str, Enum):
    """Intenções possíveis detectadas nas mensagens"""
    CADASTRO_INICIAL = "cadastro_inicial"  # Novo artista se apresentando
    CADASTRO_COMPLEMENTO = "cadastro_complemento"  # Fornecendo dados faltantes
    CONSULTA_AGENDA = "consulta_agenda"  # Quer saber datas disponíveis
    ATUALIZAR_DADOS = "atualizar_dados"  # Mudar informações cadastradas
    INFO_CASA = "info_casa"  # Informações sobre a cervejaria
    SAUDACAO = "saudacao"  # Cumprimento inicial
    DESPEDIDA = "despedida"  # Finalizando conversa
    DUVIDA = "duvida"  # Pergunta geral
    FEEDBACK = "feedback"  # Elogio ou reclamação
    CONFIRMAR_SHOW = "confirmar_show"  # Confirmar data de apresentação
    CANCELAR = "cancelar"  # Cancelar ou desistir
    DESCONHECIDA = "desconhecida"  # Não foi possível classificar


class Sentimento(str, Enum):
    """Sentimento detectado na mensagem"""
    POSITIVO = "positivo"
    NEUTRO = "neutro"
    NEGATIVO = "negativo"
    ANSIOSO = "ansioso"
    FRUSTRADO = "frustrado"


class Contexto(str, Enum):
    """Contexto da conversa"""
    NOVO_USUARIO = "novo_usuario"
    USUARIO_RETORNANDO = "usuario_retornando"
    COMPLETANDO_CADASTRO = "completando_cadastro"
    CONVERSA_ATIVA = "conversa_ativa"
    URGENTE = "urgente"


class Urgencia(str, Enum):
    """Nível de urgência detectado"""
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


# Schemas Pydantic
class EntidadesExtraidas(BaseModel):
    """Entidades extraídas da mensagem"""
    nome: Optional[str] = Field(None, description="Nome do artista ou banda mencionado")
    estilo_musical: Optional[str] = Field(None, description="Estilo musical mencionado (rock, jazz, mpb, etc)")
    cidade: Optional[str] = Field(None, description="Cidade de origem mencionada")
    instagram: Optional[str] = Field(None, description="@usuario ou link do Instagram se mencionado (ex: @fug_jazz)")
    youtube: Optional[str] = Field(None, description="@usuario, canal ou link do YouTube se mencionado (ex: @fug_jazz)")
    spotify: Optional[str] = Field(None, description="Link do Spotify se mencionado")
    data_show: Optional[str] = Field(None, description="Data mencionada para show")
    horario: Optional[str] = Field(None, description="Horário mencionado")
    telefone_adicional: Optional[str] = Field(None, description="Telefone adicional mencionado")
    email: Optional[str] = Field(None, description="Email mencionado")


class AnaliseIntent(BaseModel):
    """Resultado completo da análise de uma mensagem"""
    intencao: Intencao = Field(
        default=Intencao.DESCONHECIDA,
        description="Intenção principal detectada na mensagem"
    )
    intencao_secundaria: Optional[Intencao] = Field(
        None,
        description="Intenção secundária se houver"
    )
    entidades: EntidadesExtraidas = Field(
        default_factory=EntidadesExtraidas,
        description="Entidades extraídas da mensagem"
    )
    contexto: Contexto = Field(
        default=Contexto.NOVO_USUARIO,
        description="Contexto da conversa"
    )
    sentimento: Sentimento = Field(
        default=Sentimento.NEUTRO,
        description="Sentimento detectado"
    )
    urgencia: Urgencia = Field(
        default=Urgencia.BAIXA,
        description="Nível de urgência"
    )
    palavras_chave: List[str] = Field(
        default_factory=list,
        description="Palavras-chave importantes na mensagem"
    )
    confianca: float = Field(
        default=0.0,
        description="Nível de confiança da análise (0-1)"
    )
    precisa_acao_humana: bool = Field(
        default=False,
        description="Se precisa de intervenção humana"
    )
    resumo: Optional[str] = Field(
        None,
        description="Resumo da mensagem em uma linha"
    )


async def analisar_mensagem_llm(
    mensagem: str,
    historico: Optional[List[str]] = None,
    dados_coletados: Optional[Dict[str, Any]] = None,
    artista_existente: bool = False
) -> AnaliseIntent:
    """
    Analisa uma mensagem usando LLM para extrair intenção, entidades e contexto.
    
    Args:
        mensagem: Mensagem atual do usuário
        historico: Histórico de mensagens anteriores
        dados_coletados: Dados já coletados do usuário
        artista_existente: Se o usuário já está cadastrado
        
    Returns:
        AnaliseIntent com toda análise estruturada
    """
    
    llm_config = EnhancedLLMConfig()
    
    try:
        provider_name, llm = llm_config.get_available_provider()
        logger.info(f"Analisando mensagem com {provider_name}")
    except Exception as e:
        logger.error(f"Nenhum provedor LLM disponível: {e}")
        return AnaliseIntent(
            intencao=Intencao.DESCONHECIDA,
            precisa_acao_humana=True
        )
    
    # LLM com saída estruturada
    structured_llm = llm.with_structured_output(AnaliseIntent)
    
    # Construir contexto
    contexto_str = ""
    if historico:
        contexto_str = "Histórico recente:\n" + "\n".join(historico[-5:])  # Últimas 5 mensagens
    
    dados_str = ""
    if dados_coletados:
        dados_str = f"Dados já coletados: {dados_coletados}"
    
    # Prompt otimizado para análise
    prompt = f"""
Você é um assistente especializado em analisar mensagens de artistas e bandas 
que querem se apresentar na Cervejaria Bragantina.

CONTEXTO:
- Usuário já cadastrado: {artista_existente}
{contexto_str}
{dados_str}

MENSAGEM ATUAL DO USUÁRIO:
"{mensagem}"

ANALISE a mensagem e classifique:

1. INTENÇÃO PRINCIPAL - Escolha apenas UMA:
   - cadastro_inicial: Artista novo se apresentando pela primeira vez
   - cadastro_complemento: Fornecendo informações que faltam no cadastro
   - consulta_agenda: Perguntando sobre datas, disponibilidade, shows
   - atualizar_dados: Querendo mudar informações já cadastradas
   - info_casa: Perguntando sobre a cervejaria, localização, funcionamento
   - saudacao: Apenas cumprimentando (oi, olá, bom dia, etc)
   - despedida: Se despedindo (tchau, até mais, obrigado)
   - duvida: Pergunta geral que não se encaixa nas outras
   - feedback: Elogio, reclamação ou sugestão
   - confirmar_show: Confirmando uma data específica
   - cancelar: Cancelando, desistindo ou pedindo para parar

2. ENTIDADES - Extraia APENAS o que está explícito na mensagem:
   - Nome da banda/artista
   - Estilo musical  
   - Cidade
   - Instagram: @usuario ou links (ex: @fug_jazz, instagram.com/banda)
   - YouTube: @usuario, canal ou links (ex: @fug_jazz, youtube.com/banda)
   - Spotify: links do artista ou @usuario ou (ex: @fug_jazz, spotify.com/banda))
   - IMPORTANTE: Se o usuário mencionar "meu instagram é @xyz" ou "youtube e instagram são @xyz" ou "minhas redes são @xyz", 
     extraia @xyz para AMBOS os campos se mencionados
   - Datas mencionadas
   - Contatos adicionais

3. CONTEXTO - Baseado no histórico:
   - novo_usuario: Primeira interação
   - usuario_retornando: Já interagiu antes
   - completando_cadastro: Está no meio do processo de cadastro
   - conversa_ativa: Conversa em andamento
   - urgente: Mensagem indica urgência

4. SENTIMENTO:
   - positivo: Animado, feliz, elogiando
   - neutro: Sem emoção clara
   - negativo: Reclamando, insatisfeito
   - ansioso: Apressado, preocupado
   - frustrado: Irritado, impaciente

5. URGÊNCIA:
   - alta: Precisa de resposta imediata (palavras como "urgente", "agora", "hoje")
   - media: Normal
   - baixa: Pode esperar

6. CONFIANÇA:
   - 0.0 a 1.0 baseado em quão clara é a intenção

IMPORTANTE:
- Se a mensagem mencionar "tocar", "apresentar", "mostrar", "show" mas o usuário NÃO está cadastrado, classifique como cadastro_inicial
- Se já está cadastrado e menciona essas palavras, classifique como consulta_agenda
- Saudações no início de uma apresentação devem ser classificadas como cadastro_inicial, não saudacao
- Seja preciso: não invente informações que não estão na mensagem
"""
    
    try:
        logger.info(f"Analisando: '{mensagem[:100]}...'")
        analise = await structured_llm.ainvoke(prompt)
        
        # Ajustar confiança se necessário
        if analise.intencao == Intencao.DESCONHECIDA:
            analise.confianca = 0.0
            analise.precisa_acao_humana = True
        elif analise.confianca == 0.0:
            # Se o LLM não preencheu, calcular baseado na intenção
            if analise.intencao in [Intencao.SAUDACAO, Intencao.DESPEDIDA]:
                analise.confianca = 0.9
            elif analise.intencao in [Intencao.CADASTRO_INICIAL, Intencao.CONSULTA_AGENDA]:
                analise.confianca = 0.8
            else:
                analise.confianca = 0.7
        
        # Criar resumo se não foi fornecido
        if not analise.resumo:
            analise.resumo = f"{analise.intencao.value}: {mensagem[:50]}..."
        
        logger.info(f"Análise completa: Intenção={analise.intencao}, Confiança={analise.confianca}")
        logger.debug(f"Entidades extraídas: {analise.entidades.model_dump(exclude_unset=True)}")
        
        return analise
        
    except Exception as e:
        logger.error(f"Erro na análise LLM: {e}")
        return AnaliseIntent(
            intencao=Intencao.DESCONHECIDA,
            sentimento=Sentimento.NEUTRO,
            precisa_acao_humana=True,
            confianca=0.0,
            resumo=f"Erro na análise: {str(e)[:50]}"
        )


async def analisar_multiplas_mensagens(
    mensagens: List[str],
    contexto_global: Optional[Dict[str, Any]] = None
) -> List[AnaliseIntent]:
    """
    Analisa múltiplas mensagens em batch para testes
    
    Args:
        mensagens: Lista de mensagens para analisar
        contexto_global: Contexto aplicável a todas
        
    Returns:
        Lista de análises
    """
    resultados = []
    
    for mensagem in mensagens:
        analise = await analisar_mensagem_llm(
            mensagem=mensagem,
            dados_coletados=contexto_global
        )
        resultados.append(analise)
    
    return resultados


# Funções auxiliares para casos específicos
def e_saudacao_simples(mensagem: str) -> bool:
    """Verifica se é apenas uma saudação simples"""
    saudacoes = [
        "oi", "olá", "ola", "oie", "oii",
        "bom dia", "boa tarde", "boa noite",
        "hey", "hello", "e ai", "eai",
        "tudo bem", "tudo bom", "como vai"
    ]
    msg_lower = mensagem.lower().strip()
    return any(msg_lower == s or msg_lower.startswith(s + " ") for s in saudacoes)


def menciona_apresentacao(mensagem: str) -> bool:
    """Verifica se menciona interesse em se apresentar"""
    palavras = [
        "tocar", "apresentar", "show", "banda", "artista",
        "música", "cantor", "cantora", "grupo", "duo", "trio",
        "som", "trabalho", "repertório", "set", "palco"
    ]
    msg_lower = mensagem.lower()
    return any(palavra in msg_lower for palavra in palavras)


def extrair_data_mencionada(mensagem: str) -> Optional[str]:
    """Extrai datas mencionadas na mensagem"""
    import re
    
    # Padrões de data
    padroes = [
        r'\d{1,2}/\d{1,2}',  # 23/08
        r'\d{1,2} de \w+',   # 23 de agosto
        r'dia \d{1,2}',       # dia 23
        r'sexta|sábado|domingo|segunda|terça|quarta|quinta',
        r'próxima? (?:sexta|sábado|domingo)',
        r'hoje|amanhã|depois de amanhã'
    ]
    
    for padrao in padroes:
        match = re.search(padrao, mensagem, re.IGNORECASE)
        if match:
            return match.group(0)
    
    return None