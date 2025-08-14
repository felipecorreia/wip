import os
import json
import time
import logging
from typing import Any, Optional, List, Tuple
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import SystemMessage, HumanMessage, BaseMessage
from langsmith import traceable
from .schemas import EstadoConversa, DadosExtraidos

logger = logging.getLogger(__name__)


class ProviderConfig:
    """Configuration for a single LLM provider with quota tracking"""
    def __init__(self, name: str, model: str, max_requests_per_minute: int = 60, timeout: int = 15):
        self.name = name
        self.model = model
        self.max_requests_per_minute = max_requests_per_minute
        self.timeout = timeout
        self.requests_history: List[float] = []
        self.is_available = True
        self.last_failure_time: Optional[float] = None
        self.failure_count = 0
        self.consecutive_failures = 0
        self.cooldown_until: Optional[float] = None

    def can_make_request(self) -> bool:
        """Check if provider can handle another request"""
        current_time = time.time()
        
        # Check if in cooldown period
        if self.cooldown_until and current_time < self.cooldown_until:
            return False
        
        # Reset cooldown if expired
        if self.cooldown_until and current_time >= self.cooldown_until:
            self.cooldown_until = None
            self.consecutive_failures = 0
            self.is_available = True
            logger.info(f"Provider {self.name} cooldown expired, re-enabling")
        
        # Clean old requests from history (keep last minute)
        self.requests_history = [
            req_time for req_time in self.requests_history 
            if current_time - req_time < 60
        ]
        
        # Check rate limit
        if len(self.requests_history) >= self.max_requests_per_minute:
            logger.warning(f"Provider {self.name} rate limited ({len(self.requests_history)} requests in last minute)")
            return False
        
        return self.is_available

    def record_request(self):
        """Record a successful request"""
        self.requests_history.append(time.time())
        self.consecutive_failures = 0  # Reset on success
        self.failure_count = 0
        self.is_available = True
        if self.cooldown_until:
            self.cooldown_until = None
            logger.info(f"Provider {self.name} recovered from failures")

    def record_failure(self, error_message: str = ""):
        """Record a failed request with intelligent cooldown"""
        current_time = time.time()
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = current_time
        
        # Check for quota/rate limit errors
        is_quota_error = any(indicator in error_message.lower() for indicator in [
            '429', 'quota', 'rate limit', 'exceeded', 'billing', 'resourceexhausted'
        ])
        
        if is_quota_error:
            # Longer cooldown for quota issues
            cooldown_duration = min(300 + (self.consecutive_failures * 60), 1800)  # 5-30 minutes
            self.cooldown_until = current_time + cooldown_duration
            logger.error(f"Provider {self.name} quota/rate limit exceeded. Cooldown for {cooldown_duration/60:.1f} minutes")
        else:
            # Shorter cooldown for other errors
            cooldown_duration = min(30 * (2 ** self.consecutive_failures), 300)  # Exponential backoff, max 5 min
            self.cooldown_until = current_time + cooldown_duration
            logger.warning(f"Provider {self.name} error. Cooldown for {cooldown_duration}s")
        
        # Disable if too many consecutive failures
        if self.consecutive_failures >= 3:
            self.is_available = False
            logger.error(f"Provider {self.name} disabled after {self.consecutive_failures} consecutive failures")

    def get_status(self) -> dict:
        """Get provider status information"""
        current_time = time.time()
        recent_requests = len([r for r in self.requests_history if current_time - r < 60])
        
        return {
            'name': self.name,
            'available': self.is_available,
            'recent_requests': recent_requests,
            'failure_count': self.failure_count,
            'consecutive_failures': self.consecutive_failures,
            'cooldown_remaining': max(0, (self.cooldown_until or 0) - current_time),
            'last_failure': self.last_failure_time
        }


