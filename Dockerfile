# Usa a imagem oficial do Playwright que já contém o Chromium e dependências do sistema
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Define o diretório de trabalho
WORKDIR /app

# Copia os arquivos de dependências e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código do bot
COPY . .

# Comando para iniciar o bot
CMD ["python", "bot.py"]