import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
from config import TOKEN
from parser import parse_battle
from db import (
    init_db, register_user, get_user_by_nick, get_user_by_discord_id,
    get_all_registered_nicks, remove_user, set_setting, get_setting,
    log_action, get_recent_logs, check_and_add_attendance, get_attendance_stats
)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree



def extract_battle_id(url: str) -> str:
    match = re.search(r'/battles/(\d+)', url)
    if match: return f"battle_{match.group(1)}"
    match_multi = re.search(r'ids=([\d,]+)', url)
    if match_multi: return f"multi_{match_multi.group(1)}"
    return f"unknown_{int(discord.utils.utcnow().timestamp())}"



class PaginationView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed]):
        super().__init__(timeout=None)
        self.embeds = embeds
        self.current_page = 0

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        await self.update_view(interaction)

    @discord.ui.button(label="Вперед ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)



@bot.event
async def on_ready():
    await init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано команд: {len(synced)}")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")
    print(f"Logged in as {bot.user}")



@tree.command(name="setup_role", description="Устанавливает роли для выдачи лута (до 3 ролей)")
@app_commands.default_permissions(manage_guild=True)
async def setup_role(interaction: discord.Interaction, role1: discord.Role, role2: discord.Role = None,
                     role3: discord.Role = None):
    roles = [str(role1.id)]
    if role2: roles.append(str(role2.id))
    if role3: roles.append(str(role3.id))

    await set_setting("loot_role_ids", ",".join(roles))
    mentions = ", ".join([f"<@&{r}>" for r in roles])

    await log_action(str(interaction.user.id), "SETUP_ROLE", f"Установлены роли: {mentions}")
    await interaction.response.send_message(f" Роли успешно установлены: {mentions}")


@tree.command(name="setup_guild_name", description="Названия гильдий для лутсплита (через |)")
@app_commands.default_permissions(manage_guild=True)
async def setup_guild_name(interaction: discord.Interaction, guilds: str):
    cleaned_guilds = "|".join([g.strip() for g in guilds.split("|")])
    await set_setting("guild_names", cleaned_guilds)

    await log_action(str(interaction.user.id), "SETUP_GUILD", f"Установлены гильдии: {cleaned_guilds}")
    await interaction.response.send_message(f" Гильдии установлены:\n`{cleaned_guilds}`")


@tree.command(name="clear_roles", description="Снимает роли лутсплита со всех")
@app_commands.default_permissions(manage_guild=True)
async def clear_roles(interaction: discord.Interaction):
    await interaction.response.defer()

    raw_role_ids = await get_setting("loot_role_ids") or await get_setting("loot_role_id")
    if not raw_role_ids:
        await interaction.followup.send(" Роли не настроены.")
        return

    role_ids = [int(r) for r in raw_role_ids.split(",")]
    roles_to_remove = [interaction.guild.get_role(r) for r in role_ids if interaction.guild.get_role(r)]

    count = 0
    for member in interaction.guild.members:
        member_roles = [r for r in member.roles if r in roles_to_remove]
        if member_roles:
            try:
                await member.remove_roles(*member_roles)
                count += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass

    await log_action(str(interaction.user.id), "CLEAR_ROLES", f"Сняты роли у {count} чел.")
    await interaction.followup.send(f" Роли сняты с **{count}** участников.")



@tree.command(name="logs", description="Показывает последние действия администраторов ")
@app_commands.default_permissions(manage_guild=True)
async def show_logs(interaction: discord.Interaction):
    logs = await get_recent_logs(15)
    if not logs:
        await interaction.response.send_message("Логи пусты.", ephemeral=True)
        return

    report = "**Последние действия (до 7 дней):**\n"
    for user_id, action, details, timestamp in logs:
        clean_time = timestamp.split(".")[0] if "." in timestamp else timestamp
        # Дискорд сделает упоминание кликабельным, а гиперссылку из [текст](url)
        report += f"`[{clean_time}]` <@{user_id}> **{action}**: {details}\n"

    await interaction.response.send_message(report, ephemeral=True)


@tree.command(name="attendance", description="Топ посещаемости контентов")
async def attendance(interaction: discord.Interaction, days: int = 7):
    total_battles, stats = await get_attendance_stats(days)

    if total_battles == 0:
        await interaction.response.send_message(f"За последние {days} дней не было спарсено ни одного боя.",
                                                ephemeral=True)
        return

    report = f"** Топ посещений за последние {days} дней:**\n"
    report += f" Всего контентов (спарсено киллборд): **{total_battles}**\n\n"

    for i, (discord_id, nick, user_battles) in enumerate(stats[:30]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
        # Высчитываем процент
        percent = int((user_battles / total_battles) * 100) if total_battles > 0 else 0
        report += f"{medal} <@{discord_id}> (`{nick}`) — **{user_battles}** ({percent}%)\n"

    await interaction.response.send_message(report)



@tree.command(name="register", description="Зарегистрировать свой ник")
async def register(interaction: discord.Interaction, nickname: str):
    discord_id = str(interaction.user.id)
    if await get_user_by_discord_id(discord_id):
        await interaction.response.send_message(" Вы уже зарегистрированы.", ephemeral=True)
        return
    if await get_user_by_nick(nickname):
        await interaction.response.send_message(" Ник уже привязан к другому аккаунту!", ephemeral=True)
        return

    await register_user(discord_id, nickname)
    try:
        await interaction.user.edit(nick=nickname)
    except discord.Forbidden:
        pass

    await interaction.response.send_message(f" Успешно зарегистрирован под ником `{nickname}`!")


@tree.command(name="register_check", description="Проверяет, зарегистрирован ли пользователь")
async def register_check(interaction: discord.Interaction, member: discord.Member):
    user = await get_user_by_discord_id(str(member.id))
    if not user:
        await interaction.response.send_message(f" {member.mention} не зарегистрирован.", ephemeral=True)
        return
    await interaction.response.send_message(f" Данный пользователь зарегистрирован под ником:\n**{user[0]}**")


@tree.command(name="reg_list", description="Показывает всех зарегистрированных пользователей")
async def reg_list(interaction: discord.Interaction):
    users = await get_all_registered_nicks()
    if not users:
        await interaction.response.send_message("В базе пока нет зарегистрированных.")
        return
    report = "**Список зарегистрированных:**\n" + "\n".join([f"• <@{did}> — `{n}`" for did, n in users])
    await interaction.response.send_message(report)


@tree.command(name="unregistered", description="Показывает участников сервера, которые не зарегистрированы")
@app_commands.default_permissions(manage_guild=True)
async def unregistered(interaction: discord.Interaction):
    await interaction.response.defer()

    registered_data = await get_all_registered_nicks()
    registered_ids = {int(did) for did, _ in registered_data}

    unregistered_members = []
    for member in interaction.guild.members:
        if not member.bot and member.id not in registered_ids:
            unregistered_members.append(member.mention)

    if not unregistered_members:
        await interaction.followup.send(" Все участники сервера зарегистрированы!")
        return

    report = f"**Не зарегистрировано: {len(unregistered_members)} чел.**\n"
    if len(unregistered_members) > 50:
        report += ", ".join(unregistered_members[:50]) + f" ...и еще {len(unregistered_members) - 50} чел."
    else:
        report += ", ".join(unregistered_members)

    await interaction.followup.send(report)


@tree.command(name="register_remove", description="Удаляет регистрацию пользователя")
@app_commands.default_permissions(manage_guild=True)
async def register_remove(interaction: discord.Interaction, member: discord.Member):
    user = await get_user_by_discord_id(str(member.id))
    if not user:
        await interaction.response.send_message(" Не зарегистрирован.", ephemeral=True)
        return

    await remove_user(str(member.id))
    await log_action(str(interaction.user.id), "REMOVE_USER", f"Удален аккаунт <@{member.id}> (Ник: {user[0]})")
    await interaction.response.send_message(f" Регистрация {member.mention} удалена.")


@tree.command(name="register_someone", description="Регистрирует другого пользователя")
@app_commands.default_permissions(manage_guild=True)
async def register_someone(interaction: discord.Interaction, member: discord.Member, nickname: str):
    if await get_user_by_discord_id(str(member.id)) or await get_user_by_nick(nickname):
        await interaction.response.send_message(" Пользователь или ник уже заняты.", ephemeral=True)
        return

    await register_user(str(member.id), nickname)
    await log_action(str(interaction.user.id), "REGISTER_OTHER", f"Зарегал <@{member.id}> как `{nickname}`")
    try:
        await member.edit(nick=nickname)
    except discord.Forbidden:
        pass
    await interaction.response.send_message(f" Зарегистрирован {member.mention} под ником `{nickname}`.")



@tree.command(name="parse", description="Спарсить киллборду и выдать роли")
async def parse(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    raw_guilds = await get_setting("guild_names")
    raw_role_ids = await get_setting("loot_role_ids") or await get_setting("loot_role_id")

    if not raw_guilds or not raw_role_ids:
        await interaction.followup.send(" Настройте гильдии (`/setup_guild_name`) и роли (`/setup_role`).")
        return

    target_guilds = [g.lower() for g in raw_guilds.split("|")]
    role_ids = [int(r) for r in raw_role_ids.split(",")]
    loot_roles = [interaction.guild.get_role(r) for r in role_ids if interaction.guild.get_role(r)]

    all_players = await parse_battle(url)
    guild_players = [p for p in all_players if p['guild'].lower() in target_guilds]

    if not guild_players:
        await interaction.followup.send(" В бою не найдено игроков из указанных гильдий.")
        return

    battle_id = extract_battle_id(url)

    # ЛОГИРОВАНИЕ С КЛИКАБЕЛЬНОЙ ССЫЛКОЙ
    await log_action(str(interaction.user.id), "PARSE", f"[Киллборда]({url}) ({len(guild_players)} чел.)")

    registered_nicks_data = await get_all_registered_nicks()
    nick_to_discord = {n.strip().lower(): str(did) for did, n in registered_nicks_data}

    player_lines = []
    given_roles_count = 0

    for p in guild_players:
        nick_lower = p['nick'].lower()
        if nick_lower in nick_to_discord:
            discord_id = nick_to_discord[nick_lower]
            is_new_attendance = await check_and_add_attendance(discord_id, battle_id)

            if is_new_attendance:
                player_lines.append(f"**{p['nick']}**\n<@{discord_id}>")
                try:
                    member = await interaction.guild.fetch_member(int(discord_id))
                    if member:
                        await member.add_roles(*loot_roles)
                        given_roles_count += 1
                except Exception as e:
                    print(f"Ошибка выдачи {p['nick']}: {e}")
            else:
                player_lines.append(f"**{p['nick']}**\n<@{discord_id}> *(Уже учтен)*")
        else:
            player_lines.append(f"**{p['nick']}**\n<@нет дискорда>")

    roles_mention = "\n".join([r.mention for r in loot_roles])

    role_embed = discord.Embed(color=discord.Color.blue())
    role_embed.description = f"**Выдана роль:**\n{roles_mention}"
    await interaction.followup.send(embed=role_embed)

    url_embed = discord.Embed(color=discord.Color.dark_theme())
    url_embed.description = f"**Игрокам ({len(guild_players)}) принимавшим участие в битве/ах:**\n{url}"
    await interaction.followup.send(embed=url_embed)

    chunk_size = 20
    embeds = []
    for i in range(0, len(player_lines), chunk_size):
        chunk = player_lines[i:i + chunk_size]
        list_embed = discord.Embed(
            description="\n\n".join(chunk),
            color=discord.Color.dark_theme()
        )
        embeds.append(list_embed)

    if len(embeds) > 1:
        view = PaginationView(embeds)
        await interaction.followup.send(embed=embeds[0], view=view)
    elif len(embeds) == 1:
        await interaction.followup.send(embed=embeds[0])


bot.run(TOKEN)