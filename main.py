import os
import logging
import time
import asyncio
from typing import Any
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks, Form
from fastapi.responses import Response 
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Imports locais
from src.schemas import EstadoConversa, MensagemWhatsApp, RespostaTwiML
from src.database import SupabaseManager
from src.flow import processar_fluxo_artista
from src.conversation_utils import reiniciar_conversa, obter_progresso_conversa
from src.flow_direct import processar_mensagem_otimizado
from src.utils import obter_twilio_manager
from src.observability import (
    inicializar_observabilidade, 
    metricas_bot, 
    ObservabilityMiddleware,
    monitorar_performance
)
from src.queue_manager import message_queue
from src.llm_config import EnhancedLLMConfig

# Configurar logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
    version="1.0.0",
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
    telefone_limpo = telefone.replace("whatsapp:", "")
    
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
    telefone_limpo = telefone.replace("whatsapp:", "")
    estados_conversa[telefone_limpo] = estado
    
    # Salvar no banco em background
    try:
        supabase.salvar_estado_conversa(telefone_limpo, estado)
    except Exception as e:
        logger.warning(f"Erro ao persistir estado da conversa: {str(e)}")


# Legacy function - now handled by queue_manager
# Keeping for backward compatibility during transition
async def processar_mensagem_background(
    telefone: str,
    mensagem: str,
    supabase: SupabaseManager
):
    """Processa mensagem em background e envia resposta via Twilio API"""
    start_time = time.time()
    
    try:
        logger.info(f"Iniciando processamento em background para {telefone}: {mensagem[:100]}")
        
        # Obter estado da conversa
        estado = obter_estado_conversa(telefone, supabase)
        
        # Comandos especiais
        if mensagem.lower() in ["/reiniciar", "/restart", "reiniciar"]:
            estado = reiniciar_conversa(telefone, supabase)
            resposta = "Conversa reiniciada! Vamos começar seu cadastro do zero. Qual é o seu nome ou nome da sua banda?"
        elif mensagem.lower() in ["/status", "status"]:
            progresso = obter_progresso_conversa(estado)
            resposta = f"Status do seu cadastro:\n- Progresso: {progresso['progresso_percentual']}%\n- Etapa atual: {progresso['etapa_atual']}\n- Tentativas: {progresso['tentativas']}"
        else:
            # Processar mensagem através do fluxo otimizado
            resposta = await processar_mensagem_otimizado(telefone, mensagem, estado, supabase)
        
        # Salvar estado atualizado
        salvar_estado_conversa(telefone, estado, supabase)
        
        # Enviar resposta via Twilio API
        twilio_manager = obter_twilio_manager()
        resultado_envio = await twilio_manager.enviar_mensagem_whatsapp(telefone, resposta)
        
        if resultado_envio["success"]:
            logger.info(f"Resposta enviada com sucesso para {telefone} - SID: {resultado_envio['message_sid']}")
        else:
            logger.error(f"Falha ao enviar resposta para {telefone}: {resultado_envio['error']}")
            
            # Registrar erro de envio
            metricas_bot.registrar_erro_sistema(
                tipo_erro="twilio_send_failed",
                mensagem_erro=resultado_envio['error'],
                contexto={"telefone": telefone, "tentativas": resultado_envio.get('tentativas', 0)}
            )
        
        # Registrar métricas de sucesso
        tempo_resposta = time.time() - start_time
        metricas_bot.registrar_interacao(
            telefone=telefone,
            etapa=estado.etapa_atual,
            sucesso=resultado_envio["success"],
            dados_coletados=estado.dados_coletados,
            tempo_resposta=tempo_resposta
        )
        
        # Salvar conversa no banco
        if estado.artista_id:
            try:
                supabase.salvar_conversa(
                    artista_id=str(estado.artista_id),
                    mensagem=mensagem,
                    direcao="entrada"
                )
                supabase.salvar_conversa(
                    artista_id=str(estado.artista_id),
                    mensagem=resposta,
                    direcao="saida"
                )
            except Exception as e:
                logger.warning(f"Erro ao salvar conversa no banco: {str(e)}")
        
        logger.info(f"Processamento em background concluído para {telefone} em {tempo_resposta:.3f}s")
        
    except Exception as e:
        tempo_resposta = time.time() - start_time
        logger.error(f"Erro no processamento em background para {telefone}: {str(e)}")
        
        # Registrar erro
        metricas_bot.registrar_erro_sistema(
            tipo_erro="background_processing",
            mensagem_erro=str(e),
            contexto={"telefone": telefone, "tempo_resposta": tempo_resposta}
        )
        
        # Tentar enviar mensagem de erro para o usuário
        try:
            twilio_manager = obter_twilio_manager()
            mensagem_erro = "Desculpe, ocorreu um problema técnico. Tente novamente em alguns instantes."
            await twilio_manager.enviar_mensagem_whatsapp(telefone, mensagem_erro)
        except Exception as send_error:
            logger.error(f"Falha ao enviar mensagem de erro para {telefone}: {str(send_error)}")
    
    except:
        # Log final para casos extremos
        logger.critical(f"Erro crítico no processamento em background para {telefone}")
        raise


