import aiohttp
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Официальное API Европейского сервера Albion Online
ALBION_EU_API_URL = "https://gameinfo-ams.albiononline.com/api/gameinfo/battles/"


async def parse_battle(base_url: str) -> list[dict]:
    """
    Получает данные о бое через официальное API Albion Online.
    Это решает проблему с пагинацией, так как API отдает всех игроков сразу в формате JSON.
    """

    match = re.search(r'/battles/(\d+)', base_url)
    if not match:

        match_multi = re.search(r'ids=([\d,]+)', base_url)
        if match_multi:

            battle_id = match_multi.group(1).split(',')[0]
        else:
            logger.error("Не удалось найти ID боя в ссылке.")
            return []
    else:
        battle_id = match.group(1)

    api_url = f"{ALBION_EU_API_URL}{battle_id}"
    logger.info(f"Запрашиваем данные боя {battle_id} через API...")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка API: сервер вернул статус {resp.status}")
                    return []

                # Получаем готовый словарь из JSON
                data = await resp.json()
        except Exception as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return []


    players = []


    players_data = data.get('players', {})

    for player_id, player_info in players_data.items():
        nick = player_info.get('name')
        guild = player_info.get('guildName', '')
        alliance = player_info.get('allianceName', '')

        if nick:
            players.append({
                "nick": nick,
                "guild": guild,
                "alliance": alliance
            })

    logger.info(f"Успешно получено игроков из API: {len(players)}")
    return players