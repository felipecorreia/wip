import os
import logging
from typing import Optional, Any
from uuid import UUID
import json
from supabase import create_client, Client
from langsmith import traceable
from .schemas import Artista, Contato, Link, TipoContato, EstadoConversa

logger = logging.getLogger(__name__)


class SupabaseManager:
    """Gerenciador de conexão e operações com Supabase"""
    
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            raise ValueError("SUPABASE_URL e SUPABASE_KEY devem estar configurados")
        
        self.supabase: Client = create_client(url, key)
        logger.info("Conexão com Supabase estabelecida")
    
    @traceable
    def salvar_artista(self, artista: Artista, tenant_id: str = None) -> dict[str, Any]:
        """Salva artista com transação completa"""
        try:
            # Preparar dados do artista
            # Converter links para dict serializable
            links_dict = None
            if artista.links:
                links_dict = {}
                for field, value in artista.links.dict().items():
                    if value is not None:
                        # Converter HttpUrl para string se necessário
                        links_dict[field] = str(value) if hasattr(value, '__str__') else value
            
            artista_data = {
                "id": str(artista.id),
                "nome": artista.nome,
                "cidade": artista.cidade,
                "estilo_musical": artista.estilo_musical.value if hasattr(artista.estilo_musical, 'value') else artista.estilo_musical,
                "links": links_dict,
                "biografia": artista.biografia,
                "experiencia_anos": artista.experiencia_anos
            }
            
            # Inserir artista principal
            result = self.supabase.table("artistas").insert(artista_data).execute()
            
            if not result.data:
                raise Exception("Erro ao inserir artista na base de dados")
            
            logger.info(f"Artista {artista.nome} inserido com ID {artista.id}")
            
            # Inserir contatos
            contatos_inseridos = 0
            for contato in artista.contatos:
                contato_data = {
                    "artista_id": str(artista.id),
                    "tipo": contato.tipo.value,
                    "valor": contato.valor,
                    "principal": contato.principal
                }
                
                contato_result = self.supabase.table("contatos_artistas").insert(contato_data).execute()
                if contato_result.data:
                    contatos_inseridos += 1
                    logger.debug(f"Contato {contato.tipo.value} inserido para artista {artista.id}")
            
            # Relacionar com tenant se fornecido
            if tenant_id:
                relacao_data = {
                    "artista_id": str(artista.id),
                    "tenant_id": tenant_id,
                    "status": "ativo",
                    "origem": "whatsapp"
                }
                
                tenant_result = self.supabase.table("artista_tenants").insert(relacao_data).execute()
                if tenant_result.data:
                    logger.info(f"Artista {artista.id} relacionado ao tenant {tenant_id}")
            
            logger.info(f"Artista {artista.nome} salvo com sucesso. Contatos: {contatos_inseridos}")
            
            return {
                "success": True,
                "artista_id": str(artista.id),
                "contatos_inseridos": contatos_inseridos
            }
            
        except Exception as e:
            logger.error(f"Erro ao salvar artista: {str(e)}")
            return {"success": False, "error": str(e)}
    
    @traceable
    def buscar_artista_por_telefone(self, telefone: str) -> Optional[Artista]:
        """Busca artista por número de telefone"""
        try:
            # Normalizar telefone (remover whatsapp: se presente)
            telefone_normalizado = telefone.replace("whatsapp:", "")
            
            # Buscar contato e artista relacionado
            result = self.supabase.table("contatos_artistas")\
                .select("artista_id, artistas(*)")\
                .eq("valor", telefone_normalizado)\
                .eq("tipo", TipoContato.WHATSAPP.value)\
                .execute()
            
            if result.data:
                artista_data = result.data[0]["artistas"]
                artista = self._dict_to_artista(artista_data)
                logger.info(f"Artista encontrado por telefone {telefone_normalizado}: {artista.nome}")
                return artista
            
            logger.info(f"Nenhum artista encontrado para telefone {telefone_normalizado}")
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar artista por telefone: {str(e)}")
            return None
    
    @traceable
    def buscar_artista_por_id(self, artista_id: str) -> Optional[Artista]:
        """Busca artista por ID"""
        try:
            result = self.supabase.table("artistas")\
                .select("*")\
                .eq("id", artista_id)\
                .execute()
            
            if result.data:
                artista = self._dict_to_artista(result.data[0])
                logger.info(f"Artista encontrado por ID {artista_id}: {artista.nome}")
                return artista
            
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar artista por ID: {str(e)}")
            return None
    
    @traceable
    def salvar_conversa(
        self, 
        artista_id: str, 
        mensagem: str, 
        direcao: str, 
        momento_chave: str = None, 
        tenant_id: str = None
    ):
        """Salva mensagem na tabela de conversas"""
        try:
            conversa_data = {
                "artista_id": artista_id,
                "tenant_id": tenant_id,
                "direcao": direcao,
                "mensagem": mensagem,
                "momento_chave": momento_chave
            }
            
            result = self.supabase.table("conversas").insert(conversa_data).execute()
            
            if result.data:
                logger.debug(f"Conversa salva para artista {artista_id}: {direcao}")
            else:
                logger.warning(f"Erro ao salvar conversa para artista {artista_id}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar conversa: {str(e)}")
    
    @traceable
    def salvar_estado_conversa(self, telefone: str, estado: EstadoConversa):
        """Salva estado da conversa (para persistência entre sessões)"""
        try:
            # Usar hash do telefone para privacidade
            telefone_hash = str(hash(telefone))
            
            estado_data = {
                "telefone_hash": telefone_hash,
                "artista_id": str(estado.artista_id) if estado.artista_id else None,
                "dados_coletados": estado.dados_coletados,
                "etapa_atual": estado.etapa_atual,
                "tentativas_coleta": estado.tentativas_coleta,
                "mensagens_historico": estado.mensagens_historico
            }
            
            # Usar upsert para atualizar se já existir
            result = self.supabase.table("estados_conversa")\
                .upsert(estado_data, on_conflict="telefone_hash")\
                .execute()
            
            if result.data:
                logger.debug(f"Estado da conversa salvo para telefone {telefone}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar estado da conversa: {str(e)}")
    
    @traceable
    def carregar_estado_conversa(self, telefone: str) -> Optional[EstadoConversa]:
        """Carrega estado da conversa persistido"""
        try:
            telefone_hash = str(hash(telefone))
            
            result = self.supabase.table("estados_conversa")\
                .select("*")\
                .eq("telefone_hash", telefone_hash)\
                .execute()
            
            if result.data:
                data = result.data[0]
                estado = EstadoConversa(
                    artista_id=data["artista_id"] if data["artista_id"] else None,
                    dados_coletados=data["dados_coletados"] or {},
                    etapa_atual=data["etapa_atual"] or "inicio",
                    tentativas_coleta=data["tentativas_coleta"] or 0,
                    mensagens_historico=data["mensagens_historico"] or []
                )
                logger.info(f"Estado da conversa carregado para telefone {telefone}")
                return estado
            
            return None
            
        except Exception as e:
            logger.error(f"Erro ao carregar estado da conversa: {str(e)}")
            return None
    
    @traceable
    def listar_artistas_por_tenant(self, tenant_id: str, limite: int = 50) -> list[Artista]:
        """Lista artistas de um tenant específico"""
        try:
            result = self.supabase.table("artista_tenants")\
                .select("artista_id, artistas(*)")\
                .eq("tenant_id", tenant_id)\
                .eq("status", "ativo")\
                .limit(limite)\
                .execute()
            
            artistas = []
            for item in result.data:
                if item["artistas"]:
                    artista = self._dict_to_artista(item["artistas"])
                    artistas.append(artista)
            
            logger.info(f"Encontrados {len(artistas)} artistas para tenant {tenant_id}")
            return artistas
            
        except Exception as e:
            logger.error(f"Erro ao listar artistas do tenant: {str(e)}")
            return []
    
    @traceable
    def atualizar_artista(self, artista: Artista) -> dict[str, Any]:
        """Atualiza dados de um artista existente"""
        try:
            artista_data = {
                "nome": artista.nome,
                "cidade": artista.cidade,
                "estilo_musical": artista.estilo_musical,
                "links": artista.links.dict() if artista.links else None,
                "biografia": artista.biografia,
                "experiencia_anos": artista.experiencia_anos
            }
            
            result = self.supabase.table("artistas")\
                .update(artista_data)\
                .eq("id", str(artista.id))\
                .execute()
            
            if result.data:
                logger.info(f"Artista {artista.id} atualizado com sucesso")
                return {"success": True, "artista_id": str(artista.id)}
            else:
                raise Exception("Nenhum registro foi atualizado")
            
        except Exception as e:
            logger.error(f"Erro ao atualizar artista: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _dict_to_artista(self, data: dict[str, Any]) -> Artista:
        """Converte dict do banco para objeto Artista"""
        try:
            # Buscar contatos do artista
            contatos_result = self.supabase.table("contatos_artistas")\
                .select("*")\
                .eq("artista_id", data["id"])\
                .execute()
            
            contatos = []
            for c in contatos_result.data:
                contato = Contato(
                    tipo=TipoContato(c["tipo"]),
                    valor=c["valor"],
                    principal=c["principal"]
                )
                contatos.append(contato)
            
            # Construir objeto Links se existir
            links = None
            if data.get("links") and isinstance(data["links"], dict):
                links = Link(**data["links"])
            
            # Construir objeto Artista
            artista = Artista(
                id=UUID(data["id"]),
                nome=data["nome"],
                cidade=data.get("cidade"),
                estilo_musical=data.get("estilo_musical"),
                links=links,
                contatos=contatos,
                biografia=data.get("biografia"),
                experiencia_anos=data.get("experiencia_anos")
            )
            
            return artista
            
        except Exception as e:
            logger.error(f"Erro ao converter dict para Artista: {str(e)}")
            raise
    
    @traceable
    def obter_estatisticas_tenant(self, tenant_id: str) -> dict[str, Any]:
        """Obtém estatísticas de um tenant"""
        try:
            # Contar artistas ativos
            artistas_result = self.supabase.table("artista_tenants")\
                .select("id", count="exact")\
                .eq("tenant_id", tenant_id)\
                .eq("status", "ativo")\
                .execute()
            
            total_artistas = artistas_result.count or 0
            
            # Contar conversas do último mês
            conversas_result = self.supabase.table("conversas")\
                .select("id", count="exact")\
                .eq("tenant_id", tenant_id)\
                .gte("created_at", "NOW() - INTERVAL '30 days'")\
                .execute()
            
            conversas_mes = conversas_result.count or 0
            
            return {
                "tenant_id": tenant_id,
                "total_artistas": total_artistas,
                "conversas_ultimo_mes": conversas_mes,
                "timestamp": "NOW()"
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas do tenant: {str(e)}")
            return {
                "tenant_id": tenant_id,
                "total_artistas": 0,
                "conversas_ultimo_mes": 0,
                "erro": str(e)
            }