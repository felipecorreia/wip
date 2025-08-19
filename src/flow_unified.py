"""
Fluxo Unificado do WIP Bot
Todas as mensagens passam pelo LLM para análise inteligente
"""

import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from src.llm_analyzer import analisar_mensagem_llm, AnaliseIntent
from src.schemas import Artista, Contato, TipoContato, EstiloMusical, Link
from src.message_humanizer import humanizar_resposta
from uuid import uuid4

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EstadoConversa:
    """Gerencia o estado da conversa do usuário"""
    
    def __init__(self):
        self.historico: List[Dict[str, str]] = []
        self.dados_coletados: Dict[str, Any] = {}
        self.ultima_intencao: Optional[str] = None
        self.aguardando_resposta: Optional[str] = None
        self.artista_id: Optional[str] = None  # ID do artista quando cadastrado
        
    def adicionar_interacao(self, mensagem: str, resposta: str):
        """Adiciona interação ao histórico"""
        self.historico.append({
            "timestamp": datetime.now().isoformat(),
            "mensagem": mensagem,
            "resposta": resposta
        })
        # Manter apenas últimas 10 interações
        if len(self.historico) > 10:
            self.historico = self.historico[-10:]
            
    def get_historico_formatado(self) -> str:
        """Retorna histórico formatado para contexto"""
        if not self.historico:
            return "Primeira interação"
        
        ultimas = self.historico[-3:]  # Últimas 3 interações
        return "\n".join([
            f"User: {h['mensagem']}\nBot: {h['resposta']}"
            for h in ultimas
        ])

# Cache de estados por telefone
estados_usuarios: Dict[str, EstadoConversa] = {}

def get_estado_usuario(telefone: str) -> EstadoConversa:
    """Obtém ou cria estado do usuário"""
    if telefone not in estados_usuarios:
        estados_usuarios[telefone] = EstadoConversa()
    return estados_usuarios[telefone]

# =================== HANDLERS DE INTENÇÃO ===================

async def handle_cadastro_inicial(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase,
    telefone: str = None
) -> str:
    """Handler para cadastro inicial de artistas"""
    
    # Atualizar dados coletados com entidades extraídas
    if analise.entidades:
        # Converter entidades do modelo para o formato esperado
        entidades_dict = analise.entidades.model_dump(exclude_unset=True)
        if entidades_dict.get("nome"):
            estado.dados_coletados["nome_artistico"] = entidades_dict["nome"]
        if entidades_dict.get("estilo_musical"):
            estado.dados_coletados["estilo_musical"] = entidades_dict["estilo_musical"]
        if entidades_dict.get("cidade"):
            estado.dados_coletados["cidade"] = entidades_dict["cidade"]
        # Coletar links de diferentes fontes
        links_coletados = []
        if entidades_dict.get("instagram"):
            links_coletados.append(entidades_dict["instagram"])
        if entidades_dict.get("spotify"):
            links_coletados.append(entidades_dict["spotify"])
        if entidades_dict.get("youtube"):
            links_coletados.append(entidades_dict["youtube"])
        if links_coletados:
            estado.dados_coletados["links"] = links_coletados
    
    # Se já tem cadastro
    if artista:
        return (
            f"Olá! Vi que você já está na nossa base de artistas. "
            f"Do que você precisa? Quer ver a nossa agenda disponível ou "
            f"atualizar seus materiais?"
        )
    
    # Novo cadastro - verificar dados já coletados
    dados = estado.dados_coletados
    nome = dados.get("nome_artistico")
    estilo = dados.get("estilo_musical")
    cidade = dados.get("cidade")
    links = dados.get("links", [])
    
    # Resposta personalizada baseada nos dados
    if nome:
        resposta = f"Prazer, {nome}! Sou a WIP, responsável pela agenda de shows da Cervejaria Bragantina. "
        
        # Verificar o que falta
        faltando = []
        if not estilo:
            faltando.append("estilo musical")
        if not cidade:
            faltando.append("de onde vocês são")
        if not links:
            faltando.append("links do seu trabalho (Spotify, YouTube, Instagram)")
            
        if faltando:
            if len(faltando) == 1:
                resposta += f"Só preciso saber {faltando[0]} para completar seu cadastro."
            else:
                resposta += f"Para completar seu cadastro, preciso saber {', '.join(faltando[:-1])} e {faltando[-1]}."
            estado.aguardando_resposta = "dados_cadastro"
        else:
            # Todos os dados coletados - salvar no banco
            resposta += "Já tenho todas as informações que preciso! Vou salvar seu cadastro."
            
            # Criar objeto Artista
            artista_obj = await criar_artista_de_dados(dados, telefone)
            
            # Salvar no Supabase
            if supabase:
                resultado = supabase.salvar_artista(artista_obj)
                if resultado["success"]:
                    estado.artista_id = artista_obj.id
                    logger.info(f"Artista {nome} salvo com ID {artista_obj.id}")
                    resposta += " Perfeito! Agora você faz parte da nossa base de artistas. Quando tiver uma oportunidade vamos te chamar."
                else:
                    logger.error(f"Erro ao salvar artista: {resultado.get('error')}")
                    resposta += " Estou com um pequeno problema por aqui, mas já tenho suas informações, logo entro em contato."
            
            estado.aguardando_resposta = None
            estado.dados_coletados = {}  # Limpar dados após salvar
            
    else:
        # Sem nome ainda
        resposta = (
            "Olá! Sou a WIP da Cervejaria Bragantina, responsável pela nossa agenda de shows. "
            "Adoraria conhecer seu trabalho! Me conta aí o nome da sua banda/projeto e "
            "que tipo de som vocês fazem?"
        )
        estado.aguardando_resposta = "nome_e_estilo"
    
    return resposta