class EnhancedLLMConfig:
    """Enhanced LLM configuration with cascading fallback support"""
    
    def __init__(self):
        # Get primary provider from environment, default to gemini
        primary_provider = os.getenv("LLM_PROVIDER", "gemini")
        
        # Define provider priority based on user preference
        if primary_provider == "gemini":
            # User prefers Gemini, but fallback to OpenAI when quota exceeded
            self.providers = [
                ProviderConfig("gemini", "gemini-1.5-flash", 15, 15),  # Lower limits for quota management
                ProviderConfig("openai", "gpt-4o-mini", 100, 15),      # Fallback option
                ProviderConfig("anthropic", "claude-3-haiku-20240307", 50, 15)
            ]
        elif primary_provider == "openai":
            self.providers = [
                ProviderConfig("openai", "gpt-4o-mini", 100, 15),
                ProviderConfig("anthropic", "claude-3-haiku-20240307", 50, 15),
                ProviderConfig("gemini", "gemini-1.5-flash", 15, 15)
            ]
        else:  # anthropic
            self.providers = [
                ProviderConfig("anthropic", "claude-3-haiku-20240307", 50, 15),
                ProviderConfig("openai", "gpt-4o-mini", 100, 15),
                ProviderConfig("gemini", "gemini-1.5-flash", 15, 15)
            ]
        
        self.temperature = 0.3
        self.max_tokens = 1000
        
        logger.info(f"Enhanced LLM Config initialized with primary: {primary_provider}")
        logger.info(f"Provider order: {[p.name for p in self.providers]}")
    
    def get_available_provider(self) -> Tuple[Optional[ProviderConfig], Optional[Any]]:
        """Get next available provider and its LLM instance"""
        
        for provider in self.providers:
            if provider.can_make_request():
                try:
                    llm = self._create_llm_instance(provider)
                    logger.info(f"Using provider: {provider.name} ({provider.model})")
                    return provider, llm
                except Exception as e:
                    logger.error(f"Failed to create {provider.name} instance: {str(e)}")
                    provider.record_failure(str(e))
                    continue
        
        logger.error("No available LLM providers!")
        return None, None
    
    def _create_llm_instance(self, provider: ProviderConfig):
        """Create LLM instance for given provider"""
        if provider.name == "openai":
            return ChatOpenAI(
                model=provider.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=provider.timeout,
                max_retries=0  # No auto-retry, we handle fallback manually
            )
        elif provider.name == "anthropic":
            return ChatAnthropic(
                model=provider.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=provider.timeout,
                max_retries=0  # No auto-retry
            )
        elif provider.name == "gemini":
            # Use much shorter timeout for faster failure detection
            return ChatGoogleGenerativeAI(
                model=provider.model,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                timeout=3,  # Very short timeout for fast quota error detection
                max_retries=0,  # No auto-retry
                transport="rest"  # Use REST API
            )
        else:
            raise ValueError(f"Unknown provider: {provider.name}")
    
    def get_provider_status(self) -> List[dict]:
        """Get status of all providers"""
        return [provider.get_status() for provider in self.providers]


# Legacy class for backward compatibility
class LLMConfig:
    """Legacy LLM configuration - deprecated, use EnhancedLLMConfig"""
    
    def __init__(self):
        self.enhanced_config = EnhancedLLMConfig()
        logger.warning("LLMConfig is deprecated, consider using EnhancedLLMConfig directly")
        
    def get_llm(self):
        """Get LLM using enhanced config fallback system"""
        provider, llm = self.enhanced_config.get_available_provider()
        if llm:
            return llm
        else:
            raise Exception("No available LLM providers")


