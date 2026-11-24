# Usa a imagem oficial do Playwright, que já contém o Chromium e as dependências do sistema
FROM mcr.microsoft.com/playwright/python:v1.65.2-jammy

# Define o diretório de trabalho
WORKDIR /app

# Copia e instala as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do bot
COPY . .

# Define a variável de ambiente para o Playwright encontrar o navegador
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Comando para iniciar o bot
CMD ["python", "bot.py"]