async def handle_cadastro_complemento(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase,
    telefone: str = None
) -> str:
    """Handler para complementar dados do cadastro"""
    
    # Atualizar dados com novas entidades
    if analise.entidades:
        # Converter entidades do modelo para o formato esperado
        entidades_dict = analise.entidades.model_dump(exclude_unset=True)
        if entidades_dict.get("nome"):
            estado.dados_coletados["nome_artistico"] = entidades_dict["nome"]
        if entidades_dict.get("estilo_musical"):
            estado.dados_coletados["estilo_musical"] = entidades_dict["estilo_musical"]
        if entidades_dict.get("cidade"):
            estado.dados_coletados["cidade"] = entidades_dict["cidade"]
        # Coletar links de diferentes fontes
        links_coletados = estado.dados_coletados.get("links", [])
        if entidades_dict.get("instagram"):
            links_coletados.append(entidades_dict["instagram"])
        if entidades_dict.get("spotify"):
            links_coletados.append(entidades_dict["spotify"])
        if entidades_dict.get("youtube"):
            links_coletados.append(entidades_dict["youtube"])
        if links_coletados:
            estado.dados_coletados["links"] = links_coletados
    
    dados = estado.dados_coletados
    nome = dados.get("nome_artistico")
    estilo = dados.get("estilo_musical")
    cidade = dados.get("cidade")
    links = dados.get("links", [])
    
    # Verificar o que ainda falta
    faltando = []
    if not nome:
        faltando.append("o nome do seu projeto")
    if not estilo:
        faltando.append("o estilo musical")
    if not cidade:
        faltando.append("de onde vocês são")
    if not links:
        faltando.append("links do seu trabalho")
    
    if faltando:
        if len(faltando) == 1:
            resposta = f"Ótimo! Agora só falta {faltando[0]}."
        else:
            resposta = f"Legal! Ainda preciso de {', '.join(faltando[:-1])} e {faltando[-1]}."
        estado.aguardando_resposta = "dados_cadastro"
    else:
        # Cadastro completo
        resposta = (
            f"Perfeito, {nome}!! "
            f"Agora vocês fazem parte da nossa base de artistas. "
            f"Vou analisar o material de vocês e em breve entro em contato "
            f"com possíveis datas. Enquanto isso, que tal dar uma olhada "
            f"na nossa agenda atual?"
        )
        
        # Criar e salvar artista
        artista_obj = await criar_artista_de_dados(dados, telefone)
        if supabase:
            resultado = supabase.salvar_artista(artista_obj)
            if resultado["success"]:
                estado.artista_id = artista_obj.id
                logger.info(f"Artista {nome} salvo com ID {artista_obj.id}")
            else:
                logger.error(f"Erro ao salvar artista: {resultado.get('error')}")
        
        estado.aguardando_resposta = None
        estado.dados_coletados = {}  # Limpar dados após salvar
    
    return resposta

