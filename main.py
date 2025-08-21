import os
import logging
import time
import asyncio
from typing import Any, List, Optional
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks, Form
from fastapi.responses import Response 
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import html

# Carregar variáveis de ambiente
load_dotenv()

# Imports locais
from src.schemas import EstadoConversa, MensagemWhatsApp, RespostaTwiML
from src.database import SupabaseManager
from src.flow import processar_mensagem, processar_mensagem_sync, AgentState
from src.conversation_utils import reiniciar_conversa, obter_progresso_conversa
from src.utils import obter_twilio_manager, limpar_telefone
from src.observability import (
    inicializar_observabilidade, 
    metricas_bot, 
    ObservabilityMiddleware,
    monitorar_performance
)
from src.queue_manager import message_queue
from src.llm_config import EnhancedLLMConfig
from src.llm_analyzer import analisar_mensagem_llm, AnaliseIntent

# Configurar logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _parse_and_validate_request(form_data: dict) -> tuple[str, str]:
    """Extrai e valida os dados do webhook do Twilio."""
    telefone = form_data.get("From", "")
    mensagem = form_data.get("Body", "").strip()
    
    if not telefone or not mensagem:
        raise ValueError("Telefone ou mensagem ausentes no payload do webhook.")
    
    telefone_limpo = limpar_telefone(telefone)
    logger.info(f"Webhook recebido - {telefone_limpo}: {mensagem[:50]}...")
    return telefone_limpo, mensagem

async def _get_bot_response(telefone: str, mensagem: str, estado: EstadoConversa) -> str:
    """Processa a mensagem e retorna a resposta do bot, tratando comandos especiais."""
    if mensagem.lower() in ["/reiniciar", "/restart", "reiniciar"]:
        # A função reiniciar_conversa já salva o estado, então não precisamos fazer de novo.
        reiniciar_conversa(telefone, SupabaseManager()) 
        return "Conversa reiniciada! Vamos começar do zero. Me conte sobre você ou sua banda!"
    
    if mensagem.lower() in ["/status", "status"]:
        progresso = obter_progresso_conversa(estado)
        return (
            f" Status do seu cadastro:\n"
            f"• Progresso: {progresso['progresso_percentual']}%\n"
            f"• Etapa: {progresso['etapa_atual']}\n"
            f"• Tentativas: {progresso['tentativas']}"
        )
    
    # Processamento principal com LangGraph
    try:
        timeout = float(os.getenv("WEBHOOK_TIMEOUT", "11.0"))
        return await asyncio.wait_for(
            processar_mensagem(telefone, mensagem, estado),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"Timeout no processamento para {telefone}")
        return "Opa, muitas mensagens chegando por aqui hoje. Me perdi um pouco, pode repetir sua mensagem?"
    except Exception as e:
        logger.error(f"Erro no processamento da mensagem para {telefone}: {e}", exc_info=True)
        return "Tive um probleminha por aqui. Pode tentar novamente?"

def _save_conversation_history(supabase: SupabaseManager, estado: EstadoConversa, mensagem_usuario: str, resposta_bot: str):
    """Salva o histórico da conversa no banco de dados."""
    if not estado.artista_id:
        return # Não faz nada se não houver um artista associado

    try:
        # Salva a mensagem do usuário
        supabase.salvar_conversa(
            artista_id=str(estado.artista_id),
            mensagem=mensagem_usuario,
            direcao="usuario"
        )
        # Salva a resposta do bot
        supabase.salvar_conversa(
            artista_id=str(estado.artista_id),
            mensagem=resposta_bot,
            direcao="bot"
        )
    except Exception as e:
        logger.warning(f"Erro ao salvar histórico da conversa para o artista {estado.artista_id}: {e}", exc_info=True)




