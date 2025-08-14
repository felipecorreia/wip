import os
import logging
import time
import functools
from typing import Any, Optional
from datetime import datetime, timedelta
from langsmith import Client, traceable
from langchain.callbacks import LangChainTracer

logger = logging.getLogger(__name__)


def configurar_langsmith() -> tuple[Client, LangChainTracer]:
    """Configura observabilidade com LangSmith"""
    
    # Verificar se as variáveis estão configuradas
    if not os.getenv("LANGCHAIN_API_KEY"):
        raise ValueError("LANGCHAIN_API_KEY não configurada")
    
    # Configurar projeto
    projeto = os.getenv("LANGCHAIN_PROJECT", "wip-artista-bot")
    os.environ["LANGCHAIN_PROJECT"] = projeto
    
    # Criar cliente
    client = Client()
    
    # Configurar tracer
    tracer = LangChainTracer(
        project_name=projeto,
        client=client
    )
    
    logger.info(f"LangSmith configurado - Projeto: {projeto}")
    return client, tracer


def configurar_observabilidade():
    """Configuração inicial de observabilidade"""
    
    # Configurar variáveis de ambiente se não estiverem definidas
    if not os.getenv("LANGCHAIN_TRACING_V2"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
    
    if not os.getenv("LANGCHAIN_ENDPOINT"):
        os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
    
    try:
        client, tracer = configurar_langsmith()
        logger.info("Observabilidade configurada com sucesso")
        return client, tracer
    except Exception as e:
        logger.warning(f"Erro ao configurar observabilidade: {str(e)}")
        return None, None


def monitorar_performance(nome_funcao: str = None):
    """Decorador para monitorar performance de funções"""
    def decorador(func):
        funcao_nome = nome_funcao or func.__name__
        
        @functools.wraps(func)
        @traceable(name=funcao_nome)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Log métricas
                logger.info(f"{funcao_nome} executada em {duration:.3f}s")
                
                # Adicionar métricas ao contexto do trace
                if hasattr(wrapper, '_langsmith_extra'):
                    wrapper._langsmith_extra.update({
                        "duration_seconds": duration,
                        "success": True
                    })
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"{funcao_nome} falhou após {duration:.3f}s: {str(e)}")
                
                # Adicionar erro ao contexto do trace
                if hasattr(wrapper, '_langsmith_extra'):
                    wrapper._langsmith_extra.update({
                        "duration_seconds": duration,
                        "success": False,
                        "error": str(e)
                    })
                
                raise
        
        return wrapper
    return decorador