# Sistema de prompts estruturado
SYSTEM_PROMPTS = {
    "coleta_dados": """Você é a WIP, assistente virtual da Cervejaria Bragantina em Bragança Paulista.
A Cervejaria é um espaço acolhedor de música ao vivo, focado em rock, MPB e música autoral.

Sua missão é cadastrar artistas e bandas para tocar na casa. Colete as informações:
1. Nome completo do artista ou banda
2. Cidade onde atua
3. Estilo musical principal
4. Links de redes sociais (Instagram, YouTube, Spotify)
5. Experiência em anos
6. Breve descrição do som/biografia

REGRAS IMPORTANTES:
- Seja casual e amigável, como quem conversa num bar
- Use linguagem descontraída mas profissional
- Faça uma pergunta por vez
- Se o artista fornecer múltiplas informações, reconheça todas
- Use emojis com moderação (🍺🎸🎤)
- Mencione a Cervejaria quando relevante

Responda sempre em português brasileiro.""",

    "validacao_dados": """Você é responsável por validar e normalizar dados de artistas.

Analise as informações fornecidas e:
1. Corrija erros de digitação
2. Padronize formatos (telefones, links)
3. Classifique estilos musicais nas categorias disponíveis
4. Identifique informações faltantes importantes

Retorne um JSON estruturado com os dados validados.""",

    "resposta_final": """Você é a WIP confirmando o cadastro de um artista.

Crie uma mensagem de confirmação que:
1. Agradeça o cadastro
2. Resuma as informações coletadas
3. Explique os próximos passos
4. Seja profissional mas acolhedora

Não use emojis.""",

    "extracao_dados": """Você é especialista em extrair informações específicas de texto livre.

IMPORTANTE: 
- "WIP" é o nome do bot/assistente, NÃO é o nome do artista
- Ignore saudações e cumprimentos genéricos
- Extraia apenas informações específicas sobre o artista/banda
- Se a mensagem é apenas uma saudação ("oi", "olá", "bom dia"), não extraia nome

Extraia as seguintes informações da mensagem do usuário:
- nome: Nome REAL do artista ou banda (ignore "WIP", "bot", saudações)
- cidade: Cidade onde atua
- estilo_musical: Estilo musical (rock, pop, mpb, sertanejo, funk, rap, eletronica, jazz, blues, reggae, outro)
- instagram: Link ou handle do Instagram
- youtube: Link do YouTube
- spotify: Link do Spotify
- biografia: Descrição ou biografia
- experiencia_anos: Anos de experiência (número inteiro)

Retorne APENAS um JSON válido com os dados encontrados. Se não encontrar algum dado, omita o campo.
Não inclua markdown, explicações ou texto adicional. Apenas JSON puro."""
}


@traceable
def processar_mensagem_llm_with_fallback(
    mensagem: str, 
    contexto: EstadoConversa, 
    tipo_prompt: str
) -> str:
    """Process message with provider fallback system"""
    
    enhanced_config = EnhancedLLMConfig()
    system_prompt = SYSTEM_PROMPTS.get(tipo_prompt, SYSTEM_PROMPTS["coleta_dados"])
    
    # Build context
    contexto_str = f"""
Dados já coletados: {contexto.dados_coletados}
Etapa atual: {contexto.etapa_atual}
Tentativas de coleta: {contexto.tentativas_coleta}
Histórico de mensagens: {contexto.mensagens_historico[-3:] if contexto.mensagens_historico else []}
"""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Contexto: {contexto_str}\n\nMensagem do usuário: {mensagem}")
    ]
    
    # Try providers in order with fallback
    for attempt in range(len(enhanced_config.providers)):
        provider, llm = enhanced_config.get_available_provider()
        
        if not provider or not llm:
            logger.error("No available providers for LLM processing")
            break
        
        try:
            logger.info(f"Attempting LLM processing with {provider.name} (attempt {attempt + 1})")
            response = llm.invoke(messages)
            
            # Record success
            provider.record_request()
            logger.info(f"LLM processing successful with {provider.name}")
            
            return response.content
            
        except Exception as e:
            error_msg = str(e)
            
            # Log the specific error
            logger.warning(f"LLM processing failed with {provider.name}: {error_msg[:200]}...")
            
            # Record failure with error context
            provider.record_failure(error_msg)
            
            # Check if this was the last provider
            if attempt == len(enhanced_config.providers) - 1:
                logger.error(f"All LLM providers failed. Last error: {error_msg}")
            else:
                logger.info(f"Trying next provider in fallback chain...")
    
    # All providers failed - return fallback response
    logger.error("All LLM providers failed, returning fallback response")
    return "Desculpe, estou com dificuldades técnicas no momento. Pode tentar novamente em alguns instantes?"


