# WIP Artista Bot

Sistema completo de cadastro de artistas via WhatsApp para a **Cervejaria Bragantina** usando IA avançada e fluxos otimizados.

## Recursos

- **LLM com Fallback**: OpenAI → Anthropic → Gemini (sistema robusto de fallback)
- **Fluxo Híbrido**: Resposta instantânea para usuários existentes + LangGraph para novos cadastros
- **WhatsApp Nativo**: Integração direta via Twilio com timeout otimizado
- **Menu Inteligente**: Detecção de intenção por palavras-chave para respostas sub-segundo
- **Banco Multi-tenant**: Supabase com suporte completo à Cervejaria Bragantina
- **Observabilidade**: LangSmith para traces completos e debugging
- **Validação Rigorosa**: Schemas Pydantic com tratamento robusto de erros
- **Performance Otimizada**: Sistema de timeout adaptativo e processamento assíncrono

## Instalação

### 1. Clonar e Configurar Ambiente

```bash
git clone <repository-url>
cd wip-artista-bot

# Ativar ambiente virtual (já criado)
source .venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

### 2. Configurar Variáveis de Ambiente

```bash
# Copiar exemplo de configuração
cp .env.example .env

# Editar com suas credenciais
nano .env
```

### 3. Configurar Banco de Dados

```bash
# Executar script SQL no Supabase
# (usar arquivo supabase-setup-scripts.sql)

# Verificar configuração
python scripts/setup_db.py
```

### 4. Iniciar Aplicação

```bash
# Modo desenvolvimento
python main.py

# Ou usando uvicorn diretamente
uvicorn main:app --reload --port 8000
```

## Configuração dos Serviços

### Supabase
1. Criar projeto em [supabase.com](https://supabase.com)
2. Executar SQL de criação das tabelas
3. Obter URL e Key do projeto
4. Configurar em `.env`

### LLM (OpenAI, Anthropic e Gemini)
```env
# Provider primário
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Providers de fallback  
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...

# O sistema usa automaticamente fallback em caso de falha
```

### LangSmith (Observabilidade)
1. Criar conta em [smith.langchain.com](https://smith.langchain.com)
2. Obter API Key
3. Configurar projeto

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=wip-artista-bot
```

### Twilio WhatsApp
1. Configurar Sandbox WhatsApp no Twilio
2. Configurar webhook: `https://sua-url.com/webhook/whatsapp`
3. Criar tenant da Cervejaria Bragantina no Supabase

```env
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

```sql
-- Executar no Supabase SQL Editor
INSERT INTO tenants (id, nome, cidade, telefone)
VALUES (
    'b2894499-6bf5-4e91-8853-fa16c59ddf40',
    'Cervejaria Bragantina', 
    'Bragança Paulista',
    '+55 11 99999-8888'
);
```

## Uso

### Fluxo de Conversação

**Para Novos Usuários** (fluxo simplificado):
1. **Nome** do artista/banda (obrigatório)
2. **Estilo musical** principal  
3. **Cidade** onde atua
4. **Links** de redes sociais (Instagram, YouTube, Spotify)
5. Cadastro automático na Cervejaria Bragantina

**Para Usuários Existentes** (resposta instantânea):
- **Menu Principal**: Agenda, Dados, Casa
- **Detecção de Intenção**: Palavras-chave para resposta rápida
- **Atualização de Dados**: Fluxo específico para completar informações

### Comandos Especiais

- `/reiniciar` - Reinicia a conversa
- `/status` - Mostra progresso do cadastro

### Menu Interativo

- **Agenda** - Ver datas disponíveis para shows
- **Dados** - Atualizar informações do artista  
- **Casa** - Informações sobre a Cervejaria Bragantina

### Endpoints da API

- `GET /health` - Status da aplicação
- `GET /metrics` - Métricas do sistema
- `POST /webhook/whatsapp` - Webhook Twilio
- `GET /conversas/{telefone}/status` - Status conversa
- `GET /artistas` - Listar artistas

## Monitoramento

### LangSmith Dashboard
Acesse [smith.langchain.com](https://smith.langchain.com) para:
- Traces de conversações completas
- Métricas de performance do LLM
- Debugging de falhas
- Análise de qualidade dos dados coletados

### Logs da Aplicação
```bash
# Logs em tempo real
tail -f wip_bot.log

# Logs estruturados com nível INFO
python main.py
```

### Métricas via API
```bash
# Métricas diárias
curl http://localhost:8000/metrics

# Status de saúde
curl http://localhost:8000/health
```

## Desenvolvimento

### Executar Testes

```bash
# Testes unitários
pytest tests/

# Verificar configuração do banco
python scripts/setup_db.py

# Teste específico
pytest tests/test_llm.py -v
```

### Estrutura do Projeto

```
wip-artista-bot/
├── src/
│   ├── schemas.py          # Modelos Pydantic
│   ├── database.py         # Conexão Supabase  
│   ├── llm_config.py      # Configuração LLM com fallback
│   ├── flow.py            # Fluxo LangGraph original
│   ├── flow_direct.py     # Fluxo otimizado para usuários existentes
│   ├── flow_new_user.py   # Fluxo simplificado para novos usuários
│   ├── flow_update.py     # Fluxo específico para atualização de dados
│   ├── observability.py   # LangSmith e métricas
│   ├── queue_manager.py   # Processamento assíncrono
│   └── utils.py           # Funções auxiliares
├── tests/                  # Testes unitários
├── scripts/               # Scripts de configuração
├── docs/                  # Documentação
├── main.py               # FastAPI webhook principal
├── supabase-setup-scripts.sql  # Configuração do banco
└── requirements.txt      # Dependências
```

## Produção

### Variáveis Importantes
```env
ENVIRONMENT=production
LOG_LEVEL=WARNING
API_HOST=0.0.0.0
API_PORT=8000
```


## Solução de Problemas

### Erro de Conexão LLM
```bash
# Verificar credenciais
python -c "from src.llm_config import LLMConfig; LLMConfig().get_llm()"
```

### Erro de Conexão Supabase  
```bash
# Testar conectividade e configuração
python scripts/setup_db.py
```