import re
import logging
import os
import asyncio
from typing import Any, Optional, Union
from urllib.parse import urlparse
import validators
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
from .schemas import EstiloMusical

logger = logging.getLogger(__name__)


def normalizar_telefone(telefone: str) -> str:
    """Normaliza número de telefone para formato padrão"""
    # Remove prefixo whatsapp: se presente
    telefone_limpo = telefone.replace("whatsapp:", "")
    
    # Remove espaços e caracteres especiais
    telefone_limpo = re.sub(r'[^\d+]', '', telefone_limpo)
    
    # Garantir que tem código do país
    if not telefone_limpo.startswith("+"):
        if telefone_limpo.startswith("55"):
            telefone_limpo = "+" + telefone_limpo
        else:
            telefone_limpo = "+55" + telefone_limpo
    
    return telefone_limpo


def limpar_telefone(telefone: str) -> str:
    """Alias para normalizar_telefone - remove prefixo whatsapp e limpa o número"""
    return normalizar_telefone(telefone)


def validar_url(url: str) -> bool:
    """Valida se uma string é uma URL válida"""
    try:
        return validators.url(url) is True
    except:
        return False


def normalizar_url_social(url: str, plataforma: str) -> Optional[str]:
    """Normaliza URLs de redes sociais"""
    if not url:
        return None
    
    # Se já é uma URL válida, retorna
    if url.startswith("http") and validar_url(url):
        return url
    
    # Remover @ se presente
    handle = url.replace("@", "")
    
    # Normalizar baseado na plataforma
    if plataforma == "instagram":
        if "/" in handle:
            # Extrair handle da URL
            parts = handle.split("/")
            handle = next((p for p in parts if p and p != "instagram.com"), handle)
        return f"https://instagram.com/{handle}"
    
    elif plataforma == "youtube":
        if "youtube.com" in handle or "youtu.be" in handle:
            return handle if handle.startswith("http") else f"https://{handle}"
        return f"https://youtube.com/@{handle}"
    
    elif plataforma == "spotify":
        if "spotify.com" in handle:
            return handle if handle.startswith("http") else f"https://{handle}"
        return f"https://open.spotify.com/artist/{handle}"
    
    elif plataforma == "soundcloud":
        if "soundcloud.com" in handle:
            return handle if handle.startswith("http") else f"https://{handle}"
        return f"https://soundcloud.com/{handle}"
    
    elif plataforma == "bandcamp":
        if "bandcamp.com" in handle:
            return handle if handle.startswith("http") else f"https://{handle}"
        # Assumir que é um subdomínio
        if not "." in handle:
            return f"https://{handle}.bandcamp.com"
        return f"https://{handle}"
    
    return None


def identificar_estilo_musical(texto: str) -> Optional[EstiloMusical]:
    """Identifica estilo musical a partir de texto livre"""
    if not texto:
        return None
    
    texto_lower = texto.lower()
    
    # Mapeamento de variações para estilos
    mapeamentos = {
        EstiloMusical.ROCK: ["rock", "hard rock", "soft rock", "rock nacional", "rock alternativo"],
        EstiloMusical.POP: ["pop", "pop nacional", "pop rock", "música pop"],
        EstiloMusical.MPB: ["mpb", "musica popular brasileira", "música popular brasileira"],
        EstiloMusical.SERTANEJO: ["sertanejo", "sertanejo universitário", "country", "música sertaneja"],
        EstiloMusical.FUNK: ["funk", "funk carioca", "funk nacional", "funky"],
        EstiloMusical.RAP: ["rap", "hip hop", "hip-hop", "música rap"],
        EstiloMusical.ELETRONICA: ["eletrônica", "eletronica", "electronic", "house", "techno", "edm"],
        EstiloMusical.JAZZ: ["jazz", "música jazz", "smooth jazz"],
        EstiloMusical.BLUES: ["blues", "rhythm and blues", "r&b"],
        EstiloMusical.REGGAE: ["reggae", "música reggae", "ragga"]
    }
    
    # Procurar por correspondências
    for estilo, variacoes in mapeamentos.items():
        for variacao in variacoes:
            if variacao in texto_lower:
                return estilo
    
    # Se não encontrar correspondência, retorna OUTRO
    return EstiloMusical.OUTRO