class MetricasBot:
    """Classe para gerenciar métricas personalizadas do bot"""
    
    def __init__(self):
        try:
            self.client = Client()
            self.projeto = os.getenv("LANGCHAIN_PROJECT", "wip-artista-bot")
        except Exception as e:
            logger.warning(f"Erro ao inicializar cliente LangSmith: {str(e)}")
            self.client = None
    
    @traceable
    def registrar_interacao(
        self, 
        telefone: str, 
        etapa: str, 
        sucesso: bool, 
        dados_coletados: dict[str, Any],
        tempo_resposta: float = None,
        erro: str = None
    ):
        """Registra métricas de interação"""
        
        if not self.client:
            return
        
        try:
            # Hash do telefone para privacidade
            telefone_hash = str(abs(hash(telefone)))
            
            metadata = {
                "telefone_hash": telefone_hash,
                "etapa": etapa,
                "sucesso": sucesso,
                "campos_coletados": len([v for v in dados_coletados.values() if v]),
                "total_campos": len(dados_coletados),
                "timestamp": datetime.now().isoformat()
            }
            
            if tempo_resposta:
                metadata["tempo_resposta_seconds"] = tempo_resposta
            
            if erro:
                metadata["erro"] = erro
            
            # Enviar para LangSmith
            self.client.create_run(
                name="interacao_artista",
                run_type="chain",
                inputs={"etapa": etapa, "telefone_hash": telefone_hash},
                outputs={"sucesso": sucesso, "dados_coletados": len(dados_coletados)},
                extra=metadata
            )
            
            logger.debug(f"Métrica registrada - Etapa: {etapa}, Sucesso: {sucesso}")
            
        except Exception as e:
            logger.error(f"Erro ao registrar métrica: {str(e)}")
    
    @traceable
    def registrar_cadastro_completo(
        self, 
        telefone: str, 
        artista_id: str, 
        dados_finais: dict[str, Any],
        tempo_total: float,
        tentativas: int
    ):
        """Registra cadastro completo de artista"""
        
        if not self.client:
            return
        
        try:
            telefone_hash = str(abs(hash(telefone)))
            
            metadata = {
                "telefone_hash": telefone_hash,
                "artista_id": artista_id,
                "campos_preenchidos": len([v for v in dados_finais.values() if v]),
                "tempo_total_seconds": tempo_total,
                "tentativas_coleta": tentativas,
                "timestamp": datetime.now().isoformat(),
                "tipo_evento": "cadastro_completo"
            }
            
            # Analisar qualidade dos dados
            qualidade = self._calcular_qualidade_dados(dados_finais)
            metadata["qualidade_dados"] = qualidade
            
            self.client.create_run(
                name="cadastro_artista_completo",
                run_type="chain",
                inputs={"telefone_hash": telefone_hash},
                outputs={"artista_id": artista_id, "qualidade": qualidade},
                extra=metadata
            )
            
            logger.info(f"Cadastro completo registrado - Artista: {artista_id}, Qualidade: {qualidade}")
            
        except Exception as e:
            logger.error(f"Erro ao registrar cadastro completo: {str(e)}")
    
    def _calcular_qualidade_dados(self, dados: dict[str, Any]) -> str:
        """Calcula qualidade dos dados coletados"""
        campos_obrigatorios = ["nome"]
        campos_importantes = ["cidade", "estilo_musical"]
        campos_extras = ["biografia", "experiencia_anos", "instagram", "youtube", "spotify"]
        
        score = 0
        
        # Campos obrigatórios (peso 3)
        for campo in campos_obrigatorios:
            if dados.get(campo):
                score += 3
        
        # Campos importantes (peso 2)
        for campo in campos_importantes:
            if dados.get(campo):
                score += 2
        
        # Campos extras (peso 1)
        for campo in campos_extras:
            if dados.get(campo):
                score += 1
        
        # Classificar qualidade
        if score >= 10:
            return "excelente"
        elif score >= 7:
            return "boa"
        elif score >= 5:
            return "regular"
        else:
            return "baixa"
    
    def gerar_relatorio_periodo(
        self, 
        inicio: datetime, 
        fim: datetime
    ) -> dict[str, Any]:
        """Gera relatório de métricas para um período"""
        
        if not self.client:
            return {"erro": "Cliente LangSmith não disponível"}
        
        try:
            # Buscar runs do período
            runs = list(self.client.list_runs(
                project_name=self.projeto,
                start_time=inicio,
                end_time=fim
            ))
            
            # Processar métricas
            total_interacoes = len([r for r in runs if r.name == "interacao_artista"])
            cadastros_completos = len([r for r in runs if r.name == "cadastro_artista_completo"])
            
            sucessos = len([r for r in runs if r.outputs and r.outputs.get("sucesso")])
            taxa_sucesso = sucessos / total_interacoes if total_interacoes > 0 else 0
            
            # Calcular tempo médio de resposta
            tempos_resposta = [
                r.extra.get("tempo_resposta_seconds", 0) 
                for r in runs 
                if r.extra and r.extra.get("tempo_resposta_seconds")
            ]
            tempo_medio = sum(tempos_resposta) / len(tempos_resposta) if tempos_resposta else 0
            
            # Distribuição por etapa
            etapas = {}
            for run in runs:
                if run.extra and run.extra.get("etapa"):
                    etapa = run.extra["etapa"]
                    etapas[etapa] = etapas.get(etapa, 0) + 1
            
            return {
                "periodo": {
                    "inicio": inicio.isoformat(),
                    "fim": fim.isoformat()
                },
                "metricas": {
                    "total_interacoes": total_interacoes,
                    "cadastros_completos": cadastros_completos,
                    "taxa_sucesso": round(taxa_sucesso * 100, 2),
                    "tempo_medio_resposta": round(tempo_medio, 3),
                    "distribuicao_etapas": etapas
                },
                "gerado_em": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {str(e)}")
            return {"erro": str(e)}
    
    def gerar_relatorio_diario(self) -> dict[str, Any]:
        """Gera relatório de métricas do dia atual"""
        hoje = datetime.now().date()
        inicio = datetime.combine(hoje, datetime.min.time())
        fim = datetime.combine(hoje, datetime.max.time())
        
        return self.gerar_relatorio_periodo(inicio, fim)
    
    def gerar_relatorio_semanal(self) -> dict[str, Any]:
        """Gera relatório de métricas da última semana"""
        fim = datetime.now()
        inicio = fim - timedelta(days=7)
        
        return self.gerar_relatorio_periodo(inicio, fim)
    
    @traceable
    def registrar_erro_sistema(
        self, 
        tipo_erro: str, 
        mensagem_erro: str, 
        contexto: dict[str, Any] = None
    ):
        """Registra erros do sistema para monitoramento"""
        
        if not self.client:
            return
        
        try:
            metadata = {
                "tipo_erro": tipo_erro,
                "mensagem": mensagem_erro,
                "timestamp": datetime.now().isoformat(),
                "tipo_evento": "erro_sistema"
            }
            
            if contexto:
                metadata["contexto"] = contexto
            
            self.client.create_run(
                name="erro_sistema",
                run_type="tool",
                inputs={"tipo": tipo_erro},
                outputs={"erro": mensagem_erro},
                extra=metadata
            )
            
            logger.warning(f"Erro do sistema registrado: {tipo_erro} - {mensagem_erro}")
            
        except Exception as e:
            logger.error(f"Erro ao registrar erro do sistema: {str(e)}")


# Instância global para facilitar uso
metricas_bot = MetricasBot()


def inicializar_observabilidade():
    """Inicializa todos os componentes de observabilidade"""
    try:
        # Configurar LangSmith
        client, tracer = configurar_observabilidade()
        
        # Configurar logging estruturado
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('wip_bot.log')
            ]
        )
        
        # Registrar inicialização
        if client:
            metricas_bot.registrar_interacao(
                telefone="sistema",
                etapa="inicializacao",
                sucesso=True,
                dados_coletados={"status": "inicializado"}
            )
        
        logger.info("Observabilidade inicializada com sucesso")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao inicializar observabilidade: {str(e)}")
        return False


# Middleware para capturar métricas automaticamente
class ObservabilityMiddleware:
    """Middleware para capturar métricas automaticamente em requests"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            start_time = time.time()
            
            # Processar request
            try:
                await self.app(scope, receive, send)
                duration = time.time() - start_time
                
                # Registrar métrica de sucesso
                metricas_bot.registrar_interacao(
                    telefone="api_request",
                    etapa="webhook_request",
                    sucesso=True,
                    dados_coletados={"path": scope.get("path", "")},
                    tempo_resposta=duration
                )
                
            except Exception as e:
                duration = time.time() - start_time
                
                # Registrar erro
                metricas_bot.registrar_erro_sistema(
                    tipo_erro="webhook_error",
                    mensagem_erro=str(e),
                    contexto={"path": scope.get("path", ""), "duration": duration}
                )
                raise
        else:
            await self.app(scope, receive, send)