# Legacy function for backward compatibility
@traceable
def processar_mensagem_llm(
    mensagem: str, 
    contexto: EstadoConversa, 
    tipo_prompt: str
) -> str:
    """Legacy function - redirects to fallback system"""
    logger.warning("Using deprecated processar_mensagem_llm, consider using processar_mensagem_llm_with_fallback")
    return processar_mensagem_llm_with_fallback(mensagem, contexto, tipo_prompt)


@traceable
def extrair_dados_mensagem_with_fallback(mensagem: str, etapa: str) -> DadosExtraidos:
    """Extract data from message using fallback system"""
    enhanced_config = EnhancedLLMConfig()
    
    prompt_extracao = f"""
{SYSTEM_PROMPTS["extracao_dados"]}

Contexto da etapa atual: {etapa}
Mensagem do usuário: "{mensagem}"

Resposta (JSON apenas):"""
    
    # Try providers in fallback order
    for attempt in range(len(enhanced_config.providers)):
        provider, llm = enhanced_config.get_available_provider()
        
        if not provider or not llm:
            logger.error("No available providers for data extraction")
            break
            
        try:
            logger.info(f"Attempting data extraction with {provider.name}")
            response = llm.invoke([HumanMessage(content=prompt_extracao)])
            
            # Try to parse JSON response
            dados_extraidos = _parse_llm_json_response(response.content, mensagem)
            
            # Record success
            provider.record_request()
            logger.info(f"Data extraction successful with {provider.name}")
            
            return dados_extraidos
            
        except Exception as e:
            error_msg = str(e)
            # Check for quota/rate limit errors and fail fast
            is_quota_error = any(indicator in error_msg.lower() for indicator in [
                '429', 'quota', 'rate limit', 'exceeded', 'resourceexhausted', 'billing'
            ])
            
            if is_quota_error:
                logger.error(f"QUOTA ERROR on {provider.name}: {error_msg[:100]}...")
                logger.error(f"Switching to next provider immediately")
            else:
                logger.warning(f"Data extraction failed with {provider.name}: {error_msg[:150]}...")
            provider.record_failure(error_msg)
            
            if attempt == len(enhanced_config.providers) - 1:
                logger.error("All providers failed for data extraction")
    
    # All providers failed - return empty result
    logger.warning("All LLM providers failed for data extraction, using fallback extraction")
    return _extrair_dados_fallback("", mensagem)


# Legacy function for backward compatibility
@traceable
def extrair_dados_mensagem(mensagem: str, etapa: str) -> DadosExtraidos:
    """Legacy function - redirects to fallback system"""
    logger.warning("Using deprecated extrair_dados_mensagem, consider using extrair_dados_mensagem_with_fallback")
    return extrair_dados_mensagem_with_fallback(mensagem, etapa)


@traceable
def gerar_resposta_contextual(
    dados_coletados: dict[str, Any], 
    etapa: str, 
    mensagem_usuario: str
) -> str:
    """Gera resposta contextual baseada no estado da conversa"""
    # Use enhanced config with fallback
    enhanced_config = EnhancedLLMConfig()
        
    # Determine next information to collect
    proxima_info = determinar_proxima_informacao(dados_coletados)
        
    prompt_contextual = f"""
{SYSTEM_PROMPTS["coleta_dados"]}

SITUAÇÃO ATUAL:
- Dados já coletados: {dados_coletados}
- Etapa atual: {etapa}
- Última mensagem do usuário: "{mensagem_usuario}"
- Próxima informação a coletar: {proxima_info}

Gere uma resposta que:
1. Reconheça as informações fornecidas pelo usuário
2. Pergunte pela próxima informação necessária de forma natural
3. Seja amigável mas profissional
4. Não use emojis

Resposta:"""
    
    # Try providers in fallback order
    for attempt in range(len(enhanced_config.providers)):
        provider, llm = enhanced_config.get_available_provider()
        
        if not provider or not llm:
            logger.error("No available providers for contextual response")
            break
            
        try:
            logger.info(f"Generating response with {provider.name}")
            response = llm.invoke([HumanMessage(content=prompt_contextual)])
            
            provider.record_request()
            logger.info(f"Response generated successfully with {provider.name}")
            return response.content
            
        except Exception as e:
            error_msg = str(e)
            # Check for quota/rate limit errors and fail fast
            is_quota_error = any(indicator in error_msg.lower() for indicator in [
                '429', 'quota', 'rate limit', 'exceeded', 'resourceexhausted', 'billing'
            ])
            
            if is_quota_error:
                logger.error(f"QUOTA ERROR on {provider.name}: {error_msg[:100]}...")
                logger.error(f"Switching to next provider immediately")
            else:
                logger.warning(f"Response generation failed with {provider.name}: {error_msg[:100]}...")
            provider.record_failure(error_msg)
    
    # All providers failed - return hardcoded response
    logger.warning("All providers failed, using hardcoded response")
    return _generate_hardcoded_response(dados_coletados, proxima_info)