def extrair_anos_experiencia(texto: str) -> Optional[int]:
    """Extrai anos de experiência de texto livre"""
    if not texto:
        return None
    
    # Padrões para encontrar números seguidos de "anos"
    patterns = [
        r'(\d+)\s*anos?',
        r'há\s*(\d+)\s*anos?',
        r'(\d+)\s*a\s*\d+\s*anos?',  # Para faixas, pega o primeiro número
        r'mais\s*de\s*(\d+)\s*anos?',
        r'cerca\s*de\s*(\d+)\s*anos?',
        r'aproximadamente\s*(\d+)\s*anos?'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, texto.lower())
        if match:
            anos = int(match.group(1))
            # Validar se é um número razoável
            if 0 <= anos <= 50:
                return anos
    
    return None


def limpar_texto(texto: str, max_length: int = None) -> str:
    """Limpa e normaliza texto"""
    if not texto:
        return ""
    
    # Remove espaços extras
    texto_limpo = " ".join(texto.split())
    
    # Remove caracteres especiais desnecessários
    texto_limpo = re.sub(r'[^\w\sáéíóúàèìòùâêîôûãõç.,!?()-]', '', texto_limpo, flags=re.IGNORECASE)
    
    # Trunca se necessário
    if max_length and len(texto_limpo) > max_length:
        texto_limpo = texto_limpo[:max_length].rsplit(' ', 1)[0] + "..."
    
    return texto_limpo.strip()


def extrair_handle_social(url_ou_handle: str) -> str:
    """Extrai handle de uma URL ou texto de rede social"""
    if not url_ou_handle:
        return ""
    
    # Se é uma URL, extrair o handle
    if url_ou_handle.startswith("http"):
        parsed = urlparse(url_ou_handle)
        path = parsed.path.strip("/")
        
        # Para Instagram: instagram.com/handle
        if "instagram.com" in parsed.netloc:
            return path.split("/")[0] if path else ""
        
        # Para YouTube: youtube.com/@handle ou youtube.com/channel/handle
        elif "youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc:
            if path.startswith("@"):
                return path
            elif "/" in path:
                return path.split("/")[-1]
        
        # Para outras plataformas
        elif "/" in path:
            return path.split("/")[-1]
        
        return path
    
    # Se não é URL, limpar @ se presente
    return url_ou_handle.replace("@", "")


def validar_dados_artista(dados: dict[str, Any]) -> dict[str, list[str]]:
    """Valida dados do artista e retorna erros encontrados"""
    erros = {}
    
    # Validar nome (obrigatório)
    if not dados.get("nome"):
        erros["nome"] = ["Nome é obrigatório"]
    elif len(dados["nome"]) < 2:
        erros["nome"] = ["Nome deve ter pelo menos 2 caracteres"]
    elif len(dados["nome"]) > 100:
        erros["nome"] = ["Nome deve ter no máximo 100 caracteres"]
    
    # Validar cidade
    if dados.get("cidade"):
        if len(dados["cidade"]) > 50:
            erros["cidade"] = ["Cidade deve ter no máximo 50 caracteres"]
    
    # Validar biografia
    if dados.get("biografia"):
        if len(dados["biografia"]) > 500:
            erros["biografia"] = ["Biografia deve ter no máximo 500 caracteres"]
    
    # Validar experiência
    if dados.get("experiencia_anos"):
        try:
            anos = int(dados["experiencia_anos"])
            if anos < 0 or anos > 50:
                erros["experiencia_anos"] = ["Experiência deve estar entre 0 e 50 anos"]
        except (ValueError, TypeError):
            erros["experiencia_anos"] = ["Experiência deve ser um número válido"]
    
    # Validar URLs de redes sociais
    for campo in ["instagram", "youtube", "spotify", "soundcloud", "bandcamp"]:
        url = dados.get(campo)
        if url and not validar_url(url):
            if campo not in erros:
                erros[campo] = []
            erros[campo].append(f"URL do {campo} inválida")
    
    return erros


def formatar_resposta_bot(mensagem: str, max_length: int = 1600) -> str:
    """Formata resposta do bot para WhatsApp"""
    # WhatsApp tem limite de caracteres
    if len(mensagem) > max_length:
        mensagem = mensagem[:max_length - 3] + "..."
    
    # Remove quebras de linha excessivas
    mensagem = re.sub(r'\n{3,}', '\n\n', mensagem)
    
    return mensagem.strip()


def calcular_completude_dados(dados: dict[str, Any]) -> dict[str, Any]:
    """Calcula completude dos dados coletados"""
    campos_obrigatorios = {"nome": 3}  # peso 3
    campos_importantes = {"cidade": 2, "estilo_musical": 2}  # peso 2
    campos_opcionais = {
        "biografia": 1, "experiencia_anos": 1,
        "instagram": 1, "youtube": 1, "spotify": 1
    }  # peso 1
    
    score = 0
    max_score = sum(campos_obrigatorios.values()) + sum(campos_importantes.values()) + sum(campos_opcionais.values())
    
    campos_preenchidos = []
    campos_faltantes = []
    
    # Verificar cada categoria
    for campo, peso in campos_obrigatorios.items():
        if dados.get(campo):
            score += peso
            campos_preenchidos.append(campo)
        else:
            campos_faltantes.append(campo)
    
    for campo, peso in campos_importantes.items():
        if dados.get(campo):
            score += peso
            campos_preenchidos.append(campo)
    
    for campo, peso in campos_opcionais.items():
        if dados.get(campo):
            score += peso
            campos_preenchidos.append(campo)
    
    percentual = (score / max_score) * 100
    
    # Classificar qualidade
    if percentual >= 80:
        qualidade = "excelente"
    elif percentual >= 60:
        qualidade = "boa"
    elif percentual >= 40:
        qualidade = "regular"
    else:
        qualidade = "baixa"
    
    return {
        "percentual_completude": round(percentual, 1),
        "score": score,
        "max_score": max_score,
        "qualidade": qualidade,
        "campos_preenchidos": campos_preenchidos,
        "campos_faltantes": campos_faltantes,
        "total_campos": len(campos_preenchidos)
    }


def gerar_resumo_artista(dados: dict[str, Any]) -> str:
    """Gera resumo textual dos dados do artista"""
    nome = dados.get("nome", "Artista")
    resumo_parts = [f"Nome: {nome}"]
    
    if dados.get("cidade"):
        resumo_parts.append(f"Cidade: {dados['cidade']}")
    
    if dados.get("estilo_musical"):
        resumo_parts.append(f"Estilo: {dados['estilo_musical']}")
    
    if dados.get("experiencia_anos"):
        resumo_parts.append(f"Experiência: {dados['experiencia_anos']} anos")
    
    # Contar redes sociais
    redes_sociais = []
    for rede in ["instagram", "youtube", "spotify", "soundcloud", "bandcamp"]:
        if dados.get(rede):
            redes_sociais.append(rede.capitalize())
    
    if redes_sociais:
        resumo_parts.append(f"Redes: {', '.join(redes_sociais)}")
    
    if dados.get("biografia"):
        bio_resumida = dados["biografia"][:100]
        if len(dados["biografia"]) > 100:
            bio_resumida += "..."
        resumo_parts.append(f"Bio: {bio_resumida}")
    
    return " | ".join(resumo_parts)


def detectar_intencao_mensagem(mensagem: str) -> str:
    """Detecta intenção da mensagem do usuário"""
    mensagem_lower = mensagem.lower().strip()
    
    # Comandos explícitos
    if mensagem_lower in ["oi", "olá", "ola", "hello", "hi"]:
        return "saudacao"
    
    if any(cmd in mensagem_lower for cmd in ["/ajuda", "ajuda", "help", "/help"]):
        return "ajuda"
    
    if any(cmd in mensagem_lower for cmd in ["/reiniciar", "/restart", "reiniciar"]):
        return "reiniciar"
    
    if any(cmd in mensagem_lower for cmd in ["/status", "status"]):
        return "status"
    
    # Negativas
    if any(neg in mensagem_lower for neg in ["não", "nao", "não tenho", "nao tenho", "não sei"]):
        return "negativa"
    
    # Confirmações
    if any(conf in mensagem_lower for conf in ["sim", "ok", "okay", "certo", "correto", "confirmo"]):
        return "confirmacao"
    
    # URLs ou handles sociais
    if any(plat in mensagem_lower for plat in ["instagram.com", "@", "youtube.com", "spotify.com"]):
        return "rede_social"
    
    # Números (experiência)
    if re.search(r'\d+\s*anos?', mensagem_lower):
        return "experiencia"
    
    # Default: informação geral
    return "informacao"


# Twilio Utilities for Background Message Sending
class TwilioManager:
    """Gerenciador para envio de mensagens WhatsApp via Twilio"""
    
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.whatsapp_from = os.getenv("TWILIO_WHATSAPP_FROM")
        
        if not all([self.account_sid, self.auth_token, self.whatsapp_from]):
            raise ValueError("Credenciais do Twilio não configuradas corretamente")
        
        self.client = Client(self.account_sid, self.auth_token)
        logger.info("Cliente Twilio inicializado")
    
    async def enviar_mensagem_whatsapp(
        self, 
        telefone: str, 
        mensagem: str, 
        max_retries: int = 3
    ) -> dict[str, Any]:
        """Envia mensagem WhatsApp com retry automático"""
        telefone_normalizado = normalizar_telefone(telefone)
        if not telefone_normalizado.startswith("whatsapp:"):
            telefone_normalizado = f"whatsapp:{telefone_normalizado}"
        
        # Formatar mensagem para WhatsApp
        mensagem_formatada = formatar_resposta_bot(mensagem)
        
        for tentativa in range(max_retries):
            try:
                logger.info(f"Enviando mensagem para {telefone_normalizado} (tentativa {tentativa + 1})")
                
                message = self.client.messages.create(
                    body=mensagem_formatada,
                    from_=self.whatsapp_from,
                    to=telefone_normalizado
                )
                
                logger.info(f"Mensagem enviada com sucesso - SID: {message.sid}")
                return {
                    "success": True,
                    "message_sid": message.sid,
                    "telefone": telefone_normalizado,
                    "tentativas": tentativa + 1
                }
                
            except TwilioException as e:
                logger.error(f"Erro do Twilio (tentativa {tentativa + 1}): {e}")
                if tentativa == max_retries - 1:
                    return {
                        "success": False,
                        "error": str(e),
                        "telefone": telefone_normalizado,
                        "tentativas": tentativa + 1
                    }
                
                # Esperar antes de tentar novamente (exponential backoff)
                await asyncio.sleep(2 ** tentativa)
                
            except Exception as e:
                logger.error(f"Erro inesperado ao enviar mensagem: {e}")
                if tentativa == max_retries - 1:
                    return {
                        "success": False,
                        "error": str(e),
                        "telefone": telefone_normalizado,
                        "tentativas": tentativa + 1
                    }
                
                await asyncio.sleep(2 ** tentativa)
        
        return {
            "success": False,
            "error": "Máximo de tentativas excedido",
            "telefone": telefone_normalizado,
            "tentativas": max_retries
        }
    
    def validar_numero_whatsapp(self, telefone: str) -> bool:
        """Valida se o número pode receber mensagens WhatsApp"""
        try:
            telefone_normalizado = normalizar_telefone(telefone)
            # Implementar validação se necessário
            return len(telefone_normalizado) >= 10
        except Exception:
            return False


# Singleton instance
_twilio_manager: Optional[TwilioManager] = None


def obter_twilio_manager() -> TwilioManager:
    """Obtém instância singleton do TwilioManager"""
    global _twilio_manager
    if _twilio_manager is None:
        _twilio_manager = TwilioManager()
    return _twilio_manager