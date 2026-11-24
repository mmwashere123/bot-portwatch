import os
import asyncio
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Variáveis para as mensagens fixas
msg_progresso_geral = None
msg_corrida = None

async def fetch_all_data():
    """Extrai o progresso geral e a lista da corrida da página principal."""
    dados = {'progresso_geral': None, 'corrida': []}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # A página principal já contém a seção #race
            await page.goto('https://portwatch-vi.xyz/', wait_until='networkidle', timeout=30000)
            
            # 1. Extrair o progresso geral (o texto "Overall progress · closest effort to playable X%")
            try:
                # Espera o elemento do título aparecer
                await page.wait_for_selector('#ov-title', timeout=10000)
                texto_titulo = await page.inner_text('#ov-title')
                # Extrai o número antes do '%'
                import re
                match = re.search(r'(\d+)%', texto_titulo)
                if match:
                    dados['progresso_geral'] = int(match.group(1))
            except Exception as e:
                print(f"Erro ao extrair progresso geral: {e}")

            # 2. Extrair a lista da corrida
            try:
                await page.wait_for_selector('#race-list', timeout=10000)
                # Cada projeto é um <li> com a classe "effort"
                cards = await page.query_selector_all('#race-list li.effort')
                
                for card in cards:
                    # Nome do projeto
                    nome_elem = await card.query_selector('.e-title h3 a')
                    nome = await nome_elem.inner_text() if nome_elem else 'Desconhecido'
                    
                    # Porcentagem
                    pct_elem = await card.query_selector('.e-score b')
                    porcentagem = await pct_elem.inner_text() if pct_elem else 'N/A'
                    
                    # Status (milestone)
                    status_elem = await card.query_selector('.e-score small')
                    status = await status_elem.inner_text() if status_elem else 'N/A'
                    
                    if nome != 'Desconhecido' and porcentagem != 'N/A':
                        dados['corrida'].append({
                            'nome': nome.strip(),
                            'porcentagem': porcentagem.strip(),
                            'status': status.strip()
                        })
            except Exception as e:
                print(f"Erro ao extrair corrida: {e}")

            await browser.close()
    except Exception as e:
        print(f"Erro geral no fetch_all_data: {e}")
    return dados

# --- Funções para criar os Embeds ---

def create_progress_embed(progresso):
    embed = discord.Embed(
        title="📊 Progresso Geral do PortWatch VI",
        description=f"O projeto mais próximo de ser jogável está em **{progresso}%**.",
        color=discord.Color.purple()
    )
    embed.set_footer(text="Atualizado automaticamente a cada 30 minutos")
    return embed

def create_race_embed(projetos):
    embed = discord.Embed(
        title="🏁 A Corrida do PortWatch VI",
        description="Classificação atual dos projetos mais próximos de rodar GTA VI no PC.",
        color=discord.Color.purple()
    )
    
    if not projetos:
        embed.add_field(name="Nenhum projeto encontrado", value="Não foi possível extrair os dados da corrida.", inline=False)
        return embed

    # Pega os 10 primeiros projetos
    for i, p in enumerate(projetos[:10], start=1):
        embed.add_field(
            name=f"{i}. {p['nome']}",
            value=f"**{p['porcentagem']}** — {p['status']}",
            inline=False
        )
    
    embed.set_footer(text="Atualizado automaticamente a cada 30 minutos")
    return embed

# --- Tarefas em Loop ---

@tasks.loop(minutes=30)
async def update_all():
    global msg_progresso_geral, msg_corrida
    if msg_progresso_geral is None and msg_corrida is None:
        return
    
    dados = await fetch_all_data()
    
    # Atualiza o progresso geral, se a mensagem existir
    if msg_progresso_geral is not None and dados['progresso_geral'] is not None:
        embed = create_progress_embed(dados['progresso_geral'])
        try:
            await msg_progresso_geral.edit(embed=embed)
        except discord.NotFound:
            msg_progresso_geral = None

    # Atualiza a corrida, se a mensagem existir
    if msg_corrida is not None and dados['corrida']:
        embed = create_race_embed(dados['corrida'])
        try:
            await msg_corrida.edit(embed=embed)
        except discord.NotFound:
            msg_corrida = None

@update_all.before_loop
async def before_update():
    await bot.wait_until_ready()

# --- Comandos ---

@bot.command(name='start_monitor')
async def start_monitor(ctx):
    """Inicia o monitor do progresso geral."""
    global msg_progresso_geral
    if msg_progresso_geral is not None:
        await ctx.send("⚠️ O monitor de progresso geral já está ativo.")
        return

    await ctx.send("🔎 Buscando progresso geral, aguarde...")
    dados = await fetch_all_data()
    if dados['progresso_geral'] is None:
        await ctx.send("❌ Não foi possível obter o progresso geral.")
        return

    embed = create_progress_embed(dados['progresso_geral'])
    msg_progresso_geral = await ctx.send(embed=embed)
    if not update_all.is_running():
        update_all.start()
    await ctx.send("✅ Monitor de progresso geral iniciado!", delete_after=5)

@bot.command(name='start_race')
async def start_race(ctx):
    """Inicia o monitor da corrida."""
    global msg_corrida
    if msg_corrida is not None:
        await ctx.send("⚠️ O monitor da corrida já está ativo.")
        return

    await ctx.send("🔎 Buscando dados da corrida, aguarde...")
    dados = await fetch_all_data()
    if not dados['corrida']:
        await ctx.send("❌ Não foi possível obter os dados da corrida.")
        return

    embed = create_race_embed(dados['corrida'])
    msg_corrida = await ctx.send(embed=embed)
    if not update_all.is_running():
        update_all.start()
    await ctx.send("✅ Monitor da corrida iniciado!", delete_after=5)

@bot.command(name='stop_all')
async def stop_all(ctx):
    """Para todos os monitores."""
    global msg_progresso_geral, msg_corrida
    if update_all.is_running():
        update_all.stop()
    msg_progresso_geral = None
    msg_corrida = None
    await ctx.send("🛑 Todos os monitores foram parados.")

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

if __name__ == '__main__':
    if not TOKEN:
        print("ERRO: Token do Discord não encontrado. Verifique o arquivo .env")
    else:
        bot.run(TOKEN)