def _generate_hardcoded_response(dados_coletados: dict[str, Any], proxima_info: str) -> str:
    """Generate hardcoded response when all LLM providers fail"""
    
    # Acknowledge what we have
    acknowledgment = ""
    if dados_coletados.get("nome"):
        acknowledgment += f"Obrigada, {dados_coletados['nome']}! "
    elif any(dados_coletados.values()):
        acknowledgment += "Obrigada pelas informações! "
    else:
        acknowledgment += "Olá! "
    
    # Ask for next info
    if proxima_info == "nome do artista ou banda":
        return acknowledgment + "Para começar, qual é o seu nome ou nome da sua banda?"
    elif proxima_info == "cidade onde atua":
        return acknowledgment + "Agora, me conte em que cidade você atua como artista."
    elif proxima_info == "estilo musical principal":
        return acknowledgment + "Qual é o seu estilo musical principal?"
    elif proxima_info == "links de redes sociais":
        return acknowledgment + "Você pode compartilhar seus links do Instagram, YouTube ou Spotify?"
    elif proxima_info == "breve biografia":
        return acknowledgment + "Conte-me um pouco sobre você e sua trajetória musical."
    elif proxima_info == "anos de experiência musical":
        return acknowledgment + "Há quantos anos você trabalha com música?"
    else:
        return acknowledgment + "Qual seria a próxima informação que você gostaria de compartilhar?"


def determinar_proxima_informacao(dados_coletados: dict[str, Any]) -> str:
    """Determina qual informação coletar em seguida"""
    if not dados_coletados.get("nome"):
        return "nome do artista ou banda"
    elif not dados_coletados.get("cidade"):
        return "cidade onde atua"
    elif not dados_coletados.get("estilo_musical"):
        return "estilo musical principal"
    elif not any(dados_coletados.get(link) for link in ["instagram", "youtube", "spotify"]):
        return "links de redes sociais"
    elif not dados_coletados.get("biografia"):
        return "breve biografia"
    elif not dados_coletados.get("experiencia_anos"):
        return "anos de experiência musical"
    else:
        return "confirmação dos dados"


def _parse_llm_json_response(resposta_llm: str, mensagem_original: str) -> DadosExtraidos:
    """Parse JSON response from LLM with fallback extraction"""
    try:
        # Clean LLM response removing markdown wrappers
        resposta_limpa = resposta_llm.strip()
        
        # Remove markdown JSON wrappers if they exist
        if resposta_limpa.startswith('```json'):
            resposta_limpa = resposta_limpa[7:]  # Remove ```json
        if resposta_limpa.startswith('```'):
            resposta_limpa = resposta_limpa[3:]   # Remove ```
        if resposta_limpa.endswith('```'):
            resposta_limpa = resposta_limpa[:-3]  # Remove ``` at end
        
        resposta_limpa = resposta_limpa.strip()
        
        # Parse JSON
        dados_dict = json.loads(resposta_limpa)
        
        # Validate that we didn't capture "WIP" as name
        if dados_dict.get('nome', '').lower() in ['wip', 'bot', 'assistente']:
            dados_dict.pop('nome', None)
        
        dados_extraidos = DadosExtraidos(**dados_dict)
        
        # Calculate confidence based on number of extracted fields
        campos_preenchidos = sum(1 for v in dados_dict.values() if v is not None and v != "")
        dados_extraidos.confianca = min(campos_preenchidos / 3.0, 1.0)  # Normalize to 0-1
        
        logger.info(f"Data extracted with confidence {dados_extraidos.confianca:.2f}: {dados_dict}")
        return dados_extraidos
        
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"JSON parsing failed: {str(e)}. Response: {resposta_llm[:200]}...")
        # Fallback to manual extraction
        return _extrair_dados_fallback(resposta_llm, mensagem_original)


