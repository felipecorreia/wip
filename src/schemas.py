from pydantic import BaseModel, HttpUrl, Field, validator
from typing import Optional, Any
from uuid import UUID, uuid4
from enum import Enum
import re


class TipoContato(str, Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    TELEFONE = "telefone"


class EstiloMusical(str, Enum):
    ROCK = "rock"
    POP = "pop"
    MPB = "mpb"
    SERTANEJO = "sertanejo"
    FUNK = "funk"
    RAP = "rap"
    ELETRONICA = "eletronica"
    JAZZ = "jazz"
    BLUES = "blues"
    REGGAE = "reggae"
    OUTRO = "outro"


class Link(BaseModel):
    instagram: Optional[HttpUrl] = None
    youtube: Optional[HttpUrl] = None
    spotify: Optional[HttpUrl] = None
    soundcloud: Optional[HttpUrl] = None
    bandcamp: Optional[HttpUrl] = None
    outros: Optional[dict[str, HttpUrl]] = None


class Contato(BaseModel):
    tipo: TipoContato
    valor: str
    principal: bool = False
    
    @validator('valor')
    def validar_formato_contato(cls, v, values):
        tipo = values.get('tipo')
        if tipo == TipoContato.WHATSAPP:
            # Validar formato de telefone brasileiro
            pattern = r'^\+55\d{2}9?\d{8}$'
            if not re.match(pattern, v):
                raise ValueError('WhatsApp deve estar no formato +55DDNNNNNNNNN')
        elif tipo == TipoContato.EMAIL:
            # Validação básica de email
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, v):
                raise ValueError('Email inválido')
        return v


class Artista(BaseModel):
    id: Optional[UUID] = Field(default_factory=uuid4)
    nome: str = Field(..., min_length=2, max_length=100)
    cidade: Optional[str] = Field(None, max_length=50)
    estilo_musical: Optional[EstiloMusical] = None
    links: Optional[Link] = None
    contatos: list[Contato] = Field(default_factory=list)
    biografia: Optional[str] = Field(None, max_length=500)
    experiencia_anos: Optional[int] = Field(None, ge=0, le=50)
    
    class Config:
        use_enum_values = True


class EstadoConversa(BaseModel):
    artista_id: Optional[UUID] = None
    dados_coletados: dict[str, Any] = Field(default_factory=dict)
    etapa_atual: str = "inicio"
    tentativas_coleta: int = 0
    mensagens_historico: list[str] = Field(default_factory=list)
    precisa_langgraph: bool = False  # Flag para indicar se deve usar LangGraph


class MensagemWhatsApp(BaseModel):
    """Schema para mensagens recebidas do Twilio WhatsApp"""
    From: str
    To: str
    Body: str
    MessageSid: Optional[str] = None
    AccountSid: Optional[str] = None
    
    @validator('From')
    def validar_numero_origem(cls, v):
        # Remove prefixo whatsapp: se presente
        numero = v.replace("whatsapp:", "")
        if not numero.startswith("+"):
            raise ValueError("Número deve incluir código do país")
        return numero


class RespostaTwiML(BaseModel):
    """Schema para resposta TwiML"""
    mensagem: str
    
    def to_twiml(self) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{self.mensagem}</Message>
</Response>"""


class DadosExtraidos(BaseModel):
    """Schema para dados extraídos pelo LLM"""
    nome: Optional[str] = None
    cidade: Optional[str] = None
    estilo_musical: Optional[str] = None
    instagram: Optional[str] = None
    youtube: Optional[str] = None
    spotify: Optional[str] = None
    biografia: Optional[str] = None
    experiencia_anos: Optional[int] = None
    confianca: float = 0.0  # Nível de confiança na extração (0-1)
    
    @validator('experiencia_anos')
    def validar_experiencia(cls, v):
        if v is not None and (v < 0 or v > 50):
            raise ValueError("Experiência deve estar entre 0 e 50 anos")
        return v
    


class DadosExtraidos(BaseModel):
    """Schema para os dados estruturados extraídos pelo LLM a partir da mensagem do usuário."""
    nome: Optional[str] = Field(None, description="Nome da banda ou do artista solo.")
    cidade: Optional[str] = Field(None, description="Cidade de origem da banda ou artista.")
    estilo_musical: Optional[str] = Field(None, description="Gênero ou estilo musical principal.")
    instagram: Optional[str] = Field(None, description="Link completo ou @username do perfil do Instagram.")
    youtube: Optional[str] = Field(None, description="Link completo do canal ou de um vídeo no YouTube.")
    spotify: Optional[str] = Field(None, description="Link completo do perfil do artista no Spotify.")

    # Validador para normalizar o @username do instagram para uma URL completa
    @validator('instagram')
    def formatar_instagram_url(cls, v):
        if v and not v.startswith('http' ):
            username = v.replace('@', '').strip()
            return f"https://instagram.com/{username}"
        return v
