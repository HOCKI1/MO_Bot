import datetime
from typing import Optional
import captcha.image
import discord
from discord.ui import Button, View, Select
from discord.ext import commands, tasks
import os
import shutil
from urllib.parse import urlparse
import re
import pytz
import requests
import random
import captcha
import emoji
import translators as ts
from bs4 import BeautifulSoup
from urlextract import URLExtract
import pymongo
import io
from PIL import Image, ImageDraw, ImageChops, ImageFilter, ImageFont
from dateutil.relativedelta import relativedelta
import numpy as np
import json
import time
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import asyncio
import hashlib

app = FastAPI()

extractor = URLExtract()

intents = discord.Intents.all()

bot = discord.Bot(intents = intents, command_prefix="!")

client = pymongo.MongoClient(
    "mongodb://127.0.0.1",
    27017,
    username="user",
    password="password",
    authSource="admin"
)
events_db = client['MadOrangeBotDB']
events = events_db['Events']
votes = events_db['EventResults']

multichat_db = client['Multichat_db']
pairs = multichat_db['tg_ds_pairs']

asset_channels_db = client['ChannelsDB']
asset_channels = asset_channels_db['Channels']

# очистка и пересоздание директорий капчи
shutil.rmtree("./user_captcha", ignore_errors=True)
os.mkdir("./user_captcha")

class Message(BaseModel):
  author: str
  message: str
  message_id: int
  channel: int
  has_image: bool
  is_reply: bool
  file: Optional[str] = None
  file_name: Optional[str] = None
  original_message_id: Optional[int] = None

tg_pairs = {
   "2": 684517290691264570
}

ds_pairs = {
   "684517290691264570": 2
}

latest_cfg_upd_time = 0.0

@bot.event
async def on_ready():
    kick_newbies.start()
    check_config_updates.start()
    bot.add_view(RegBaseView(timeout=None))
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

# название кнопки для создания капчи
verify_button_name = '"Открыть каналы"'

with open("control_panel.json", "r") as f:
    settings = json.load(f)

    latest_cfg_upd_time = os.path.getctime("control_panel.json")

    task_guild_id = 645021500373598232
    give_role_id = 677410915422961706 # id роли которую нужно выдать
    rem_role_id = 742414816148324354 # id роли которую нужно убрать
    rank_role_ids = settings["rank_role_ids"]
    programms_role_ids = [*settings["programms_role_ids"], *settings["engine_role_ids"], *settings["coding_role_ids"], *settings["render_role_ids"]]
    # programms_role_ids = programms_role_ids.append(settings["engine_role_ids"])
    # programms_role_ids = programms_role_ids.append(settings["coding_role_ids"])
    # programms_role_ids = programms_role_ids.append(settings["render_role_ids"])
    napravleniya_role_ids = settings["napravleniya_role_ids"]

    minimum_rank = 1
    minimum_programms = settings["minimum_programms"]
    minimum_napravleniya = settings["minimum_napravleniya"]

    nsfw_channel_ids = [638423720465006603, 1004796774730432622]

    whitelisted_domains = settings["whitelisted_domains"]
    f.close()

# роли Madorange
@tasks.loop(seconds=5)
async def check_config_updates():
    global latest_cfg_upd_time
    if os.path.getctime("control_panel.json") > latest_cfg_upd_time:
        latest_cfg_upd_time = os.path.getctime("control_panel.json")
        f = open("control_panel.json", "r")
        settings = json.load(f)
        global minimum_programms
        minimum_programms = settings["minimum_programms"]
        global minimum_napravleniya
        minimum_napravleniya = settings["minimum_napravleniya"]
        global rank_role_ids
        rank_role_ids = settings["rank_role_ids"]
        global programms_role_ids
        programms_role_ids = settings["programms_role_ids"]
        global napravleniya_role_ids
        napravleniya_role_ids = settings["napravleniya_role_ids"],
        global whitelisted_domains
        whitelisted_domains = settings["whitelisted_domains"]
        f.close()
        me = await bot.fetch_user(344544078794457098)
        await me.send(f"Конфиг обновлен")

class RoleSelector(discord.ui.Select):
  def __init__(self, rolelists_list: list, is_roles_list: bool):
    options = []
    rolelist = rolelists_list
    placeholder = "Выберите роли"
    if is_roles_list == True:
       firstrole_name = str(rolelists_list[0].name)
       lastrole_name = str(rolelists_list[-1].name)

       placeholder = "Выберите роли (" + firstrole_name[0].upper() + "-" + lastrole_name[0].upper() + ")"
    for role in rolelist:
      options.append(discord.SelectOption(label=f"{role.name}", value=f"{role.id}", emoji=role.icon))
    super().__init__(placeholder=placeholder, min_values=0, max_values=5, options=options)
    self.rolelists_list = rolelists_list
    self.is_roles_list = is_roles_list

  async def callback(self, interaction: discord.Interaction):
    await interaction.response.defer()
    user_roles = interaction.user.roles
    
    role_rolelist = self.rolelists_list
    add_roles  = []
    remove_roles = []

    # проверяем что выбрал пользователь
    for value in self.values:
      for role in role_rolelist:
        if int(value) == role.id:
            if role not in user_roles:
                add_roles.append(role) # если у пользователя нет роли, то добавляем
            else:
                remove_roles.append(role) # если у пользователя есть роли, то убираем
            
    await interaction.user.add_roles(*add_roles)
    await interaction.user.remove_roles(*remove_roles)
    
    # пересоздаем список ролей
    view = discord.ui.View()
    view.add_item(RoleSelector(self.rolelists_list, self.is_roles_list))

    await interaction.followup.edit_message(interaction.message.id ,view=view)
    print("роли изменены")