@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicação"""
    # Startup
    logger.info("Iniciando WIP Artista Bot...")
    
    # Inicializar observabilidade
    observabilidade_ok = inicializar_observabilidade()
    if observabilidade_ok:
        logger.info("Observabilidade configurada")
    else:
        logger.warning("Observabilidade não pôde ser configurada")
    
    # Testar conexão com Supabase
    try:
        supabase = SupabaseManager()
        logger.info("Conexão com Supabase estabelecida")
    except Exception as e:
        logger.error(f"Erro ao conectar com Supabase: {str(e)}")
    
    # Start background message queue processor
    await message_queue.start_processing()
    logger.info("Sistema de processamento assíncrono iniciado")
    
    yield
    
    # Shutdown
    logger.info("Encerrando WIP Artista Bot...")
    await message_queue.stop_processing()
    logger.info("Sistema de processamento assíncrono finalizado")


# Criar aplicação FastAPI
app = FastAPI(
    title="WIP Artista Bot",
    description="Sistema de cadastro de artistas via WhatsApp com LLM e LangGraph",
    version="2.0.0",  # Atualizado para versão 2.0 com flow unificado
    lifespan=lifespan
)

# Adicionar middleware de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configurar adequadamente em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Adicionar middleware de observabilidade
app.add_middleware(ObservabilityMiddleware)

# Estado em memória para conversas 
estados_conversa: dict[str, EstadoConversa] = {}


def obter_supabase() -> SupabaseManager:
    """Dependency para obter instância do Supabase"""
    return SupabaseManager()


def obter_estado_conversa(telefone: str, supabase: SupabaseManager) -> EstadoConversa:
    """Obtém ou cria estado da conversa"""
    telefone_limpo = limpar_telefone(telefone)
    
    # Tentar carregar do cache em memória
    if telefone_limpo in estados_conversa:
        return estados_conversa[telefone_limpo]
    
    # Tentar carregar do banco de dados
    estado_persistido = supabase.carregar_estado_conversa(telefone_limpo)
    if estado_persistido:
        estados_conversa[telefone_limpo] = estado_persistido
        return estado_persistido
    
    # Criar novo estado
    novo_estado = EstadoConversa()
    estados_conversa[telefone_limpo] = novo_estado
    return novo_estado


def salvar_estado_conversa(telefone: str, estado: EstadoConversa, supabase: SupabaseManager):
    """Salva estado da conversa"""
    telefone_limpo = limpar_telefone(telefone)
    estados_conversa[telefone_limpo] = estado
    
    # Salvar no banco em background
    try:
        supabase.salvar_estado_conversa(telefone_limpo, estado)
    except Exception as e:
        logger.warning(f"Erro ao persistir estado da conversa: {str(e)}")


@app.post("/webhook/whatsapp")
async def webhook_whatsapp(
    request: Request,
    supabase: SupabaseManager = Depends(obter_supabase)
    ):
    """Webhook principal do WhatsApp, agora refatorado para clareza."""
    start_time = time.time()
    telefone, mensagem = "", ""
    
    try:
        form_data = await request.form()
        telefone, mensagem = _parse_and_validate_request(dict(form_data))
        
        estado = obter_estado_conversa(telefone, supabase)
        resposta = await _get_bot_response(telefone, mensagem, estado)
        
        # Salva o estado e o histórico (aqui usamos a nova função corrigida)
        salvar_estado_conversa(telefone, estado, supabase)
        _save_conversation_history(supabase, estado, mensagem, resposta)
        
        # Gera a resposta TwiML
        response_xml = f"""<?xml version="1.0" encoding="UTF-8"?><Response><Message>{html.escape(resposta)}</Message></Response>"""
        
        # Registra métricas de sucesso
        metricas_bot.registrar_interacao(
            telefone=telefone,
            etapa=estado.etapa_atual,
            sucesso=True,
            dados_coletados=estado.dados_coletados,
            tempo_resposta=(time.time() - start_time)
        )
        
        return Response(content=response_xml, media_type="application/xml")

    except ValueError as e: # Erro de validação dos dados de entrada
        logger.warning(f"Erro de validação no webhook: {e}")
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        
    except Exception as e: # Erro geral não esperado
        tempo_resposta = time.time() - start_time
        logger.error(f"Erro fatal no webhook para o telefone '{telefone}': {e} em {tempo_resposta:.3f}s", exc_info=True)
        
        metricas_bot.registrar_erro_sistema(
            tipo_erro="webhook_fatal_error",
            mensagem_erro=str(e),
            contexto={"telefone": telefone}
        )
        
        error_xml = """<?xml version="1.0" encoding="UTF-8"?><Response><Message>Desculpe, ocorreu um problema técnico. Tente novamente em alguns instantes.</Message></Response>"""
        return Response(content=error_xml, media_type="application/xml")


@app.get("/health")
async def health_check():
    """Endpoint de verificação de saúde da aplicação"""
    try:
        # Testar conexão com Supabase
        supabase = SupabaseManager()
        
        # Testar observabilidade
        observabilidade_status = "ok" if metricas_bot.client else "warning"
        
        return {
            "status": "healthy",
            "service": "wip-artista-bot",
            "version": "2.0.0",
            "flow": "unified_langgraph",
            "database": "connected",
            "observability": observabilidade_status,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "error": str(e)}
        )


@app.get("/metrics")
async def get_metrics():
    """Endpoint para obter métricas do sistema"""
    try:
        # Relatório diário
        relatorio = metricas_bot.gerar_relatorio_diario()
        
        # Adicionar métricas do sistema
        relatorio["sistema"] = {
            "conversas_ativas": len(estados_conversa),
            "observabilidade_ativa": metricas_bot.client is not None,
            "flow_version": "2.0_unified_langgraph"
        }
        
        # Adicionar métricas da queue
        relatorio["queue"] = message_queue.get_stats()
        
        return relatorio
    except Exception as e:
        logger.error(f"Erro ao obter métricas: {str(e)}")
        return {"erro": str(e)}


@app.get("/conversas/{telefone}/status")
async def status_conversa(
    telefone: str,
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """Obtém status de uma conversa específica"""
    try:
        estado = obter_estado_conversa(telefone, supabase)
        progresso = obter_progresso_conversa(estado)
        
        return {
            "telefone": telefone,
            "estado": estado.dict(),
            "progresso": progresso
        }
    except Exception as e:
        logger.error(f"Erro ao obter status da conversa: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/conversas/{telefone}/reiniciar")
async def reiniciar_conversa_endpoint(
    telefone: str,
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """Reinicia uma conversa específica"""
    try:
        telefone_limpo = limpar_telefone(telefone)
        estado = reiniciar_conversa(telefone_limpo, supabase)
        return {
            "telefone": telefone,
            "status": "reiniciada",
            "novo_estado": estado.dict()
        }
    except Exception as e:
        logger.error(f"Erro ao reiniciar conversa: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/artistas")
async def listar_artistas(
    tenant_id: str = None,
    limite: int = 50,
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """Lista artistas cadastrados"""
    try:
        if tenant_id:
            artistas = supabase.listar_artistas_por_tenant(tenant_id, limite)
        else:
            # Em produção, implementar paginação adequada
            artistas = []
        
        return {
            "artistas": [artista.dict() for artista in artistas],
            "total": len(artistas)
        }
    except Exception as e:
        logger.error(f"Erro ao listar artistas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue/status")
async def queue_status():
    """Get message queue status and statistics"""
    try:
        stats = message_queue.get_stats()
        return {
            "status": "healthy" if stats['is_running'] else "stopped",
            "queue_stats": stats,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Error getting queue status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/llm/status")
async def llm_status():
    """Get LLM providers status and availability"""
    try:
        enhanced_config = EnhancedLLMConfig()
        provider_stats = enhanced_config.get_provider_status()
        
        # Get currently available provider
        current_provider, _ = enhanced_config.get_available_provider()
        
        return {
            "current_provider": current_provider.name if current_provider else None,
            "providers": provider_stats,
            "fallback_available": any(p['available'] for p in provider_stats),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Error getting LLM status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint para testar análise LLM
@app.post("/test/analyze")
async def test_analyze_message(
    mensagem: str = Form(...),
    historico: Optional[str] = Form(None),
    artista_existente: bool = Form(False),
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """
    Endpoint para testar análise de intenção com LLM
    
    Exemplos de uso:
    curl -X POST http://localhost:8000/test/analyze \
        --data-urlencode "mensagem=Oi, sou João da banda Rock Total"
    """
    try:
        # Processar histórico se fornecido
        historico_list = None
        if historico:
            historico_list = historico.split("|")  # Separar por pipe
        
        # Buscar dados coletados se for usuário existente
        dados_coletados = None
        if artista_existente:
            # Simulação - em produção buscaríamos do banco
            dados_coletados = {}
        
        # Analisar mensagem
        analise = await analisar_mensagem_llm(
            mensagem=mensagem,
            historico=historico_list,
            dados_coletados=dados_coletados,
            artista_existente=artista_existente
        )
        
        # Retornar análise completa
        return {
            "mensagem_original": mensagem,
            "analise": {
                "intencao": analise.intencao.value,
                "intencao_secundaria": analise.intencao_secundaria.value if analise.intencao_secundaria else None,
                "entidades": analise.entidades.model_dump(exclude_unset=True),
                "contexto": analise.contexto.value,
                "sentimento": analise.sentimento.value,
                "urgencia": analise.urgencia.value,
                "confianca": analise.confianca,
                "palavras_chave": analise.palavras_chave,
                "precisa_acao_humana": analise.precisa_acao_humana,
                "resumo": analise.resumo
            },
            "debug": {
                "artista_existente": artista_existente,
                "historico_fornecido": bool(historico)
            }
        }
    except Exception as e:
        logger.error(f"Erro no teste de análise: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint para testes do novo flow unificado
@app.post("/test/message")
async def test_message(
    telefone: str = Form(...),
    mensagem: str = Form(...),
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """Endpoint para testar processamento de mensagens com o novo flow unificado"""
    try:
        telefone_limpo = limpar_telefone(telefone)
        estado = obter_estado_conversa(telefone_limpo, supabase)
        
        # Usar o novo flow unificado
        resposta = await processar_mensagem(telefone_limpo, mensagem, estado)
        
        salvar_estado_conversa(telefone_limpo, estado, supabase)
        
        return {
            "telefone": telefone,
            "mensagem_enviada": mensagem,
            "resposta_bot": resposta,
            "estado_atual": estado.model_dump(),
            "flow_version": "2.0_unified_langgraph"
        }
    except Exception as e:
        logger.error(f"Erro no teste de mensagem: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    # Configurações do servidor
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    
    logger.info(f"Iniciando servidor em {host}:{port}")
    logger.info("Usando flow unificado LangGraph v2.0")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=os.getenv("ENVIRONMENT") == "development",
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )