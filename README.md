# WIP Artista Bot

## O Assistente de Curadoria Inteligente

O WIP Artista Bot é um sistema de onboarding conversacional para artistas, construído para a **Cervejaria Bragantina**. Utilizando IA avançada, o bot cria um fluxo de cadastro natural e inteligente via WhatsApp, abandonando os formulários rígidos em favor de um diálogo fluido.

O objetivo é simples: tratar o artista com a atenção que ele merece, enquanto otimiza o processo de curadoria para a casa de shows.

---

## Destaques da Arquitetura

-   **🧠 Extração de Dados com LLM**: O coração do bot. Em vez de um roteiro fixo, ele usa um LLM (com fallback entre OpenAI, Anthropic e Gemini) para entender e extrair informações de uma conversa em linguagem natural.
-   **⛓️ Orquestração com LangGraph**: O fluxo da conversa é gerenciado por um grafo de estados, permitindo lidar com diálogos complexos, parciais e não lineares. O grafo possui mecanismos de prevenção de loops para garantir robustez.
-   **⚡ Fluxo Híbrido Otimizado**: Respostas instantâneas para usuários já conhecidos e um fluxo de IA completo para novos cadastros, otimizando a experiência e a performance.
-   **📱 Integração Nativa com WhatsApp**: Conexão direta via Twilio, com timeouts adaptativos para garantir respostas dentro da janela da plataforma.
-   **🏢 Banco de Dados Multi-tenant**: Arquitetura no Supabase pronta para escalar para outras casas de show, com suporte completo à Cervejaria Bragantina.
-   **🔭 Observabilidade de Ponta a Ponta**: Traces detalhados de cada conversa no LangSmith para depuração, análise de performance e monitoramento da qualidade dos dados extraídos.
-   **🛡️ Validação e Robustez**: Uso de schemas Pydantic para garantir a integridade dos dados em todas as etapas do fluxo, desde a extração pelo LLM até a inserção no banco de dados.

---

## Instalação e Execução

### 1. Pré-requisitos
-   Python 3.11+
-   Conta no Supabase, Twilio, LangSmith e em pelo menos um provedor de LLM (OpenAI, Anthropic, Google).

### 2. Configuração do Ambiente
```bash
# Clone o repositório
git clone https://github.com/felipecorreia/wip.git
cd wip

# Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate

# Instale as dependências
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
wip/
├── src/
│   ├── schemas.py          # Modelos Pydantic (incluindo DadosExtraidos para o LLM)
│   ├── database.py         # Gerenciador do Supabase
│   ├── llm_config.py       # Configuração dos LLMs com lógica de fallback
│   ├── llm_extractor.py    # Função de extração de dados com LLM
│   ├── flow.py             # Lógica principal do fluxo com LangGraph
│   ├── conversation_utils.py # Funções auxiliares (reiniciar, status)
│   ├── observability.py    # Configuração do LangSmith
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