class RegBaseView(discord.ui.View):
    @discord.ui.button(custom_id="reg_base_view", label=verify_button_name, style=discord.ButtonStyle.green)
    async def button_callback(self, button, interaction):
        try:
            # переменные ролей
            user_rank = 0
            user_programms_roles = 0
            user_napravleniya_roles = 0
            user_roles = interaction.user.roles
            
            # проверка ролей у пользователя
            for user_rank_role in user_roles:
                if str(user_rank_role.id) in str(rank_role_ids):
                    user_rank = user_rank + 1
                elif str(user_rank_role.id) in str(programms_role_ids):
                    user_programms_roles = user_programms_roles + 1
                elif str(user_rank_role.id) in str(napravleniya_role_ids):
                    user_napravleniya_roles = user_napravleniya_roles + 1

            # ранг пользователя меньше минимального
            if user_rank < minimum_rank:
                # у пользователя достаточно ролей по программам и направлениям
                if user_programms_roles >= minimum_programms and user_napravleniya_roles >= minimum_napravleniya:

                    # генерация капчи
                    captcha_view = View(timeout=None)
                    true_word = ''.join(random.sample("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 4))
                    fake_word = ''.join(random.sample("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 4))
                    fake_word2 = ''.join(random.sample("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 4))
                    captcha_words = [true_word, fake_word, fake_word2]
                    random.shuffle(captcha_words)
                    image = captcha.image.ImageCaptcha(width = 320, height = 200)
                    captcha_img = f"user_captcha/{true_word}.png"
                    image.write(true_word, captcha_img)

                    # проверка капчи
                    async def check_captcha(interaction):
                        if len(captcha_words) != 0:
                            if interaction.custom_id == true_word:
                                await interaction.user.add_roles(interaction.guild.get_role(give_role_id))
                                await interaction.user.remove_roles(interaction.guild.get_role(rem_role_id))
                                await interaction.response.send_message("### Вы успешно прошли верификацию!", ephemeral=True)
                            else:
                                await interaction.response.send_message("### Вы не прошли верификацию!", ephemeral=True)
                            captcha_words.clear()
                            os.remove("./"+captcha_img)
                        else:
                            await interaction.response.send_message("### Капча уже использована!", ephemeral=True)

                    # генерация кнопок
                    for captcha_word in captcha_words:
                        true_button = Button(label = captcha_word, style = discord.ButtonStyle.green, custom_id=captcha_word)
                        true_button.callback = check_captcha
                        captcha_view.add_item(true_button)

                    await interaction.response.send_message("### **Пожалуйста решите капчу!**\n(Нажмите на кнопку содержащую текст с картинки)", file = discord.File(captcha_img), view=captcha_view, ephemeral=True)
                # колличество ролей по программам и направлениям у пользователя меньше минимального
                elif user_napravleniya_roles < minimum_napravleniya and user_programms_roles < minimum_programms:
                    await interaction.response.send_message(f'### Возьмите пожалуйста хотя бы **ОДНУ** роль из категории "РОЛИ ПО НАПРАВЛЕНИЯМ И СФЕРАМ CG" и **ОДНУ** роль из категорий "РОЛИ ПО РАЗЛИЧНЫМ 2D И 3D ПРОГРАММАМ", "РОЛИ ПО РАЗЛИЧНЫМ ДВИЖКАМ" или "РОЛИ ПО ЯЗЫКАМ ПРОГРАММИРОВАНИЯ"\n### И нажмите на кнопку {verify_button_name}', ephemeral = True)
                # колличество ролей по программам у пользователя меньше минимального
                elif user_programms_roles < minimum_programms:
                    await interaction.response.send_message(f'### Возьмите пожалуйста хотя бы **ОДНУ** роль из категорий "РОЛИ ПО РАЗЛИЧНЫМ 2D И 3D ПРОГРАММАМ", "РОЛИ ПО РАЗЛИЧНЫМ ДВИЖКАМ" или "РОЛИ ПО ЯЗЫКАМ ПРОГРАММИРОВАНИЯ"\n### И нажмите на кнопку {verify_button_name}', ephemeral = True)
                # колличество ролей по направлениям у пользователя меньше минимального
                elif user_napravleniya_roles < minimum_napravleniya:
                    await interaction.response.send_message(f'### Возьмите пожалуйста хотя бы **ОДНУ** роль из категории "РОЛИ ПО НАПРАВЛЕНИЯМ И СФЕРАМ CG"\n### И нажмите на кнопку {verify_button_name}', ephemeral = True)
                # что-то пошло не так
                else:
                    await interaction.response.send_message(f'## Что-то пошло не так...', ephemeral = True)

            # ранг пользователя выше минимального
            elif user_rank >= minimum_rank:
                await interaction.user.remove_roles(interaction.guild.get_role(rem_role_id))
                await interaction.response.send_message("## Вы уже верифицированы!", ephemeral=True)
            # что-то пошло не так
            else:
                await interaction.response.send_message(f'## Что-то пошло не так...', ephemeral = True)
        except Exception as e:
            print(e)


# class AvatarDecorationView(discord.ui.View):
#     def __init__(self):
#         super().__init__(timeout=None)

#     @discord.ui.button()

# заход на сервер
@bot.event
async def on_member_join(member):
    try:
        new_user = await bot.fetch_user(member.id)

        user_number = member.guild.member_count
        
        # получение аватара
        try:
            user_avatar = await new_user.avatar.read()
            user_avatar = Image.open(io.BytesIO(user_avatar))
            user_avatar = user_avatar.resize((270, 270))
        
        except:
            user_avatar = await new_user.default_avatar.read()
            user_avatar = Image.open(io.BytesIO(user_avatar))
            user_avatar = user_avatar.resize((270, 270))

        user_img = Image.new('RGBA', (980, 450), (0, 0, 0, 255))

        # создание текста
        draw_text = ImageDraw.Draw(user_img)
        font1 = ImageFont.truetype('Roboto-Regular.ttf', 36)
        font2 = ImageFont.truetype('Roboto-Regular.ttf', 28)

        # расположение текста
        draw_text.text((490, 350), "Добро пожаловать на madorange", (255, 255, 255), anchor='mm', font=font1)
        draw_text.text((490, 400), f"Вы {user_number} участник", (180, 180, 180), anchor='mm', font=font2)

        # создание фона аватара
        avatar_bg = Image.new('RGBA', (270, 270), (0, 0, 0, 0))
        draw = ImageDraw.Draw(avatar_bg)
        draw.ellipse((3, 4, 267, 266), fill=(255, 255, 255, 255))
        avatar_bg = avatar_bg.filter(ImageFilter.GaussianBlur(radius=0.8))

        # расположение фона
        user_img.paste(avatar_bg, (355, 25), avatar_bg)
        
        # создание аватара
        user_avatar = user_avatar.convert(mode='RGBA')

        # создание маски
        avatar_mask = Image.open(fp = './assets/avatar_mask.png')
        avatar_mask = avatar_mask.convert(mode='RGBA')

        # создание финального аватара
        user_avatar = user_avatar.resize((242, 242), Image.Resampling.BILINEAR)
        avatar = Image.composite(image1=user_avatar, image2=avatar_mask, mask=avatar_mask)

        # расположение аватара
        user_img.paste(avatar, (369, 40), avatar)

        with io.BytesIO() as image_binary:
            user_img.save(image_binary, 'PNG')
            image_binary.seek(0)

            await new_user.send(content=
f"""
Привет, <@{member.id}> 

1. Прочитай правила в комнате "1.1.правила": https://discord.com/channels/645021500373598232/872084479097839646. 
2. Обязательно возьми роли по своим программам и направлениям в комнате "1.2.роли": https://discord.com/channels/645021500373598232/645021500373598238. 


Добро пожаловать на **madorange**, располагайся).

"""
    , file=discord.File(image_binary, f"image_{member.id}.png"))
    
    except:
        pass

    channel = member.guild.get_channel(954318071269584906)

    await member.add_roles(member.guild.get_role(742414816148324354))
    await channel.send(f"""Привет, <@{member.id}>
1. Прочитай правила в <#872084479097839646> .
2. Обязательно возьми роли по своим **программам** и **направлениям** в <#645021500373598238> .
3. Если нужна помощь, позови <@&693475672760254495>.

Добро пожаловать на **madorange**, располагайся
                       """)
    
    channel2 = member.guild.get_channel(683684101529927683)

    join_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

    years = relativedelta(datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')), member.created_at).years
    
    # print(months)
    # created = ""
    # years = 0
    # if months > 11:
    #     years = months / 12
    #     years = math.floor(years)
    #     if years > 1:
    #         created = f"{years} лет назад"
    #     else:
    #         created = f"{years} год назад"
    # else:
    #     if months > 1:
    #         created = f"{months} месяцев назад"
    #     else:
    #         created = f"{months} месяц назад"

    created = f"{years} лет назад"


    embed = discord.Embed()
    embed.set_author(name = member.name, icon_url = member.avatar.url)
    embed.color = discord.Color.green()
    embed.title = f"📥 Пользователь <@{member.id}> присоединился к серверу."
    embed.thumbnail = member.avatar.url
    embed.add_field(name="Аккаунт создан:", value = created, inline = True)
    embed.footer = discord.EmbedFooter(text = f"ID: {member.id} | Время: {join_time}")
    await channel2.send(embed = embed)

# создание списка ролей
@bot.slash_command(name = "roles", description = "Создание списка ролей", guild_ids = [645021500373598232])
@commands.has_any_role(639573026278473768, 637039225178554371, 693475672760254495, 819853217449902131)
async def roles(ctx, chunk_size: int):
  global prog_rolelist
  global engine_rolelist
  global coding_rolelist
  global render_rolelist
  global napr_rolelist
  prog_rolelist = []
  engine_rolelist = []
  coding_rolelist = []
  render_rolelist = []
  napr_rolelist = []
  global prog_rolelist_lists
  global engine_rolelist_lists
  global coding_rolelist_lists
  global render_rolelist_lists
  global napr_rolelist_lists
  prog_rolelist_lists = []
  engine_rolelist_lists = []
  coding_rolelist_lists = []
  render_rolelist_lists = []
  napr_rolelist_lists = []

  with open("control_panel.json", "r") as f:
    data = json.load(f)
    f.close()

    # print(data)

    # импорт листов ролей из файла
    prog_role_ids = data["programms_role_ids"]
    engine_role_ids = data["engine_role_ids"]
    coding_role_ids = data["coding_role_ids"]
    render_role_ids = data["render_role_ids"]
    napr_role_ids = data["napravleniya_role_ids"]
    guild = bot.get_guild(645021500373598232)

    # получение ролей
    for role_id in prog_role_ids:
      role = guild.get_role(role_id)
      prog_rolelist.append(role)
    for role_id in engine_role_ids:
      role = guild.get_role(role_id)
      engine_rolelist.append(role)
    for role_id in coding_role_ids:
      role = guild.get_role(role_id)
      coding_rolelist.append(role)
    for role_id in render_role_ids:
      role = guild.get_role(role_id)
      render_rolelist.append(role)
    for role_id in napr_role_ids:
      role = guild.get_role(role_id)
      napr_rolelist.append(role)

  # сортировка ролей по алфавиту
  prog_rolelist.sort(key=lambda x: x.name)
  engine_rolelist.sort(key=lambda x: x.name)
  coding_rolelist.sort(key=lambda x: x.name)
  render_rolelist.sort(key=lambda x: x.name)
  napr_rolelist.sort(key=lambda x: x.name)

  # разбиваем роли на списки
  prog_rolelist_lists = [prog_rolelist[i:i + chunk_size] for i in range(0, len(prog_rolelist), chunk_size)]
  engine_rolelist_lists = [engine_rolelist[i:i + chunk_size] for i in range(0, len(engine_rolelist), chunk_size)]
  coding_rolelist_lists = [coding_rolelist[i:i + chunk_size] for i in range(0, len(coding_rolelist), chunk_size)]
  render_rolelist_lists = [render_rolelist[i:i + chunk_size] for i in range(0, len(render_rolelist), chunk_size)]
  napr_rolelist_lists = [napr_rolelist[i:i + chunk_size] for i in range(0, len(napr_rolelist), chunk_size)]

      
  #роли по программам
  for i in range(0, len(prog_rolelist_lists)):
    view = View(timeout=None) 
    view.add_item(RoleSelector(prog_rolelist_lists[i], is_roles_list=True))
    if i == 0:
      await ctx.send("### Пожалуйста выберите роли по программам", view=view)
    else:
      await ctx.send(view=view)
    time.sleep(0.5)

  # Роли по движкам
  for i in range(0, len(engine_rolelist_lists)):
    view = View(timeout=None)
    view.add_item(RoleSelector(engine_rolelist_lists[i], is_roles_list=False))
    if i==0:
            await ctx.send("### Пожалуйста выберите роли по движкам", view=view)
    else:
      await ctx.send(view=view)
    time.sleep(0.5)

  # Роли по ЯП
  for i in range(0, len(coding_rolelist_lists)):
    view = View(timeout=None)
    view.add_item(RoleSelector(coding_rolelist_lists[i], is_roles_list=False))
    if i==0:
            await ctx.send("### Пожалуйста выберите роли по языкам программирования", view=view)
    else:
      await ctx.send(view=view)
    time.sleep(0.5)

  # Роли по рендерам
  for i in range(0, len(render_rolelist_lists)):
    view = View(timeout=None)
    view.add_item(RoleSelector(render_rolelist_lists[i], is_roles_list=False))
    if i==0:
            await ctx.send("### Пожалуйста выберите роли по рендерам", view=view)
    else:
      await ctx.send(view=view)
    time.sleep(0.5)
  
  # Роли по направлениям
  for i in range(0, len(napr_rolelist_lists)):
    view = View(timeout=None)
    view.add_item(RoleSelector(napr_rolelist_lists[i], is_roles_list=False))
    if i==0:
            await ctx.send("### Пожалуйста выберите роли по направлениям", view=view)
    else:
      await ctx.send(view=view)
    time.sleep(0.5)

# команда изменения ролей
@bot.slash_command(name = "change_role", description = "Изменить роли", guild_ids = [645021500373598232])
@commands.has_any_role(639573026278473768, 637039225178554371, 693475672760254495, 819853217449902131)
async def role_change(ctx: discord.ApplicationContext, change: discord.Option(str, "Что сделать с ролью?", choices = ["Добавить", "Убрать"]), role: discord.Option(discord.Role, "Роль"), category: discord.Option(str, "Категория", choices = ["Программы", "Движки", "Языки программирования", "Рендеры", "Направления"])):
  with open("test_config.json", "r+") as f:
    data = json.load(f)
    f.close()
  
  match category:
    case "Программы":
      category = "programms_role_ids"
    case "Движки":
      category = "engines_role_ids"
    case "Языки программирования":
      category = "coding_role_ids"
    case "Рендеры":
      category = "render_role_ids"
    case "Направления":
      category = "napravleniya_role_ids"

  if change == "Добавить":
    data[category].append(role.id)
    with open("test_config.json", "w") as f:
      json.dump(data, f)
      f.close()
    await ctx.respond(f"Добавил {role.id}", ephemeral=True)

  elif change == "Убрать":
    data[category].remove(role.id)
    with open("test_config.json", "w") as f:
      json.dump(data, f)
      f.close()
    await ctx.respond(f"Убрал {role.id}", ephemeral=True)

# команда для создания капчи
@bot.slash_command(name = "reg", description = "Верифицируйте себя", guild_ids = [645021500373598232])
@commands.has_any_role(639573026278473768, 637039225178554371, 693475672760254495, 819853217449902131) # роль для создания верификации 
async def reg(ctx):
    view = RegBaseView(timeout=None)
    embed = discord.Embed(
        title = "**Верификация**",
        description = f"""
Перед нажатием на кнопку "Открыть каналы" вам нужно: 
1. Взять хотя бы **ОДНУ** роль из категории "РОЛИ ПО НАПРАВЛЕНИЯМ И СФЕРАМ CG"
2. Взять хотя бы **ОДНУ** роль из категорий "РОЛИ ПО РАЗЛИЧНЫМ 2D И 3D ПРОГРАММАМ", "РОЛИ ПО РАЗЛИЧНЫМ ДВИЖКАМ" или "РОЛИ ПО ЯЗЫКАМ ПРОГРАММИРОВАНИЯ"!
3. Нажать на кнопку {verify_button_name}, чтобы создать капчу!
        """,
        color = discord.Color.green()
    )
    await ctx.send(embed=embed,view=view)

@bot.slash_command(name="free_assets", description="Бесплатные ассеты FAB")
async def free_assets(ctx):

    try:
        with open("free_assets.json", "r", encoding="utf-8") as f:
            assets = json.load(f)
    except Exception:
        return

    if not assets:
        await ctx.respond("Нет доступных ассетов.", ephemeral=True)
        return

    # Генерация хэша по списку ассетов
    asset_strings = []
    for a in assets:
        line = f"{a.get('url', '')}|{a.get('title', '')}|{a.get('image', '')}"
        asset_strings.append(line.strip().lower())

    asset_strings.sort()
    joined = "\n".join(asset_strings)
    new_hash = hashlib.sha256(joined.encode("utf-8")).hexdigest()

    # Сравнение с предыдущим хэшем
    hash_file = "free_assets_hash.txt"
    previous_hash = ""
    if os.path.exists(hash_file):
        with open(hash_file, "r") as f:
            previous_hash = f.read().strip()

    # if new_hash == previous_hash:
    #     await ctx.respond("Новых ассетов не обнаружено.", ephemeral=True)
    #     return

    # Обновляем хэш
    with open(hash_file, "w") as f:
        f.write(new_hash)

    for asset in assets:
        title = asset.get("title", "Без названия")[:40]
        url = asset.get("url", "#")
        image = asset.get("image")

        embed = discord.Embed(
            title=title,
            description="Нажмите кнопку ниже, чтобы перейти к ассету",
            color=discord.Color.from_rgb(30, 30, 30)
        )
        if image:
            embed.set_image(url=image)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Ссылка на Fab.com", url=url, emoji="🔗"))

        await ctx.respond(embed=embed, view=view, ephemeral=True)

# обработка сообщений
@bot.event
async def on_message(message):
    if message.author.bot == False:
        message_safe = 1
        # print(f"Message from {message.author}: {message.content}")
        if "https://" in message.content.lower() or "http://" in message.content.lower():
            #проверка ссылок из базы
            urls = extractor.find_urls(message.content)
            for url in urls:
                # url_domain = urlparse(url).netloc
                # # проверка на вирусы
                # req = requests.get(f"https://vms.drweb.ru/online-check-result/?lng=ru&uro=1&url={url}", headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"})
                # soup = BeautifulSoup(req.text, 'html.parser')
                # spans = soup.find_all('span')
                # if req.status_code == 200:
                #     for span in spans:
                #         if "ОПАСНОСТЬ" in span.text:
                # url = input("url: ")

                url_domain = urlparse(url).netloc
                try:
                    url_domain = url_domain.replace("www.", "")
                except:
                    pass
                print(url_domain)

                data = {
                    "Referer": "https://www.urlvoid.com/api/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 YaBrowser/24.12.0.0 Safari/537.36",
                    }
                req = requests.get(f"https://www.urlvoid.com/scan/{url_domain}/", data=json.dumps(data))

                # print(req.status_code)
                # print(req.text)

                # i = 0
                soup = BeautifulSoup(req.text, "html.parser")

                tbody = soup.find('tbody')
                tr = tbody.find_all('tr')[2]
                td = tr.find_all('td')[1]
                span = td.find('span', class_="label")

                danger_count = span.text.split("/")[0]
                danger_count = int(danger_count)
                if danger_count > 1:
                    # print(span.text)
                    print("ссылка опасна")
                    message_safe = 0
                    me = await bot.fetch_user(344544078794457098)
                    await me.send(f"{message.author.name}\n```{message.content}```")
                    await message.delete()
                    await message.delete()
                # else:
                #     print("ссылка безопасна")                  
                #     pass
                # elif url_domain in whitelisted_domains:
                #     print("ссылка безопасна")                        
                #     pass
                # else:
                #     print("ссылка опасна")
                #     message_safe = 0
                #     me = await bot.fetch_user(344544078794457098)
                #     await me.send(f"{message.author.name}\n```{message.content}```")
                #     await message.delete()

        if message_safe == 1:
            if ds_pairs.get(str(message.channel.id)) != None:
                try:
                    data = {"author": message.author.display_name, "message": message.content, "channel": message.channel.id, "message_id": message.id, "has_image": False, "is_reply": False}
                    
                    if message.attachments != []:
                        data["has_image"] = True
                        for attachment in message.attachments:
                            urls = ""
                            url = attachment.url
                            urls = urls + url + "\n"
                            data["file"] = urls

                    if message.stickers != []:
                        data["has_image"] = True
                        sticker_url = ""
                        for sticker in message.stickers:
                            sticker_url = sticker.url
                        if "https://cdn.discordapp.com" in sticker_url:
                            sticker_url = sticker_url.replace("https://cdn.discordapp.com", "https://media.discordapp.net")
                        data["file"] = sticker_url

                    if message.reference != None:
                        data["is_reply"] = True
                        repliable_message = message.reference.resolved
                        data["original_message_id"] = repliable_message.id

                    pairs.insert_one({"ds_message_id": message.id, "tg_message_id": None})

                    requests.post("http://127.0.0.1:8001/send_tg", data=json.dumps(data))

                except:
                    pass

# изменение сообщения
@bot.event
async def on_message_edit(before, after):
    if before.content != after.content:
        try:
            edit_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

            embed = discord.Embed(title=f"Сообщение изменено в канале #{before.channel.name}", color=discord.Color.blue(), url=f"https://discord.com/channels/{before.guild.id}/{before.channel.id}/{before.id}")
            embed.set_author(name=before.author.name, icon_url=before.author.avatar.url)
            embed.add_field(name="До:", value=before.content, inline=False)
            embed.add_field(name="После:", value=after.content, inline=False)
            embed.footer = discord.EmbedFooter(text=f"ID: {before.author.id} | Сегодня в {str(edit_time)}")
            await bot.get_channel(883394568886845461).send(embed=embed)
        except:
            pass

# удаление сообщения
@bot.event
async def on_message_delete(message):
    if message.author.bot == False:
        try:
            delete_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

            embed = discord.Embed(title=f"Сообщение удалено в канале #{message.channel.name}", color=discord.Color.red(), url=f"https://discord.com/channels/{message.guild.id}/{message.channel.id}")
            embed.color = discord.Color.red()
            embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
            embed.description = message.content
            embed.add_field(name="ID сообщения:", value=message.id, inline=True)
            embed.footer = discord.EmbedFooter(text=f"ID: {message.author.id} | Сегодня в {str(delete_time)}")
            await bot.get_channel(883394568886845461).send(embed=embed)
        except:
            pass

# изменение пользователя
@bot.event
async def on_user_update(before, after):
    if before.avatar != after.avatar:
        try:
            avatar_update_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

            # guild = await bot.fetch_guild(683684101529927683)
            # member = await guild.fetch_member(after.id)

            embed = discord.Embed(title = f"Пользователь <@{after.id}> обновил свой профиль!", color=discord.Color.orange())
            embed.set_author(name=after.name, icon_url=after.avatar.url)
            embed.thumbnail = after.avatar.url
            embed.add_field(name="Аватарка:", value=f"[До]({before.avatar.url})->[После]({after.avatar.url})", inline=False)
            embed.footer = discord.EmbedFooter(text=f"ID: {after.id} | Сегодня в {str(avatar_update_time)}")
            await bot.get_channel(683684101529927683).send(embed=embed)
        except:
            pass

# изменение участника
@bot.event
async def on_member_update(before, after):    
    if before.roles != after.roles:
        try:
            role_update_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")
            
            before_roles = [str(role.name) for role in before.roles]
            after_roles = [str(role.name) for role in after.roles]

            for i in before_roles[:]:
                if i in after_roles:
                    before_roles.remove(i)
                    after_roles.remove(i)

            role_name = ""
            if len(before_roles) < len(after_roles):
                for i in after_roles:
                    role_name += f"{i} "
                role_change_text = f"**✅ Добавленные роли**"
            else:
                for i in before_roles:
                    role_name += f"{i} "
                role_change_text = f"**⛔ Убранные роли**"

            embed = discord.Embed(title = f"⚔️ Обновлены роли участника <@{after.id}>!", color=discord.Color.orange())
            embed.set_author(name=after.display_name, icon_url=after.avatar.url)
            embed.thumbnail = after.avatar.url
            embed.add_field(name=role_change_text, value=f"{role_name}", inline=False)
            embed.footer = discord.EmbedFooter(text=f"ID: {after.id} | Сегодня в {str(role_update_time)}")
            await bot.get_channel(683684101529927683).send(embed=embed)
        except:
            pass
    
    if before.display_name != after.display_name:
        try:
            name_update_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

            embed = discord.Embed(title=f"👤 Обновлено имя участника <@{after.id}>!", color=discord.Color.orange())
            embed.set_author(name=after.display_name, icon_url=after.avatar.url)
            embed.thumbnail = after.avatar.url
            embed.add_field(name="До:", value=before.display_name, inline=False)
            embed.add_field(name="После:", value=after.display_name, inline=False)
            embed.footer = discord.EmbedFooter(text=f"ID: {after.id} | Сегодня в {str(name_update_time)}")
            await bot.get_channel(683684101529927683).send(embed=embed)
        except:
            pass

# выход участника
@bot.event
async def on_member_remove(member):
    try:
        leave_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

        embed = discord.Embed(title=f"📤 Участник <@{member.id}> покинул сервер!", color=discord.Color.red())
        embed.set_author(name=member.display_name, icon_url=member.avatar.url)
        embed.thumbnail = member.avatar.url
        embed.footer = discord.EmbedFooter(text=f"ID: {member.id} | Сегодня в {str(leave_time)}")
        await bot.get_channel(683684101529927683).send(embed=embed)
    except:
        pass

# бан участника
@bot.event
async def on_member_ban(member):
    try:
        ban_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

        embed = discord.Embed(title=f"🚫 Участник <@{member.id}> был забанен!", color=discord.Color.red())
        embed.set_author(name=member.display_name, icon_url=member.avatar.url)
        embed.thumbnail = member.avatar.url
        embed.add_field(name="Причина бана:", value=f"**{member.ban_reason}**", inline=False)
        embed.footer = discord.EmbedFooter(text=f"ID: {member.id} | Сегодня в {str(ban_time)}")
        await bot.get_channel(683684101529927683).send(embed=embed)
    except:
        pass

# разбан участника
@bot.event
async def on_member_unban(member):
    try:
        unban_time = datetime.datetime.now(tz=pytz.timezone('Asia/Almaty')).strftime("%H:%M")

        embed = discord.Embed(title=f"✅ Участник <@{member.id}> был разбанен!", color=discord.Color.green())
        embed.set_author(name=member.display_name, icon_url=member.avatar.url)
        embed.thumbnail = member.avatar.url
        embed.footer = discord.EmbedFooter(text=f"ID: {member.id} | Сегодня в {str(unban_time)}")
        await bot.get_channel(683684101529927683).send(embed=embed)
    except:
        pass

# получение размера члена
@bot.slash_command(name = "dick_size", description = "Узнать размер члена!", guild_ids = [645021500373598232])
async def get_dick_size(ctx):
    if ctx.channel.id in nsfw_channel_ids:
        dick_size = random.uniform(0.0,25.0)
        dick_size = round(dick_size, 1)
        dick_size_result = ""
        if dick_size < 0.1:
            dick_size_result = "У тебя он разве есть? Может ты девочка? Попробуй /boob_size"
        elif dick_size < 5.0:
            dick_size_result = "Может пилюльки попить?"
        elif dick_size < 10.0:
            dick_size_result = "Скромно, но со вкусом"
        elif dick_size < 15.0:
            dick_size_result = "Неплохо-неплохо"
        elif dick_size < 20.0:
            dick_size_result = "Любимец женщин"
        elif dick_size < 25.0:
            dick_size_result = "Догнать и перегнать Африку😂"
            
        user_nick = ctx.author.nick
        if user_nick == None:
            user_nick = ctx.author.name
        await ctx.respond(f"Размер члена {user_nick}: {dick_size} см - {dick_size_result}")

# получение размера сисек
@bot.slash_command(name = "boob_size", description = "Узнать размер сисек!", guild_ids = [645021500373598232])
async def get_boob_size(ctx):
    if ctx.channel.id in nsfw_channel_ids:
        boob_size = random.randint(0,6)
        boob_size_result = ""
        if boob_size == 0:
            boob_size_result = "AA[0] . .\nУ тебя они разве есть? Может ты мальчик? Попробуй /dick_size"
        elif boob_size == 1:
            boob_size_result = "A[1](.)(.)"
        elif boob_size == 2:
            boob_size_result = "B[2]( . )( . )"
        elif boob_size == 3:
            boob_size_result = "C[3](  .  )(  .  )"
        elif boob_size == 4:
            boob_size_result = "D[4](   .   )(   .   )"
        elif boob_size == 5:
            boob_size_result = "E[5] (    .    )(    .    )"
        elif boob_size == 6:
            boob_size_result = "F[6+] (     .     )(     .     )"
        user_nick = ctx.author.nick
        if user_nick == None:
            user_nick = ctx.author.name
        await ctx.respond(f"Размер сисек {user_nick} - {boob_size_result}")

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    
    # reacted_message = await bot.get_channel(reaction.message.channel.id).fetch_message(reaction.message.id)
    target_lang_emoji = emoji.demojize(reaction.emoji)
    message_content = reaction.message.content
    # print(message_content)
    # print(target_lang_emoji)

    if target_lang_emoji == ":Russia:":
        translated_message = ts.translate_text(message_content, to_language="ru")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":Kazakhstan:":
        translated_message = ts.translate_text(message_content, to_language="kk")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":Ukraine:":
        translated_message = ts.translate_text(message_content, to_language="uk")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":United_Kingdom:":
        translated_message = ts.translate_text(message_content, to_language="en")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":Uzbekistan:":
        translated_message = ts.translate_text(message_content, to_language="uz")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":Belarus:":
        translated_message = ts.translate_text(message_content, to_language="be")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":Poland:":
        translated_message = ts.translate_text(message_content, to_language="pl")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")
    if target_lang_emoji == ":Romania:":
        translated_message = ts.translate_text(message_content, to_language="ro")
        await reaction.message.channel.send(f"<@{user.id}>\n{str(translated_message)}")

# Регистрация на конкурс
class RegisterTeamModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="Название команды", placeholder="Введите название команды", max_length=100))
        self.add_item(discord.ui.InputText(label="Участники(до 5 человек)", placeholder="Введите ники участников команды через пробел", max_length=250))
        self.add_item(discord.ui.InputText(label="Тип работы(Комикс или Рассказ)", placeholder="Введите тип работы", max_length=20))

    async def callback(self, interaction: discord.Interaction):

        event_role_id = 940978509659131974
        event_channel_id = 999119775840092251
        if(bool(re.match('^[a-z0-9._ ]*$', str(self.children[1].value)))==False):
            error_embed = discord.Embed(
                title="Не правильно указаны никнеймы участников",
                color=discord.Color.from_rgb(255, 0, 0))
            error_embed.add_field(name="Пример ввода никнеймов участников" , value=f"`user1` или `user1 user2 user3 user4 user5`" , inline=False)
            error_embed.add_field(name="Пример никнейма участника", value=f"", inline=False)
            error_embed.set_image(url="https://media.discordapp.net/attachments/1260610554884526181/1307120134565007390/example_user_profile.png")
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return

        # print(f"Участники {self.children[1].value} состоят в команде {self.children[0].value} и делают {self.children[2].value}")
        for member in interaction.guild.members:
            if member.name in self.children[1].value:
                await member.add_roles(interaction.guild.get_role(event_role_id))
        new_team = {"team_name": f"{self.children[0].value}", "team_members": f"{self.children[1].value}", "work_type": f"{self.children[2].value}", "users_voted": []}
        events.insert_one(new_team)

        team_embed = discord.Embed(title=f'Команда "{self.children[0].value}"', color=discord.Color.from_rgb(240, 100, 30))
        event_members = self.children[1].value.split(" ")
        members_list = ""
        for member in event_members:
            members_list += f"{member}\n"
        team_embed.add_field(name="Участники", value=f"{members_list}", inline=False)
        team_embed.add_field(name="Тип работы", value=f"{self.children[2].value}", inline=False)

        await bot.get_channel(event_channel_id).send(embed=team_embed)
        await interaction.response.send_message(f'Вы успешно зарегистрировали команду "{self.children[0].value}" на конкурс!', ephemeral=True)

class RegisterTeamView(discord.ui.View):
    @discord.ui.button(label="Зарегистрировать команду", style=discord.ButtonStyle.green)
    async def button_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        author_id = interaction.user.id
        guild_member = interaction.guild.get_member(author_id)
        member_roles = guild_member.roles
        
        event_role_id = 940978509659131974

        if interaction.guild.get_role(event_role_id) in member_roles:
            await interaction.response.send_message("Вы уже зарегистрированы на конкурс!", ephemeral=True)
            return
        await interaction.response.send_modal(RegisterTeamModal(title="Регистрация команды", timeout=None))

# регистрация на конкурс
@bot.slash_command(guild_ids = [645021500373598232])
@commands.has_any_role(639573026278473768, 637039225178554371, 693475672760254495, 819853217449902131) # роль для создания
async def event_registraton_start(ctx, event_name: str, event_starts_date: str, event_ends_date: str):

    view = RegisterTeamView() #создание View
    view.timeout = None
    # f0641e

    embed = discord.Embed(title=f"Регистрация на конкурс на тему {event_name}")
    embed.add_field(name="Время проведения регистрации", value=f"{event_starts_date} - {event_ends_date}")
    await ctx.channel.send(embed=embed, view=view)

# голосовалка
@bot.slash_command(guild_ids = [645021500373598232])
@commands.has_any_role(639573026278473768, 637039225178554371, 693475672760254495, 819853217449902131) # роль для создания
async def event_voting(ctx, works_amount: int):
    view = View(timeout=None) #создание View

    embed = discord.Embed(title="Голосование за работы на конкурс")

    works_list = []
    for i in range(works_amount):
        work = votes.find_one({"work_id": f"{i+1}"})
        if work == None:
            votes.insert_one({"work_id": f"{i+1}", "users_voted_ids": "", "votes_amount": 0})
        works_list.append(discord.SelectOption(
            label=f"Работа {i+1}",
            value=f"{i+1}"
            )
        )
        i+=1

    async def works_voting_callback(interaction: discord.Interaction):
        work = votes.find_one({"work_id": f"{works_voting.values[0]}"}) #находим работу по номеру голоса
        # print(str(interaction.user.id))
        search_query = {"users_voted_ids": {"$regex": f".*{str(interaction.user.id)}.*"}}
        user_voted = votes.count_documents(search_query)
        if user_voted > 0:
            await interaction.response.send_message(f"Вы уже проголосовали", ephemeral=True)
            return
        # print(work)
        work["users_voted_ids"] += f" {interaction.user.id} "
        work["votes_amount"] += 1
        votes.update_one({"work_id": f"{works_voting.values[0]}"}, {"$set": {"users_voted_ids": work["users_voted_ids"], "votes_amount": work["votes_amount"]}})
        # print(work["votes_amount"])
        await interaction.response.send_message(f"{interaction.user.name} выбрал работу {works_voting.values[0]}", ephemeral=True)


    works_voting = Select(placeholder="Выберите работу", options=works_list, min_values=1, max_values=1)
    works_voting.callback = works_voting_callback
    view.add_item(works_voting)

    await ctx.channel.send(embed=embed, view=view)

times = [
    datetime.time(0, 0),
    datetime.time(1, 0),
    datetime.time(2, 0),
    datetime.time(3, 0),
    datetime.time(4, 0),
    datetime.time(5, 0),
    datetime.time(6, 0),
    datetime.time(7, 0),
    datetime.time(8, 0),
    datetime.time(9, 0),
    datetime.time(10, 0),
    datetime.time(11, 0),
    datetime.time(12, 0),
    datetime.time(13, 0),
    datetime.time(14, 0),
    datetime.time(15, 0),
    datetime.time(16, 0),
    datetime.time(17, 0),
    datetime.time(18, 0),
    datetime.time(19, 0),
    datetime.time(20, 0),
    datetime.time(21, 0),
    datetime.time(22, 0),
    datetime.time(23, 0)
]

@bot.slash_command(name = "birthdate_color", description = "Получить цвет из даты рождения", guild_ids = [645021500373598232])
async def date_color(ctx, full_date: str):
    if ctx.channel.id in nsfw_channel_ids:
        full_date = full_date
        date_array = list(full_date.split('.'))
        date = int(date_array[0])
        month = int(date_array[1])
        year = int(date_array[2])

        year_now = datetime.datetime.now()
        years = relativedelta(year_now, datetime.datetime(year, month, date)).years
        # print(years)

        h = int(360 * (date / 31))
        s = int(np.clip(100 * (month / 12)+100, 100, 200))
        v = int(np.clip(255 * (1 - (years / 100)) + 10, 100, 255))

        # print(h, s, v)

        image_color = Image.new('HSV', (512, 512), (int(h), int(s), int(v)))
        rgb_image_color = image_color.convert(mode="RGBA")
        orange_grayscale = Image.open('orange_grayscale.png')
        rgb_orange_grayscale = orange_grayscale.convert(mode="RGBA")
        orange_line = Image.open('orange_line.png')
        rgb_orange_line = orange_line.convert(mode="RGBA")
        colored_orange = ImageChops.multiply(rgb_image_color, rgb_orange_grayscale)

        full_colored_orange = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
        full_colored_orange.paste(colored_orange, (0, 0))
        full_colored_orange.paste(rgb_orange_line, (0, 0), rgb_orange_line)

        embed = discord.Embed(title="Цвет вашего дня рождения")
        embed.add_field(name=f"Дата рождения пользователя {ctx.interaction.user}", value=f"{full_date}", inline=False)
        embed.set_image(url=f"attachment://{full_date}_orange.png")

        # draw = ImageDraw.Draw(image_color)
        with io.BytesIO() as image_binary:
            full_colored_orange.save(image_binary, 'PNG')
            image_binary.seek(0)
            await ctx.respond(file=discord.File(image_binary, f"{full_date}_orange.png"), embed=embed)

@tasks.loop(time=times)
async def kick_newbies():
    guild = bot.get_guild(task_guild_id)
    newbie_role = guild.get_role(rem_role_id)
    me = await bot.fetch_user(344544078794457098)
    await me.send("Новокеки проверяются")
    for member in guild.members:
        member_rank = 0
        for rank_role in member.roles:
            if rank_role.id in rank_role_ids:
                member_rank += 1
        # print(f"{member.name} {datetime.datetime.now(datetime.timezone.utc) - member.joined_at} {len(member.roles)}")
        if newbie_role in member.roles and member_rank < minimum_rank and datetime.datetime.now(datetime.timezone.utc) - member.joined_at >= datetime.timedelta(days=14):
            # print(f"{member.name} {member_rank} {datetime.datetime.now(datetime.timezone.utc) - member.joined_at} {member_rank}")
            try:
                # print(f"Кикнул {member.name}")
                await member.kick(reason="Вы не прошли верификацию в течение 14 дней!")
                await me.send(f"Кикнул {member.name}")
            except:
                pass
        elif newbie_role in member.roles and member_rank >= minimum_rank and datetime.datetime.now(datetime.timezone.utc) - member.joined_at >= datetime.timedelta(days=14):
            # print(f"{member.name} {member_rank} {datetime.datetime.now(datetime.timezone.utc) - member.joined_at} {member_rank}")
            try:
                rem_role = guild.get_role(rem_role_id)
                # print(f"Снял роль {rem_role.name} у {member.name}")
                await member.remove_roles(rem_role)
            except:
                pass

times = [datetime.time(hour=h, minute=2, tzinfo=datetime.timezone.utc) for h in range(24)]

previous_assets_hash = ""

@tasks.loop(time=times)
async def check_free_assets_updates():
    global previous_assets_hash

    try:
        if not os.path.exists("free_assets.json"):
            print("Файл free_assets.json не найден.")
            return

        with open("free_assets.json", "r", encoding="utf-8") as f:
            assets = json.load(f)

        if not assets:
            print("Файл пустой или не содержит ассетов.")
            return

        # Хэш по содержимому
        hash_strings = [
            f"{a.get('url', '')}|{a.get('title', '')}|{a.get('image', '')}".strip().lower()
            for a in assets
        ]
        hash_strings.sort()
        joined = "\n".join(hash_strings)
        current_hash = hashlib.sha256(joined.encode("utf-8")).hexdigest()

        if current_hash == previous_assets_hash:
            print("Новых ассетов нет.")
            return

        # Сохраняем хэш
        previous_assets_hash = current_hash
        print("Обнаружены новые ассеты — отправляем уведомления.")

        # Формирование Embed и View
        embed = discord.Embed(
            title="Новые бесплатные ассеты FAB",
            description="**Нажмите на кнопки ниже для получения бесплатных ассетов**",
            color=discord.Color.from_rgb(30, 30, 30)
        )
        embed.set_footer(
            text="Поддержать разработчика: https://www.buymeacoffee.com/makskraft",
            icon_url="https://media.discordapp.net/attachments/1260610554884526181/1338386349102858240/buy-me-a-coffee-logo-F1878A1EB2-seeklogo.com.png?ex=67aae4eb&is=67a9936b&hm=5373ddeac1e1f8a16650b0ffa5dd110d0545a86c9601d7560bcd94e0d7b6351e&=&format=webp&quality=lossless&width=227&height=330"
        )

        if assets[0].get("image"):
            embed.set_thumbnail(url=assets[0]["image"])

        view = discord.ui.View()
        for asset in assets:
            view.add_item(discord.ui.Button(
                label=asset.get("title", "Без названия")[:80],
                url=asset.get("url", "#"),
                emoji="🔗"
            ))

        # Рассылка в каналы
        channels = asset_channels_db["Channels"]
        for channel_item in channels.find():
            channel = bot.get_channel(channel_item["channel_id"])
            if channel:
                await channel.send(embed=embed, view=view)

    except Exception as e:
        print(f"Ошибка при проверке ассетов: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(bot.start("TOKEN"))

@app.post("/send_ds")
async def send_ds(message: Message):
    # print(message)
    channel_id = tg_pairs[str(message.channel)]
    get_channel = await bot.fetch_channel(channel_id)
    file = None
    if message.has_image == True:
        file = discord.File(io.BytesIO(bytes.fromhex(message.file)), filename=message.file_name)
       
    if message.is_reply == True:
        original_ds_message = pairs.find_one({"tg_message_id": message.original_message_id})
        if original_ds_message != None:
            ds_message = await get_channel.fetch_message(original_ds_message["ds_message_id"])
            if file == None:
                new_ds_message = await ds_message.reply(f"**{message.author}**\n{message.message}")
                pairs.update_one({"tg_message_id": message.message_id}, {"$set": {"ds_message_id": new_ds_message.id}})
            else:
                new_ds_message = await ds_message.reply(f"**{message.author}**\n{message.message}", file=file)
                pairs.update_one({"tg_message_id": message.message_id}, {"$set": {"ds_message_id": new_ds_message.id}})
    
    elif message.is_reply == False:
        if file == None:
            new_ds_message = await get_channel.send(f"**{message.author}**\n{message.message}")
            pairs.update_one({"tg_message_id": message.message_id}, {"$set": {"ds_message_id": new_ds_message.id}})
        else:
            new_ds_message = await get_channel.send(f"**{message.author}**\n{message.message}", file=file)
            pairs.update_one({"tg_message_id": message.message_id}, {"$set": {"ds_message_id": new_ds_message.id}})

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