async def handle_consulta_agenda(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para consulta de agenda"""
    
    if not artista:
        return (
            "Legal seu interesse em tocar aqui! Antes de ver as datas disponíveis, "
            "preciso das informações da sua banda. Me fala um pouco sobre sua banda - "
            "nome, estilo e de onde vocês são?"
        )
    
    # TODO: Buscar agenda real do Supabase
    # Por enquanto, retornar exemplo
    resposta = (
        f"Olá, {artista.get('nome', 'artista')}! Aqui estão as datas disponíveis:\n\n"
        f"• Sexta, 07/02 - 20h às 23h\n"
        f"• Sábado, 15/02 - 21h às 00h\n"
        f"• Sexta, 21/02 - 20h às 23h\n\n"
        f"Interesse em alguma data? Me avisa que já reservo para vocês!"
    )
    
    estado.aguardando_resposta = "confirmacao_data"
    return resposta

async def handle_info_casa(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para informações sobre a casa"""
    
    return (
        "A Cervejaria Bragantina é um espaço cultural em Bragança Paulista "
        "dedicado à música ao vivo e cerveja artesanal. Oferecemos:\n\n"
        "• Palco completo com som e iluminação profissional\n"
        "• Cachê justo\n"
        "• Divulgação nas nossas redes\n"
        "• Ambiente acolhedor para artistas e público\n\n"
        "Quer saber mais alguma coisa específica ou já quer ver a agenda?"
    )

async def handle_saudacao(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para saudações"""
    
    hora = datetime.now().hour
    periodo = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
    
    if artista:
        return (
            f"{periodo}, {artista.get('nome', 'artista')}! "
            f"Bom te ver por aqui! Como posso ajudar hoje?"
        )
    else:
        return (
            f"{periodo}! Sou a WIP da Cervejaria Bragantina. "
            f"Está interessado em tocar aqui? Adoraria conhecer seu trabalho!"
        )

async def handle_confirmar_show(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para confirmação de show"""
    
    if not artista:
        return (
            "Para confirmar uma data, primeiro preciso te cadastrar em nossa base de artistas. "
            "Me conta sobre sua banda?"
        )
    
    # TODO: Implementar lógica de confirmação real
    return (
        "Ótimo! Vou reservar essa data para vocês. "
        "Em breve envio todos os detalhes por aqui mesmo. "
        "Já podem ir divulgando! Vai ser demais!"
    )

async def handle_cancelamento(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para cancelamentos"""
    
    estado.dados_coletados = {}
    estado.aguardando_resposta = None
    
    return (
        "Sem problemas! Cancelei o processo. "
        "Se mudar de ideia, estou sempre aqui. "
        "Até mais!"
    )

async def handle_feedback(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para feedback"""
    
    if analise.sentimento == "positivo":
        return "Fico muito feliz em ajudar! Conte sempre comigo!"
    elif analise.sentimento == "negativo":
        return (
            "Poxa, sinto muito se algo não saiu como esperado. "
            "Seu feedback é importante para melhorarmos. "
            "Pode me contar mais sobre o que aconteceu?"
        )
    else:
        return "Obrigado pelo feedback! É sempre bom saber como estamos indo."

async def handle_duvida(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para dúvidas gerais"""
    
    return (
        "Boa pergunta! Posso ajudar com:\n"
        "• Cadastro de artistas\n"
        "• Consulta de agenda\n"
        "• Informações sobre a casa\n"
        "• Agendamento de shows\n\n"
        "O que você gostaria de saber?"
    )

async def handle_despedida(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para despedidas"""
    
    if artista:
        return f"Até mais, {artista.get('nome', '')}! Foi ótimo falar com você!"
    else:
        return "Até mais! Quando quiser tocar aqui, é só chamar!"

async def handle_atualizar_dados(
    analise: AnaliseIntent,
    estado: EstadoConversa,
    artista: Optional[Dict],
    supabase
) -> str:
    """Handler para atualização de dados"""
    
    if not artista:
        return (
            "Você ainda não está cadastrado. "
            "Quer fazer seu cadastro agora?"
        )
    
    return (
        "Claro! O que você gostaria de atualizar?\n"
        "• Nome artístico\n"
        "• Estilo musical\n"
        "• Cidade\n"
        "• Links\n"
        "• Informações de contato"
    )

# =================== FUNÇÕES AUXILIARES ===================

async def criar_artista_de_dados(dados: Dict[str, Any], telefone: str) -> Artista:
    """Cria objeto Artista a partir dos dados coletados"""
    
    # Limpar telefone
    telefone_limpo = telefone.replace("whatsapp:", "").replace(" ", "")
    if not telefone_limpo.startswith("+"):
        telefone_limpo = "+55" + telefone_limpo
    
    # Criar contatos
    contatos = [
        Contato(
            tipo=TipoContato.WHATSAPP,
            valor=telefone_limpo,
            principal=True
        )
    ]
    
    # Adicionar email se existir
    if dados.get("email"):
        contatos.append(
            Contato(
                tipo=TipoContato.EMAIL,
                valor=dados["email"],
                principal=False
            )
        )
    
    # Processar estilo musical
    estilo_str = dados.get("estilo_musical", "outro").lower()
    estilo_map = {
        "rock": EstiloMusical.ROCK,
        "pop": EstiloMusical.POP,
        "mpb": EstiloMusical.MPB,
        "sertanejo": EstiloMusical.SERTANEJO,
        "funk": EstiloMusical.FUNK,
        "rap": EstiloMusical.RAP,
        "eletronica": EstiloMusical.ELETRONICA,
        "jazz": EstiloMusical.JAZZ,
        "blues": EstiloMusical.BLUES,
        "reggae": EstiloMusical.REGGAE,
        "bossa nova": EstiloMusical.MPB,
        "rock nacional": EstiloMusical.ROCK,
        "jazz instrumental": EstiloMusical.JAZZ,
    }
    
    # Encontrar o estilo mais próximo
    estilo_enum = EstiloMusical.OUTRO
    for key, value in estilo_map.items():
        if key in estilo_str:
            estilo_enum = value
            break
    
    # Processar links
    links_obj = None
    if dados.get("links"):
        links_dict = {}
        for link in dados["links"]:
            if "instagram" in link.lower() or "@" in link:
                # Converter @usuario para URL completa
                if link.startswith("@"):
                    link = f"https://instagram.com/{link[1:]}"
                links_dict["instagram"] = link
            elif "spotify" in link.lower():
                if not link.startswith("http"):
                    link = f"https://{link}"
                links_dict["spotify"] = link
            elif "youtube" in link.lower():
                if not link.startswith("http"):
                    link = f"https://{link}"
                links_dict["youtube"] = link
        
        if links_dict:
            # Criar objeto Link com URLs válidas
            try:
                links_obj = Link(**links_dict)
            except:
                # Se falhar validação, guardar como string simples
                links_obj = None
                logger.warning(f"Links inválidos: {links_dict}")
    
    # Criar artista
    artista = Artista(
        id=uuid4(),
        nome=dados.get("nome_artistico", "Artista sem nome"),
        cidade=dados.get("cidade"),
        estilo_musical=estilo_enum,
        links=links_obj,
        contatos=contatos,
        biografia=dados.get("biografia"),
        experiencia_anos=dados.get("experiencia_anos")
    )
    
    return artista

# =================== FLUXO PRINCIPAL ===================

async def processar_mensagem_unificada(
    telefone: str,
    mensagem: str,
    supabase
) -> str:
    """
    Processa mensagem através do fluxo unificado com LLM
    
    Args:
        telefone: Número do WhatsApp
        mensagem: Mensagem recebida
        supabase: Cliente Supabase para consultas
        
    Returns:
        Resposta para o usuário
    """
    
    try:
        # 1. Obter estado do usuário
        estado = get_estado_usuario(telefone)
        
        # 2. Buscar dados do artista se existir
        artista = None
        try:
            # TODO: Implementar busca real no Supabase
            # artista = await supabase.buscar_artista(telefone)
            pass
        except Exception as e:
            logger.warning(f"Erro ao buscar artista: {e}")
        
        # 3. Analisar mensagem com LLM
        historico = estado.get_historico_formatado()
        analise = await analisar_mensagem_llm(
            mensagem=mensagem,
            historico=[historico] if historico != "Primeira interação" else None,
            dados_coletados=estado.dados_coletados,
            artista_existente=artista is not None
        )
        
        logger.info(f"Análise LLM: {analise.intencao} - Sentimento: {analise.sentimento}")
        
        # 4. Rotear para handler apropriado baseado na intenção
        handlers = {
            "cadastro_inicial": handle_cadastro_inicial,
            "cadastro_complemento": handle_cadastro_complemento,
            "consulta_agenda": handle_consulta_agenda,
            "info_casa": handle_info_casa,
            "saudacao": handle_saudacao,
            "confirmar_show": handle_confirmar_show,
            "cancelamento": handle_cancelamento,
            "feedback": handle_feedback,
            "duvida": handle_duvida,
            "despedida": handle_despedida,
            "atualizar_dados": handle_atualizar_dados,
        }
        
        # Selecionar handler ou usar padrão
        handler = handlers.get(analise.intencao.value, handle_duvida)
        
        # 5. Gerar resposta através do handler
        # Adicionar telefone se o handler precisar
        if handler in [handle_cadastro_inicial, handle_cadastro_complemento]:
            resposta = await handler(analise, estado, artista, supabase, telefone)
        else:
            resposta = await handler(analise, estado, artista, supabase)
        
        # 6. Atualizar estado e histórico
        estado.ultima_intencao = analise.intencao.value
        estado.adicionar_interacao(mensagem, resposta)
        
        # 7. Salvar conversa no banco se tiver artista_id
        if estado.artista_id and supabase:
            try:
                # Salvar mensagem do usuário
                supabase.salvar_conversa(
                    artista_id=str(estado.artista_id),
                    mensagem=mensagem,
                    direcao="entrada",
                    momento_chave=analise.intencao.value
                )
                
                # Salvar resposta do bot
                supabase.salvar_conversa(
                    artista_id=str(estado.artista_id),
                    mensagem=resposta,
                    direcao="saida",
                    momento_chave=analise.intencao.value
                )
            except Exception as e:
                logger.warning(f"Erro ao salvar conversa: {e}")
        
        # 8. Log para monitoramento
        logger.info(f"Telefone: {telefone} | Intent: {analise.intencao.value} | Urgência: {analise.urgencia}")
        
        # 9. Humanizar resposta (quebrar em mensagens menores)
        # Só ativa se variável de ambiente estiver setada
        use_humanizer = os.getenv("USE_HUMANIZED_RESPONSES", "false").lower() == "true"
        if use_humanizer:
            resposta_humanizada = humanizar_resposta(resposta, quebrar=True)
            logger.info(f"Resposta humanizada: {len(resposta_humanizada.split('\\n\\n'))} mensagens")
            return resposta_humanizada
        
        return resposta
        
    except Exception as e:
        logger.error(f"Erro no fluxo unificado: {e}")
        # Fallback para resposta segura
        return (
            "Desculpe, tive um problema ao processar sua mensagem. "
            "Pode tentar novamente? Se preferir, me diga se você quer:\n"
            "1. Se cadastrar para tocar aqui\n"
            "2. Ver a agenda disponível\n"
            "3. Informações sobre a casa"
        )

# =================== UTILIDADES ===================

def limpar_estado_usuario(telefone: str):
    """Limpa o estado de um usuário específico"""
    if telefone in estados_usuarios:
        del estados_usuarios[telefone]
        logger.info(f"Estado limpo para: {telefone}")

def get_estatisticas_estados() -> Dict[str, Any]:
    """Retorna estatísticas dos estados em memória"""
    return {
        "total_usuarios": len(estados_usuarios),
        "usuarios_com_dados": sum(
            1 for e in estados_usuarios.values() 
            if e.dados_coletados
        ),
        "usuarios_aguardando": sum(
            1 for e in estados_usuarios.values()
            if e.aguardando_resposta
        )
    }