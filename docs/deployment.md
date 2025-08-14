# Guia de Deploy - WIP Artista Bot

## Deploy em Produção

### 1. Preparação do Ambiente

#### Servidor Recomendado
- **CPU**: 2+ cores
- **RAM**: 4GB+ 
- **Storage**: 20GB+ SSD
- **OS**: Ubuntu 22.04 LTS
- **Python**: 3.9+

#### Dependências do Sistema
```bash
# Atualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python e ferramentas
sudo apt install python3 python3-pip python3-venv nginx supervisor -y

# Instalar certificados SSL
sudo apt install certbot python3-certbot-nginx -y
```

### 2. Configuração da Aplicação

#### Clonar e Configurar
```bash
# Criar usuário para aplicação
sudo useradd -m -s /bin/bash wip-bot

# Clonar código
cd /home/wip-bot
sudo -u wip-bot git clone <repo-url> wip-artista-bot
cd wip-artista-bot

# Criar ambiente virtual
sudo -u wip-bot python3 -m venv .venv
sudo -u wip-bot .venv/bin/pip install -r requirements.txt
```

#### Configurar Variáveis de Ambiente
```bash
sudo -u wip-bot cp .env.example .env
sudo -u wip-bot nano .env
```

```env
# Configurações de produção
ENVIRONMENT=production
LOG_LEVEL=WARNING
API_HOST=0.0.0.0
API_PORT=8000

# LLM
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=wip-artista-bot-prod

# Twilio
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_NUMBER=whatsapp:+...
```

### 3. Configuração do Supervisor

#### Criar arquivo de configuração
```bash
sudo nano /etc/supervisor/conf.d/wip-artista-bot.conf
```

```ini
[program:wip-artista-bot]
command=/home/wip-bot/wip-artista-bot/.venv/bin/python main.py
directory=/home/wip-bot/wip-artista-bot
user=wip-bot
autostart=true
autorestart=true
stdout_logfile=/var/log/wip-artista-bot.log
stderr_logfile=/var/log/wip-artista-bot-error.log
environment=PATH="/home/wip-bot/wip-artista-bot/.venv/bin"
```

#### Ativar e iniciar
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start wip-artista-bot
sudo supervisorctl status
```

### 4. Configuração do Nginx

#### Criar configuração
```bash
sudo nano /etc/nginx/sites-available/wip-artista-bot
```

```nginx
server {
    listen 80;
    server_name seu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60;
        proxy_send_timeout 60;
        proxy_read_timeout 60;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }

    # Rate limiting
    location /webhook/whatsapp {
        limit_req zone=webhook burst=10 nodelay;
        proxy_pass http://127.0.0.1:8000/webhook/whatsapp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# Rate limiting configuration
http {
    limit_req_zone $binary_remote_addr zone=webhook:10m rate=5r/s;
}
```

#### Ativar site
```bash
sudo ln -s /etc/nginx/sites-available/wip-artista-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 5. Configuração SSL

```bash
# Obter certificado SSL
sudo certbot --nginx -d seu-dominio.com

# Testar renovação automática
sudo certbot renew --dry-run
```

### 6. Configuração do Twilio

No painel do Twilio:
1. Ir para WhatsApp Sandbox/Production
2. Configurar webhook: `https://seu-dominio.com/webhook/whatsapp`
3. Método: POST
4. Testar conectividade

### 7. Monitoramento

#### Logs da Aplicação
```bash
# Logs em tempo real
sudo tail -f /var/log/wip-artista-bot.log

# Logs de erro
sudo tail -f /var/log/wip-artista-bot-error.log

# Logs do Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

#### Health Checks
```bash
# Verificar status da aplicação
curl https://seu-dominio.com/health

# Verificar métricas
curl https://seu-dominio.com/metrics
```

#### Configurar Monitoramento Externo
- **Uptime Robot**: Para monitorar disponibilidade
- **New Relic/DataDog**: Para métricas avançadas
- **LangSmith**: Para observabilidade do LLM

### 8. Backup e Segurança

#### Backup do Código
```bash
# Script de backup
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf /backups/wip-bot-$DATE.tar.gz /home/wip-bot/wip-artista-bot
```

#### Firewall
```bash
sudo ufw allow 22    # SSH
sudo ufw allow 80    # HTTP  
sudo ufw allow 443   # HTTPS
sudo ufw enable
```

#### Atualizações de Segurança
```bash
# Configurar atualizações automáticas
sudo apt install unattended-upgrades -y
sudo dpkg-reconfigure unattended-upgrades
```

## Deploy com Docker (Alternativo)

### 1. Criar Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
```

### 2. Docker Compose
```yaml
version: '3.8'
services:
  wip-bot:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
    env_file:
      - .env
    restart: unless-stopped
    volumes:
      - ./logs:/app/logs
```

### 3. Deploy
```bash
docker-compose up -d
docker-compose logs -f
```

## Troubleshooting

### Problemas Comuns

#### Aplicação não inicia
```bash
# Verificar logs
sudo supervisorctl tail -f wip-artista-bot

# Testar manualmente
cd /home/wip-bot/wip-artista-bot
sudo -u wip-bot .venv/bin/python main.py
```

#### Webhook não funciona
```bash
# Testar conectividade
curl -X POST https://seu-dominio.com/webhook/whatsapp \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp:+5511999999999&Body=teste"
```

#### Performance baixa
1. Verificar recursos do servidor
2. Analisar logs do LangSmith
3. Considerar cache Redis para estados
4. Otimizar prompts do LLM

#### Erro de LLM
```bash
# Verificar credenciais
cd /home/wip-bot/wip-artista-bot
sudo -u wip-bot .venv/bin/python -c "from src.llm_config import LLMConfig; LLMConfig().get_llm()"
```

## Escalabilidade

### Load Balancer
Para múltiplas instâncias:
```nginx
upstream wip_backend {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    location / {
        proxy_pass http://wip_backend;
    }
}
```

### Estado Compartilhado
Para múltiplas instâncias, usar Redis:
```python
# No main.py, substituir dict em memória
import redis
redis_client = redis.Redis(host='localhost', port=6379)
```

### Banco de Dados
Para alta disponibilidade:
- Usar réplicas de leitura Supabase
- Implementar retry logic
- Configurar connection pooling