@app.post("/webhook/whatsapp")
async def webhook_whatsapp(
    request: Request,
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """Direct webhook processing - returns actual LLM response"""
    start_time = time.time()
    telefone = ""
    
    try:
        # Fast form parsing
        form_data = await request.form()
        form_dict = dict(form_data)
        
        # Quick validation
        telefone = form_dict.get("From", "")
        mensagem = form_dict.get("Body", "").strip()
        
        if not telefone or not mensagem:
            raise HTTPException(status_code=400, detail="Telefone ou mensagem em branco")
        
        # Clean phone number
        telefone_limpo = telefone.replace("whatsapp:", "")
        
        logger.info(f"Webhook recebido - {telefone_limpo}: {mensagem[:50]}...")
        
        # Get conversation state
        estado = obter_estado_conversa(telefone, supabase)
        
        # Process message directly with optimized flow
        try:
            # Check if it's an existing user first (quick check)
            artista_existente = supabase.buscar_artista_por_telefone(telefone_limpo)
            
            if artista_existente:
                # Use shorter timeout for existing users (should be instant)
                timeout_seconds = 3.0
                logger.info(f"Existing artist detected: {artista_existente.nome}, using fast timeout")
            else:
                # New users might need more time
                timeout_seconds = 13.0  # Slightly less than Twilio's 15s limit
                logger.info("New user detected, using standard timeout")
            
            # Use optimized flow that decides between direct response or LangGraph
            resposta_real = await asyncio.wait_for(
                processar_mensagem_otimizado(telefone, mensagem, estado, supabase),
                timeout=timeout_seconds
            )
            logger.info(f"Response obtained in time: {resposta_real[:100]}...")
        except asyncio.TimeoutError:
            logger.warning(f"Processing timeout for {telefone_limpo} after {timeout_seconds}s")
            resposta_real = "Desculpe, estou com uma lentidão momentânea. Pode repetir sua mensagem?"
        except asyncio.CancelledError:
            logger.warning(f"Processing cancelled for {telefone_limpo}")
            resposta_real = "Processamento interrompido. Por favor, tente novamente."
        
        # Save updated state
        salvar_estado_conversa(telefone, estado, supabase)
        
        # Generate TwiML response with ACTUAL LLM content
        response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta_real}</Message>
</Response>"""
        
        # Log response time
        tempo_resposta = time.time() - start_time
        logger.info(f"Real LLM response sent to {telefone_limpo} in {tempo_resposta:.3f}s")
        
        # Record webhook performance metric
        metricas_bot.registrar_interacao(
            telefone=telefone_limpo,
            etapa=estado.etapa_atual,
            sucesso=True,
            dados_coletados=estado.dados_coletados,
            tempo_resposta=tempo_resposta
        )
        
        return Response(
            content=response_xml,
            media_type="application/xml",
            status_code=200
        )
        
    except HTTPException:
        raise
    except Exception as e:
        tempo_resposta = time.time() - start_time
        logger.error(f"Webhook error: {str(e)} in {tempo_resposta:.3f}s")
        
        # Record error metric
        metricas_bot.registrar_erro_sistema(
            tipo_erro="webhook_error",
            mensagem_erro=str(e),
            contexto={"telefone": telefone, "tempo_resposta": tempo_resposta}
        )
        
        # Fast error response
        error_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>Desculpe, ocorreu um problema técnico. Tente novamente em alguns instantes.</Message>
</Response>"""
        
        return Response(
            content=error_xml,
            media_type="application/xml",
            status_code=200
        )



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
            "version": "1.0.0",
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
            "observabilidade_ativa": metricas_bot.client is not None
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
        estado = reiniciar_conversa(telefone, supabase)
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


# Endpoint para testes (remover em produção)
@app.post("/test/message")
async def test_message(
    # Diga explicitamente ao FastAPI para esperar 'telefone' e 'mensagem'
    # como campos de um formulário no corpo da requisição.
    telefone: str = Form(...),
    mensagem: str = Form(...),
    supabase: SupabaseManager = Depends(obter_supabase)
):
    """Endpoint para testar processamento de mensagens"""
    try:
        # O resto da função não precisa de nenhuma alteração
        estado = obter_estado_conversa(telefone, supabase)
        # A sua chamada para processar_fluxo_artista foi removida no refactoring do flow.py
        # Vamos usar a função correta que está no seu webhook, a processar_mensagem_otimizado
        # ou a processar_fluxo_artista se quiser testar o LangGraph diretamente.
        # Vamos usar processar_fluxo_artista para forçar o teste do LangGraph.
        resposta = await processar_fluxo_artista(telefone, mensagem, estado)
        salvar_estado_conversa(telefone, estado, supabase)
        
        return {
            "telefone": telefone,
            "mensagem_enviada": mensagem,
            "resposta_bot": resposta,
            "estado_atual": estado.model_dump() # Usando o método atualizado do Pydantic
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
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=os.getenv("ENVIRONMENT") == "development",
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