def _extrair_dados_fallback(resposta_llm: str, mensagem_original: str) -> DadosExtraidos:
    """Extração manual de dados como fallback quando JSON parsing falha"""
    try:
        import re
        
        dados = {}
        
        # Tentar extrair nome de forma mais inteligente
        # Evitar capturar "WIP", saludações comuns
        mensagem_lower = mensagem_original.lower()
        skip_words = ['wip', 'oi', 'olá', 'hello', 'bom dia', 'boa tarde', 'boa noite', 'tudo bem', 'bot']
        
        # Procurar padrões de apresentação
        nome_patterns = [
            r'(?:me chamo|meu nome é|sou o|sou a|eu sou)\s+([A-Za-z\s]+)',
            r'(?:banda|grupo)\s+([A-Za-z\s]+)',
            r'^([A-Za-z\s]+)\s+(?:aqui|falando)'
        ]
        
        for pattern in nome_patterns:
            match = re.search(pattern, mensagem_original, re.IGNORECASE)
            if match:
                nome_candidato = match.group(1).strip().title()
                if nome_candidato.lower() not in skip_words and len(nome_candidato) > 2:
                    dados['nome'] = nome_candidato
                    break
        
        # Extrair cidade
        cidade_pattern = r'(?:de|em|na|da cidade de|moro em)\s+([A-Za-z\s]+)'
        cidade_match = re.search(cidade_pattern, mensagem_original, re.IGNORECASE)
        if cidade_match:
            dados['cidade'] = cidade_match.group(1).strip().title()
        
        # Extrair estilo musical
        estilos = ['rock', 'pop', 'mpb', 'sertanejo', 'funk', 'rap', 'eletronica', 'jazz', 'blues', 'reggae']
        for estilo in estilos:
            if estilo in mensagem_lower:
                dados['estilo_musical'] = estilo
                break
        
        # Extrair links sociais
        instagram_pattern = r'(?:instagram|insta|ig)(?:\s*[:.]?\s*)([@\w./:-]+)'
        youtube_pattern = r'(?:youtube|yt)(?:\s*[:.]?\s*)([@\w./:-]+)'
        
        instagram_match = re.search(instagram_pattern, mensagem_original, re.IGNORECASE)
        if instagram_match:
            dados['instagram'] = instagram_match.group(1)
            
        youtube_match = re.search(youtube_pattern, mensagem_original, re.IGNORECASE)
        if youtube_match:
            dados['youtube'] = youtube_match.group(1)
        
        logger.info(f"Fallback extraction successful: {dados}")
        return DadosExtraidos(**dados)
        
    except Exception as e:
        logger.error(f"Fallback extraction failed: {str(e)}")
        return DadosExtraidos()


def validar_dados_completos(dados_coletados: dict[str, Any]) -> tuple[bool, list[str]]:
    """Valida se os dados obrigatórios foram coletados"""
    campos_obrigatorios = ["nome"]
    campos_recomendados = ["cidade", "estilo_musical"]
    
    campos_faltantes = []
    
    # Verificar campos obrigatórios
    for campo in campos_obrigatorios:
        if not dados_coletados.get(campo):
            campos_faltantes.append(campo)
    
    # Verificar se pelo menos um campo recomendado foi preenchido
    campos_recomendados_preenchidos = sum(
        1 for campo in campos_recomendados 
        if dados_coletados.get(campo)
    )
    
    dados_suficientes = len(campos_faltantes) == 0 and campos_recomendados_preenchidos > 0
    
    return dados_suficientes, campos_faltantes