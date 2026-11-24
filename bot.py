import os
import asyncio
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from playwright.async_api import async_playwright
import traceback
import re

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

msg_progresso_geral = None
msg_corrida = None

async def fetch_all_data():
    dados = {'progresso_geral': None, 'corrida': []}
    try:
        async with async_playwright() as p:
            # Otimização: Roda sem interface gráfica e ignora restrições do container
            browser = await p.chromium.launch(
                headless=True, 
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            page = await browser.new_page()
            
            # Muda a espera para não travar caso o site tenha propagandas ou scripts infinitos
            await page.goto('https://portwatch-vi.xyz/', wait_until='domcontentloaded', timeout=25000)
            await page.wait_for_timeout(3000) # Dá 3 segundos extras para o JS rodar
            
            # 1. Progresso Geral
            try:
                await page.wait_for_selector('#ov-title', timeout=5000)
                texto_titulo = await page.inner_text('#ov-title')
                match = re.search(r'(\d+)%', texto_titulo)
                if match:
                    dados['progresso_geral'] = int(match.group(1))
            except Exception as e:
                print(f"Erro ao pegar progresso: {e}")

            # 2. Corrida
            try:
                await page.wait_for_selector('#race-list', timeout=5000)
                cards = await page.query_selector_all('#race-list li.effort')
                for card in cards:
                    nome_elem = await card.query_selector('.e-title h3 a')
                    pct_elem = await card.query_selector('.e-score b')
                    status_elem = await card.query_selector('.e-score small')
                    
                    if nome_elem and pct_elem:
                        dados['corrida'].append({
                            'nome': (await nome_elem.inner_text()).strip(),
                            'porcentagem': (await pct_elem.inner_text()).strip(),
                            'status': (await status_elem.inner_text()).strip() if status_elem else 'N/A'
                        })
            except Exception as e:
                print(f"Erro ao pegar corrida: {e}")

            await browser.close()
    except Exception as e:
        print(f"ERRO FATAL PLAYWRIGHT: {e}")
        traceback.print_exc()
        # Isso vai jogar o erro no Discord para sabermos o que é
        raise Exception(f"Falha no navegador: {str(e)}") 
    
    return dados

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
        description="Classificação atual dos projetos.",
        color=discord.Color.purple()
    )
    if not projetos:
        embed.add_field(name="Nenhum projeto encontrado", value="Não foi possível extrair os dados.", inline=False)
        return embed

    for i, p in enumerate(projetos[:10], start=1):
        embed.add_field(
            name=f"{i}. {p['nome']}",
            value=f"**{p['porcentagem']}** — {p['status']}",
            inline=False
        )
    embed.set_footer(text="Atualizado automaticamente a cada 30 minutos")
    return embed

@tasks.loop(minutes=30)
async def update_all():
    global msg_progresso_geral, msg_corrida
    if msg_progresso_geral is None and msg_corrida is None:
        return
    try:
        dados = await fetch_all_data()
        if msg_progresso_geral is not None and dados['progresso_geral'] is not None:
            await msg_progresso_geral.edit(embed=create_progress_embed(dados['progresso_geral']))
        if msg_corrida is not None and dados['corrida']:
            await msg_corrida.edit(embed=create_race_embed(dados['corrida']))
    except Exception:
        pass # Ignora erros no loop de fundo para não derrubar o bot

@bot.command(name='start_monitor')
async def start_monitor(ctx):
    global msg_progresso_geral
    if msg_progresso_geral is not None:
        await ctx.send("⚠️ O monitor de progresso geral já está ativo.")
        return

    msg_espera = await ctx.send("🔎 Buscando progresso geral, aguarde (isso pode levar até 30 segundos)...")
    try:
        dados = await fetch_all_data() # Se der erro, cai no except abaixo
        if dados['progresso_geral'] is None:
            await msg_espera.edit(content="❌ O navegador abriu, mas não achou o número na página. O site pode ter bloqueado o bot.")
            return

        msg_progresso_geral = await ctx.send(embed=create_progress_embed(dados['progresso_geral']))
        await msg_espera.delete()
        if not update_all.is_running():
            update_all.start()
    except Exception as e:
        # AQUI ELE VAI MOSTRAR O ERRO REAL
        await msg_espera.edit(content=f"❌ **Erro no Playwright:** `{e}`\nVerifique os logs do Railway (Deploy Logs).")

@bot.command(name='start_race')
async def start_race(ctx):
    global msg_corrida
    if msg_corrida is not None:
        await ctx.send("⚠️ O monitor da corrida já está ativo.")
        return

    msg_espera = await ctx.send("🔎 Buscando dados da corrida, aguarde...")
    try:
        dados = await fetch_all_data()
        if not dados['corrida']:
            await msg_espera.edit(content="❌ O navegador abriu, mas não achou a lista da corrida. O layout do site mudou ou o bot foi bloqueado.")
            return

        msg_corrida = await ctx.send(embed=create_race_embed(dados['corrida']))
        await msg_espera.delete()
        if not update_all.is_running():
            update_all.start()
    except Exception as e:
        await msg_espera.edit(content=f"❌ **Erro no Playwright:** `{e}`\nVerifique os logs do Railway (Deploy Logs).")

@bot.command(name='stop_all')
async def stop_all(ctx):
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
        print("ERRO: Token do Discord não encontrado.")
    else:
        bot.run(TOKEN)
