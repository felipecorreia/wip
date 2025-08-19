"""
Humanizador de Mensagens - Quebra respostas longas em mensagens curtas
Mantém a geração por LLM, apenas formata de forma mais humana
"""

import re
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

class MessageHumanizer:
    """Quebra mensagens longas em conversas mais naturais"""
    
    def __init__(self, max_chars_per_message: int = 100):
        self.max_chars = max_chars_per_message
        
    def quebrar_resposta(self, resposta_original: str) -> List[str]:
        """
        Quebra uma resposta longa em múltiplas mensagens curtas
        Mantém o conteúdo original, só reorganiza
        """
        
        # Se já é curta, retorna como está
        if len(resposta_original) <= self.max_chars:
            return [resposta_original]
        
        # Estratégias de quebra por tipo de conteúdo
        if "preciso" in resposta_original.lower() and "cadastro" in resposta_original.lower():
            return self._quebrar_solicitacao_dados(resposta_original)
        elif "prazer" in resposta_original.lower() or "olá" in resposta_original.lower():
            return self._quebrar_saudacao(resposta_original)
        elif "perfeito" in resposta_original.lower() and "cadastro" in resposta_original.lower():
            return self._quebrar_confirmacao(resposta_original)
        else:
            return self._quebrar_generico(resposta_original)
    
    def _quebrar_saudacao(self, texto: str) -> List[str]:
        """Quebra saudações em partes naturais"""
        mensagens = []
        
        # Primeira parte: saudação
        if "prazer" in texto.lower():
            match = re.search(r"(Prazer[^!.]*[!.])", texto)
            if match:
                mensagens.append(match.group(1))
                texto = texto.replace(match.group(1), "").strip()
        elif "olá" in texto.lower() or "oi" in texto.lower():
            match = re.search(r"((?:Olá|Oi)[^.!]*[.!])", texto)
            if match:
                mensagens.append(match.group(1))
                texto = texto.replace(match.group(1), "").strip()
        
        # Segunda parte: apresentação
        if "sou a wip" in texto.lower():
            match = re.search(r"(Sou a WIP[^.]*\.)", texto, re.IGNORECASE)
            if match:
                mensagens.append(match.group(1))
                texto = texto.replace(match.group(1), "").strip()
        
        # Resto
        if texto:
            # Quebra o resto em frases
            frases = re.split(r'[.!?]+', texto)
            for frase in frases:
                if frase.strip():
                    mensagens.append(frase.strip() + ("?" if "?" in texto else "."))
        
        return mensagens if mensagens else [texto]
    
    def _quebrar_solicitacao_dados(self, texto: str) -> List[str]:
        """Quebra solicitação de dados em partes"""
        mensagens = []
        
        # Primeira confirmação
        if any(word in texto.lower() for word in ["legal", "ótimo", "show", "perfeito"]):
            match = re.search(r"^([^!.]*[!.])", texto)
            if match:
                mensagens.append(match.group(1))
                texto = texto.replace(match.group(1), "").strip()
        
        # Separa "preciso saber" ou "falta"
        if "preciso" in texto.lower() or "falta" in texto.lower():
            # Pega até o final da lista de itens
            parts = texto.split(".")
            if parts:
                mensagens.append(parts[0] + ".")
                if len(parts) > 1:
                    resto = ". ".join(parts[1:]).strip()
                    if resto:
                        mensagens.append(resto)
        else:
            mensagens.append(texto)
        
        return mensagens if mensagens else [texto]
    
    def _quebrar_confirmacao(self, texto: str) -> List[str]:
        """Quebra confirmações de cadastro"""
        mensagens = []
        
        # "Perfeito!"
        if texto.lower().startswith("perfeito"):
            mensagens.append("Perfeito! 🎸")
            texto = re.sub(r"^Perfeito[!.]?\s*", "", texto, flags=re.IGNORECASE).strip()
        
        # "Cadastro completo" ou similar
        if "cadastro" in texto.lower():
            match = re.search(r"([^.]*cadastro[^.]*\.)", texto, re.IGNORECASE)
            if match:
                mensagens.append(match.group(1))
                texto = texto.replace(match.group(1), "").strip()
        
        # Resto
        if texto:
            mensagens.append(texto)
        
        return mensagens if mensagens else [texto]
    
    def _quebrar_generico(self, texto: str) -> List[str]:
        """Quebra genérica por pontuação"""
        # Quebra por frases completas
        frases = re.split(r'(?<=[.!?])\s+', texto)
        
        mensagens = []
        buffer = ""
        
        for frase in frases:
            if len(buffer) + len(frase) <= self.max_chars:
                buffer = (buffer + " " + frase).strip()
            else:
                if buffer:
                    mensagens.append(buffer)
                buffer = frase
        
        if buffer:
            mensagens.append(buffer)
        
        return mensagens if mensagens else [texto]
    
    def formatar_para_whatsapp(self, mensagens: List[str]) -> str:
        """
        Formata múltiplas mensagens para envio via WhatsApp
        Usa quebras de linha duplas para simular mensagens separadas
        """
        return "\n\n".join(mensagens)
    
    def adicionar_delays(self, mensagens: List[str]) -> List[Tuple[str, int]]:
        """
        Adiciona delays sugeridos entre mensagens
        Retorna lista de tuplas (mensagem, delay_ms)
        """
        resultado = []
        for i, msg in enumerate(mensagens):
            # Calcula delay baseado no tamanho da mensagem anterior
            # Simula tempo de digitação: ~50ms por caractere
            if i == 0:
                delay = 0
            else:
                delay = min(len(mensagens[i-1]) * 50, 3000)  # Max 3 segundos
            
            resultado.append((msg, delay))
        
        return resultado


# Função helper para uso rápido
def humanizar_resposta(resposta: str, quebrar: bool = True) -> str:
    """
    Função conveniente para humanizar respostas
    
    Args:
        resposta: Resposta original do LLM
        quebrar: Se deve quebrar em múltiplas mensagens
    
    Returns:
        String formatada para WhatsApp (com quebras de linha duplas)
    """
    if not quebrar:
        return resposta
    
    humanizer = MessageHumanizer(max_chars_per_message=120)
    mensagens = humanizer.quebrar_resposta(resposta)
    
    # Log para debug
    if len(mensagens) > 1:
        logger.info(f"Resposta quebrada em {len(mensagens)} mensagens")
    
    return humanizer.formatar_para_whatsapp(mensagens)


# Exemplos de uso
if __name__ == "__main__":
    # Teste com diferentes tipos de resposta
    exemplos = [
        "Prazer, Rock Total! Sou a WIP, responsável pela agenda de shows da Cervejaria Bragantina. Para completar seu cadastro, preciso saber estilo musical, de onde vocês são e links do seu trabalho.",
        
        "Olá! Sou a WIP da Cervejaria Bragantina, responsável pela nossa agenda de shows. Adoraria conhecer seu trabalho! Me conta o nome da sua banda/projeto e que tipo de som vocês fazem?",
        
        "Perfeito! Cadastro completo! Agora vocês fazem parte do nosso banco de artistas. Vou analisar o material e em breve entro em contato com possíveis datas.",
        
        "Legal! Ainda preciso de algumas informações: o estilo musical de vocês e de onde vocês são."
    ]
    
    humanizer = MessageHumanizer()
    
    for exemplo in exemplos:
        print(f"\nORIGINAL:\n{exemplo}")
        print(f"\nHUMANIZADO:")
        mensagens = humanizer.quebrar_resposta(exemplo)
        for i, msg in enumerate(mensagens, 1):
            print(f"  Msg {i}: {msg}")
        print("-" * 50)