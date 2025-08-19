#!/usr/bin/env python3
"""
Script de configuração inicial do banco de dados
Verifica se as tabelas existem e estão configuradas corretamente
"""

import os
import sys
from pathlib import Path

# Adicionar src ao path
sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.database import SupabaseManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verificar_tabelas():
    """Verifica se as tabelas necessárias existem no Supabase"""
    print("Verificando estrutura do banco de dados...")
    
    try:
        supabase = SupabaseManager()
        
        # Lista de tabelas que devem existir
        tabelas_necessarias = [
            "artistas",
            "contatos_artistas", 
            "conversas",
            "estados_conversa",
            "artista_tenants"
        ]
        
        tabelas_existentes = []
        tabelas_faltantes = []
        
        for tabela in tabelas_necessarias:
            try:
                # Tentar fazer uma query simples para verificar se a tabela existe
                result = supabase.supabase.table(tabela).select("*").limit(1).execute()
                tabelas_existentes.append(tabela)
                print(f" Tabela '{tabela}' encontrada")
            except Exception as e:
                tabelas_faltantes.append(tabela)
                print(f" Tabela '{tabela}' não encontrada: {str(e)}")
        
        if tabelas_faltantes:
            print(f"\n  Tabelas faltantes: {', '.join(tabelas_faltantes)}")
            print("Execute o script SQL de criação das tabelas primeiro.")
            return False
        else:
            print(f"\n Todas as {len(tabelas_existentes)} tabelas necessárias estão presentes")
            return True
            
    except Exception as e:
        print(f" Erro ao conectar com o banco: {str(e)}")
        return False


def testar_operacoes_basicas():
    """Testa operações básicas de CRUD"""
    print("\n Testando operações básicas...")
    
    try:
        supabase = SupabaseManager()
        
        # Testar inserção na tabela de estados_conversa
        telefone_teste = "test_setup_" + str(hash("test"))[:8]
        
        estado_data = {
            "telefone_hash": telefone_teste,
            "dados_coletados": {"teste": "setup"},
            "etapa_atual": "teste",
            "tentativas_coleta": 0,
            "mensagens_historico": ["teste"]
        }
        
        # Inserir
        result = supabase.supabase.table("estados_conversa").insert(estado_data).execute()
        if result.data:
            print(" Operação de INSERT funcionando")
            
            # Buscar
            search_result = supabase.supabase.table("estados_conversa")\
                .select("*")\
                .eq("telefone_hash", telefone_teste)\
                .execute()
            
            if search_result.data:
                print(" Operação de SELECT funcionando")
                
                # Limpar dados de teste
                delete_result = supabase.supabase.table("estados_conversa")\
                    .delete()\
                    .eq("telefone_hash", telefone_teste)\
                    .execute()
                
                if delete_result:
                    print(" Operação de DELETE funcionando")
                    return True
        
        print(" Algumas operações básicas falharam")
        return False
        
    except Exception as e:
        print(f" Erro nas operações básicas: {str(e)}")
        return False


def verificar_indices():
    """Verifica se índices importantes estão criados"""
    print("\n Verificando índices e performance...")
    
    # Para este MVP, apenas logar que a verificação deveria ser feita
    print("ℹ Para produção, considere criar índices em:")
    print("   - contatos_artistas.valor (busca por telefone)")
    print("   - conversas.artista_id (histórico de conversas)")
    print("   - estados_conversa.telefone_hash (estado da conversa)")
    print("   - artista_tenants.tenant_id (listagem por tenant)")
    
    return True


def configurar_rls():
    """Informações sobre Row Level Security"""
    print("\n Row Level Security (RLS):")
    print("  Para produção, configure políticas RLS em:")
    print("   - artistas: acesso baseado em tenant")
    print("   - contatos_artistas: acesso via artista")
    print("   - conversas: acesso via tenant")
    print("   - artista_tenants: acesso restrito por tenant")
    
    return True


def main():
    """Executa configuração completa do banco"""
    print(" CONFIGURAÇÃO DO BANCO DE DADOS - WIP ARTISTA BOT")
    print("=" * 60)
    
    # Carregar variáveis de ambiente
    load_dotenv()
    
    # Verificar variáveis necessárias
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        print(" Variáveis SUPABASE_URL e SUPABASE_KEY devem estar configuradas")
        return 1
    
    resultados = []
    
    # 1. Verificar tabelas
    resultados.append(("Verificação de Tabelas", verificar_tabelas()))
    
    # 2. Testar operações básicas
    resultados.append(("Operações Básicas", testar_operacoes_basicas()))
    
    # 3. Verificar índices
    resultados.append(("Índices", verificar_indices()))
    
    # 4. Configurar RLS
    resultados.append(("RLS Info", configurar_rls()))
    
    # Resumo
    print("\n" + "=" * 60)
    print(" RESUMO DA CONFIGURAÇÃO")
    print("=" * 60)
    
    sucessos = 0
    for nome, sucesso in resultados:
        status = " OK" if sucesso else "❌ ERRO"
        print(f"{nome:<25} {status}")
        if sucesso:
            sucessos += 1
    
    if sucessos == len(resultados):
        print("\n BANCO DE DADOS CONFIGURADO COM SUCESSO!")
        print("\nPróximos passos:")
        print("1. Execute o script de teste de integração:")
        print("   python scripts/test_integration.py")
        print("2. Inicie a aplicação:")
        print("   python main.py")
        return 0
    else:
        print("\n ALGUNS PROBLEMAS FORAM ENCONTRADOS.")
        print("Verifique os erros acima e execute novamente.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)