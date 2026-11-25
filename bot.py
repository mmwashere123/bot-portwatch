import os
import re
import asyncio
import traceback
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
URL = 'https://gta6recomp.com/repo'

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

msg_progresso_geral = None
msg_corrida = None
fetch_lock = asyncio.Lock()  # só um navegador por vez

# Pega cada <h3> e sobe até o "card" que contém só aquele título
JS_CARDS = """
() => {
  const out = [];
  for (const h of document.querySelectorAll('h3')) {
    let el = h;
    while (el.parentElement && el.parentElement.querySelectorAll('h3').length === 1) {
      el = el.parentElement;
    }
    out.push({ nome: h.innerText.trim(), texto: el.innerText });
  }
  return out;
}
"""


def parse_card(nome, texto):
    """Extrai porcentagem e status de um card. Retorna None se não tiver %."""
    m = re.search(r'(\d{1,3})\s*%', texto)
    if not m:
        return None
    pct = int(m.group(1))

    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    status = ''
    for i, linha in enumerate(linhas):
        if m.group(0) in linha:
            status = linha.split(m.group(0), 1)[1].strip(' ·-—')
            if not status and i + 1 < len(linhas):
                status = linhas[i + 1]
            break
    if status.startswith('(') and status.endswith(')'):
        status = status[1:-1]

    return {'nome': nome, 'pct': pct, 'status': status or 'N/A'}


async def fetch_all_data():
    dados = {'progresso_geral': None, 'corrida': []}

    async with fetch_lock:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox',
                          '--disable-dev-shm-usage', '--disable-gpu']
                )
                try:
                    page = await browser.new_page()

                    async def bloquear(route):
                        if route.request.resource_type in ('image', 'media', 'font'):
                            await route.abort()
                        else:
                            await route.continue_()

                    await page.route('**/*', bloquear)
                    await page.goto(URL, wait_until='domcontentloaded', timeout=30000)
                    await page.wait_for_selector('h3', timeout=15000)
                    await page.wait_for_timeout(1500)

                    # Corrida
                    cards = await page.evaluate(JS_CARDS)
                    vistos = set()
                    for c in cards:
                        item = parse_card(c['nome'], c['texto'])
                        if item and item['nome'] not in vistos:
                            vistos.add(item['nome'])
                            dados['corrida'].append(item)
                    dados['corrida'].sort(key=lambda x: x['pct'], reverse=True)
                    print(f"[fetch] {len(cards)} h3 encontrados, {len(dados['corrida'])} projetos com %", flush=True)

                    # Progresso geral
                    corpo = await page.inner_text('body')
                    m = re.search(r'Overall Progress[\s\S]{0,80}?(\d{1,3})\s*%', corpo)
                    if m:
                        dados['progresso_geral'] = int(m.group(1))
                    elif dados['corrida']:
                        dados['progresso_geral'] = dados['corrida'][0]['pct']
                finally:
                    await browser.close()
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Falha no navegador: {str(e)[:300]}")

    return dados


def create_progress_embed(progresso, lider=None):
    desc = f"O projeto mais próximo de ser jogável está em **{progresso}%**."
    if lider:
        desc += f"\nLíder: **{lider}**"
    embed = discord.Embed(
        title="📊 Progresso Geral — GTA 6 Recomp",
        description=desc,
        color=discord.Color.purple()
    )
    embed.set_footer(text="Fonte: gta6recomp.com • Atualiza a cada 30 minutos")
    return embed


def create_race_embed(projetos):
    embed = discord.Embed(
        title="🏁 A Corrida do GTA 6 Recomp",
        description="Classificação atual dos projetos.",
        color=discord.Color.purple()
    )
    if not projetos:
        embed.add_field(name="Nenhum projeto encontrado",
                        value="Não foi possível extrair os dados.", inline=False)
        return embed

    for i, p in enumerate(projetos[:10], start=1):
        embed.add_field(
            name=f"{i}. {p['nome']}",
            value=f"**{p['pct']}%** — {p['status']}",
            inline=False
        )
    embed.set_footer(text="Fonte: gta6recomp.com • Atualiza a cada 30 minutos")
    return embed


@tasks.loop(minutes=30)
async def update_all():
    global msg_progresso_geral, msg_corrida
    if msg_progresso_geral is None and msg_corrida is None:
        return
    try:
        dados = await fetch_all_data()
        lider = dados['corrida'][0]['nome'] if dados['corrida'] else None

        if msg_progresso_geral is not None and dados['progresso_geral'] is not None:
            try:
                await msg_progresso_geral.edit(
                    embed=create_progress_embed(dados['progresso_geral'], lider))
            except discord.NotFound:
                msg_progresso_geral = None

        if msg_corrida is not None and dados['corrida']:
            try:
                await msg_corrida.edit(embed=create_race_embed(dados['corrida']))
            except discord.NotFound:
                msg_corrida = None
    except Exception:
        traceback.print_exc()  # registra no log, mas não derruba o bot


@bot.command(name='start_monitor')
async def start_monitor(ctx):
    global msg_progresso_geral
    if msg_progresso_geral is not None:
        await ctx.send("⚠️ O monitor de progresso geral já está ativo.")
        return

    msg_espera = await ctx.send("🔎 Buscando progresso geral, aguarde (até 30 segundos)...")
    try:
        dados = await fetch_all_data()
        if dados['progresso_geral'] is None:
            await msg_espera.edit(content="❌ O navegador abriu, mas não achei o progresso geral na página.")
            return

        lider = dados['corrida'][0]['nome'] if dados['corrida'] else None
        msg_progresso_geral = await ctx.send(
            embed=create_progress_embed(dados['progresso_geral'], lider))
        await msg_espera.delete()

        if not update_all.is_running():
            update_all.start()
    except Exception as e:
        await msg_espera.edit(content=f"❌ **Erro:** `{e}`\nVerifique os Deploy Logs do Railway.")


@bot.command(name='start_race')
async def start_race(ctx):
    global msg_corrida
    if msg_corrida is not None:
        await ctx.send("⚠️ O monitor da corrida já está ativo.")
        return

    msg_espera = await ctx.send("🔎 Buscando dados da corrida, aguarde (até 30 segundos)...")
    try:
        dados = await fetch_all_data()
        if not dados['corrida']:
            await msg_espera.edit(content="❌ O navegador abriu, mas não achei a lista da corrida. O layout do site pode ter mudado.")
            return

        msg_corrida = await ctx.send(embed=create_race_embed(dados['corrida']))
        await msg_espera.delete()

        if not update_all.is_running():
            update_all.start()
    except Exception as e:
        await msg_espera.edit(content=f"❌ **Erro:** `{e}`\nVerifique os Deploy Logs do Railway.")


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
    print(f'Bot conectado como {bot.user}', flush=True)


if __name__ == '__main__':
    if not TOKEN:
        print("ERRO: Token do Discord não encontrado.")
    else:
        bot.run(TOKEN)
