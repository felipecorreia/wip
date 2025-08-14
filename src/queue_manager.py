import asyncio
import logging
import uuid
import time
from typing import Dict, Any, Optional
from datetime import datetime
import json

from .schemas import EstadoConversa
from .database import SupabaseManager
from .utils import obter_twilio_manager

logger = logging.getLogger(__name__)

class MessageQueue:
    """Advanced message queue for background processing with immediate acknowledgment"""
    
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=1000)  # Prevent memory overflow
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        self.results_cache: Dict[str, Dict[str, Any]] = {}
        self.stats = {
            'messages_queued': 0,
            'messages_processed': 0,
            'messages_failed': 0,
            'processing_times': []
        }
        self.is_running = False
        self._worker_task: Optional[asyncio.Task] = None
        
    async def start_processing(self):
        """Start the background queue processor"""
        if not self.is_running:
            self.is_running = True
            self._worker_task = asyncio.create_task(self._process_queue_worker())
            logger.info("Message queue processing started")
    
    async def stop_processing(self):
        """Stop the background queue processor"""
        if self.is_running:
            self.is_running = False
            if self._worker_task:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
            logger.info("Message queue processing stopped")
    
    async def add_message(
        self, 
        telefone: str, 
        mensagem: str, 
        estado: EstadoConversa
    ) -> str:
        """Add message to processing queue and return immediate response"""
        
        message_id = str(uuid.uuid4())
        
        # Generate contextual immediate response
        immediate_response = self._generate_immediate_response(estado, mensagem)
        
        # Queue message for background processing
        queue_item = {
            'message_id': message_id,
            'telefone': telefone,
            'mensagem': mensagem,
            'estado': estado.dict(),
            'timestamp': datetime.now().isoformat(),
            'retry_count': 0,
            'max_retries': 2
        }
        
        try:
            await self.queue.put(queue_item)
            self.stats['messages_queued'] += 1
            logger.info(f"Message queued for background processing: {message_id} from {telefone}")
        except asyncio.QueueFull:
            logger.error("Message queue is full, rejecting message")
            return "Sistema temporariamente sobrecarregado. Tente novamente em alguns instantes."
        
        return immediate_response
    
    def _generate_immediate_response(self, estado: EstadoConversa, mensagem: str) -> str:
        """Generate contextual immediate acknowledgment based on conversation state"""
        
        # Handle special commands immediately
        if mensagem.lower() in ["/reiniciar", "/restart", "reiniciar"]:
            return "Entendido! Vou reiniciar seu cadastro..."
        elif mensagem.lower() in ["/status", "status"]:
            return "Um momento, vou verificar o status do seu cadastro..."
        elif mensagem.lower() in ["/ajuda", "/help", "ajuda"]:
            return "Preparando informações de ajuda..."
        
        # Context-aware responses based on current stage
        if estado.etapa_atual == "inicio":
            if any(greeting in mensagem.lower() for greeting in ["oi", "olá", "hello", "boa"]):
                return "Olá! Recebemos sua mensagem. Vamos iniciar seu cadastro de artista..."
            else:
                return "Recebido! Iniciando processamento do seu cadastro..."
        
        elif estado.etapa_atual == "coleta_nome":
            return "Perfeito! Processando o nome informado..."
        
        elif estado.etapa_atual == "coleta_cidade":
            return "Obrigada! Verificando a cidade informada..."
        
        elif estado.etapa_atual == "coleta_estilo":
            return "Entendi! Processando o estilo musical..."
        
        elif estado.etapa_atual == "coleta_experiencia":
            return "Certo! Analisando o tempo de experiência..."
        
        elif estado.etapa_atual == "coleta_biografia":
            return "Excelente! Processando sua biografia..."
        
        elif estado.etapa_atual == "coleta_links":
            return "Ótimo! Verificando os links informados..."
        
        elif estado.etapa_atual.startswith("coleta_"):
            return "Informação recebida! Processando seus dados..."
        
        elif estado.etapa_atual == "validacao":
            return "Quase pronto! Validando todas as informações..."
        
        elif estado.etapa_atual == "finalizacao":
            return "Finalizando seu cadastro. Aguarde um momento..."
        
        else:
            # Default response based on completion percentage
            dados_count = len([v for v in estado.dados_coletados.values() if v])
            if dados_count == 0:
                return "Olá! Vamos começar seu cadastro de artista. Processando..."
            elif dados_count < 3:
                return "Continuando seu cadastro. Processando a informação..."
            else:
                return "Estamos quase terminando! Processando seus dados..."
    
    async def _process_queue_worker(self):
        """Background worker to process queued messages"""
        logger.info("Queue worker started")
        
        while self.is_running:
            try:
                # Get next message with timeout to allow graceful shutdown
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # Check if still running
                
                message_id = item['message_id']
                
                # Process message with retry logic
                success = await self._process_message_with_retry(item)
                
                if success:
                    self.stats['messages_processed'] += 1
                else:
                    self.stats['messages_failed'] += 1
                
                # Mark queue task as done
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in queue worker: {str(e)}")
                await asyncio.sleep(1)  # Prevent tight error loop
        
        logger.info("Queue worker stopped")
    
    async def _process_message_with_retry(self, item: Dict[str, Any]) -> bool:
        """Process message with retry logic"""
        message_id = item['message_id']
        telefone = item['telefone']
        retry_count = item.get('retry_count', 0)
        max_retries = item.get('max_retries', 2)
        
        start_time = time.time()
        
        try:
            # Reconstruct conversation state
            estado = EstadoConversa(**item['estado'])
            mensagem = item['mensagem']
            supabase = SupabaseManager()
            
            logger.info(f"Processing message {message_id} (attempt {retry_count + 1}/{max_retries + 1})")
            
            # Process message through LangGraph flow
            resposta = await self._process_message_full_pipeline(telefone, mensagem, estado, supabase)
            
            # DISABLED: Response is now sent directly via webhook
            # success = await self._send_response_via_twilio(telefone, resposta)
            success = True  # Always mark as success since webhook handles response
            
            if success:
                # Record processing time
                processing_time = time.time() - start_time
                self.stats['processing_times'].append(processing_time)
                
                # Keep only last 100 processing times for memory efficiency
                if len(self.stats['processing_times']) > 100:
                    self.stats['processing_times'] = self.stats['processing_times'][-100:]
                
                logger.info(f"Message {message_id} processed successfully in {processing_time:.3f}s")
                return True
            else:
                raise Exception("Failed to send response via Twilio")
        
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Error processing message {message_id}: {str(e)} (time: {processing_time:.3f}s)")
            
            # Retry logic
            if retry_count < max_retries:
                retry_delay = min(2 ** retry_count, 30)  # Exponential backoff, max 30s
                logger.info(f"Retrying message {message_id} in {retry_delay}s")
                
                # Re-queue with incremented retry count
                item['retry_count'] = retry_count + 1
                
                # Schedule retry after delay
                asyncio.create_task(self._schedule_retry(item, retry_delay))
                return False
            else:
                # Send error message to user after all retries failed
                error_message = "Desculpe, houve um problema técnico persistente. Entre em contato com o suporte."
                await self._send_response_via_twilio(telefone, error_message)
                logger.error(f"Message {message_id} failed after {max_retries + 1} attempts")
                return False
    
    async def _schedule_retry(self, item: Dict[str, Any], delay: float):
        """Schedule a retry after the specified delay"""
        await asyncio.sleep(delay)
        try:
            await self.queue.put(item)
            logger.info(f"Message {item['message_id']} re-queued for retry")
        except asyncio.QueueFull:
            logger.error(f"Failed to re-queue message {item['message_id']} - queue full")
    
    async def _process_message_full_pipeline(
        self, 
        telefone: str, 
        mensagem: str, 
        estado: EstadoConversa, 
        supabase: SupabaseManager
    ) -> str:
        """Process message through the full pipeline"""
        from .flow import processar_fluxo_artista, reiniciar_conversa, obter_progresso_conversa
        
        # Handle special commands
        if mensagem.lower() in ["/reiniciar", "/restart", "reiniciar"]:
            estado = reiniciar_conversa(telefone, supabase)
            return "Conversa reiniciada! Vamos começar seu cadastro do zero. Qual é o seu nome ou nome da sua banda?"
        
        elif mensagem.lower() in ["/status", "status"]:
            progresso = obter_progresso_conversa(estado)
            return f"Status do seu cadastro:\n- Progresso: {progresso['progresso_percentual']}%\n- Etapa atual: {progresso['etapa_atual']}\n- Tentativas: {progresso['tentativas']}"
        
        else:
            # Process through LangGraph flow
            return await processar_fluxo_artista(telefone, mensagem, estado, supabase)
    
    async def _send_response_via_twilio(self, telefone: str, resposta: str) -> bool:
        """Send response via Twilio API"""
        try:
            twilio_manager = obter_twilio_manager()
            resultado = await twilio_manager.enviar_mensagem_whatsapp(telefone, resposta)
            
            if resultado["success"]:
                logger.info(f"Response sent successfully to {telefone}")
                return True
            else:
                logger.error(f"Failed to send response to {telefone}: {resultado.get('error')}")
                return False
        
        except Exception as e:
            logger.error(f"Exception sending response to {telefone}: {str(e)}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        avg_processing_time = 0
        if self.stats['processing_times']:
            avg_processing_time = sum(self.stats['processing_times']) / len(self.stats['processing_times'])
        
        return {
            'queue_size': self.queue.qsize(),
            'messages_queued': self.stats['messages_queued'],
            'messages_processed': self.stats['messages_processed'],
            'messages_failed': self.stats['messages_failed'],
            'success_rate': (
                self.stats['messages_processed'] / max(1, self.stats['messages_processed'] + self.stats['messages_failed'])
            ) * 100,
            'avg_processing_time': avg_processing_time,
            'active_tasks': len(self.processing_tasks),
            'is_running': self.is_running
        }

# Global queue instance
message_queue = MessageQueue()