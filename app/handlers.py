import disnake
from disnake.ext import commands

import app.database.requests as request
from app.database.models import create_all
from datetime import datetime
from app.roles import member_has_main_role, role_update
import logging
from disnake.guild import Member, Guild
from disnake.mentions import AllowedMentions
import random
from urllib.parse import parse_qsl


logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!", help_command=None, intents=disnake.Intents.default() | disnake.Intents.members | disnake.Intents.message_content)

CHANNELS_WITH_REACTIONS = set()
# 1372570283994517584, 1372570325945942097,
# 1374057088984023050, 1374057143983931544


async def update_channels_with_reactions():
    global CHANNELS_WITH_REACTIONS
    CHANNELS_WITH_REACTIONS = await request.get_channels_ids_with_reactions()


CHANNELS_CAN_ASK_BALANCE = set()
# 1375209573526278195


async def update_channels_with_balance_ask():
    global CHANNELS_CAN_ASK_BALANCE
    CHANNELS_CAN_ASK_BALANCE = await request.get_channels_ids_with_balance_ask()


ADMIN_USERS = {
    930442023423574049,
    1110971796427132951
}


async def update_cached_values():
    await update_channels_with_reactions()
    await update_channels_with_balance_ask()


@bot.event
async def on_ready():
    await create_all()
    await update_cached_values()
    print(f"Бот {bot.user} готов к работе!")


@bot.event
async def on_raw_reaction_add(payload):
    logger.debug('on_raw_reaction_add start')
    if payload.channel_id in CHANNELS_WITH_REACTIONS and payload.emoji.name == '✅':
        guild: Guild = bot.get_guild(payload.guild_id)
        member: Member = guild.get_member(payload.user_id)
        if member and member_has_main_role(member) and payload.message_author_id != payload.user_id:
            await request.add_user_reaction(
                message_id=payload.message_id,
                message_author_id=payload.message_author_id,
                user_id=payload.user_id
            )
            logger.info(
                f'Реакция {member.name} на сообщение {payload.message_id} автора {payload.message_author_id} сохранена'
            )
        else:
            logger.info(
                f'Реакция {member.name} на сообщение {payload.message_id} автора {payload.message_author_id} игнорируется'
            )
    logger.debug('on_raw_reaction_add end')


@bot.event
async def on_raw_reaction_remove(payload):
    logger.debug('on_raw_reaction_remove start')
    if payload.channel_id in CHANNELS_WITH_REACTIONS and payload.emoji.name == '✅':
        guild: Guild = bot.get_guild(payload.guild_id)
        member: Member = guild.get_member(payload.user_id)
        if member and member_has_main_role(member) and payload.message_author_id != payload.user_id:
            await request.delete_user_reaction(
                message_id=payload.message_id,
                user_id=payload.user_id
            )
            logger.info(
                f'Реакция {member.name} на сообщение {payload.message_id} автора {payload.message_author_id} удалена'
            )
        else:
            logger.info(
                f'Реакция {member.name} на сообщение {payload.message_id} автора {payload.message_author_id} игнорируется'
            )


@bot.event
async def on_member_join(member):
    await request.add_user_balance(
        user_id=member.id,
    )


@bot.command(name='баланс', description='Показать ваш текущий баланс')
async def balance(ctx, member: disnake.Member = None):

    if ctx.channel.id not in CHANNELS_CAN_ASK_BALANCE:
        return

    if member is None:
        member = ctx.author

    user_id = member.id
    user_balance = await request.get_balance(user_id)

    await role_update(member, user_balance)

    await ctx.send(
        f"{member.mention} \n\n ✨ **Ваш баланс** ✨\n\n"
        f"🎯 Текущий баланс: **{user_balance}** 💰\n\n"
        f"🗓️ Обновлено: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"🔄 Не забудьте проверять баланс перед операциями!", delete_after=60
    )

    await ctx.message.delete()
    await role_update(member, user_balance)

transfer_text_templates = [
    '🎉 {sender} перевел {receiver} — {amount} баллов ✨',
    '🚀 {sender} — перевел {receiver} | {amount} баллов 🔥',
    '⭐️ {sender} / {receiver} — {amount} баллов 💯',
    '🎯 {sender} | перевел {receiver} — {amount} баллов 🌟',
    '🏆 {sender}: перевод для {receiver} — {amount} баллов 🎖️',
    '🔥 {sender} → {receiver} | {amount} баллов 💥',
    '🌈 {sender} | {receiver} — {amount} баллов ✨',
    '💫 {sender} (перевод) {receiver}: {amount} баллов 🚀',
    '🎈 {sender} | перевод для {receiver} — {amount} баллов 🎉',
    '🥇 {sender} — перевел {receiver} | {amount} баллов 🌟'
]


def make_successful_transfer_text(sender: str, receiver: str, amount: int) -> str:
    return random.choice(transfer_text_templates).format(sender=sender, receiver=receiver, amount=amount)


@bot.command(name='передать', description='Передать баллы другому пользователю по нику')
async def transfer(ctx: commands.Context, member_name: str, amount: int):
    sender_id = ctx.author.id
    mentioned_users = [mention for mention in ctx.message.mentions if isinstance(mention, Member)]
    if not mentioned_users or len(mentioned_users) > 1:
        await ctx.send(
            f"❌ **Ошибка!**\n\n"
            f"🚫 Требуется упомянуть одного получателя.\n\n",
            delete_after=60
        )
        await ctx.message.delete()
        return
    receiver_member: Member = mentioned_users[0]

    receiver_user_id = receiver_member.id

    # Получаем текущий баланс отправителя
    sender_balance = await request.get_balance(sender_id)
    # Получаем текущий баланс получателя (если нужно)
    receiver_balance = await request.get_balance(receiver_user_id)

    # Выполняем перевод
    success = await request.transfer_balance(sender_id, receiver_user_id, amount)

    if success:
        # Обновляем роли у отправителя (и у получателя, если нужно)
        # Передача ролей для отправителя
        await role_update(ctx.author, sender_balance-amount)
        # Передача ролей для получателя
        await role_update(receiver_member, receiver_balance+amount)
        await ctx.send(
            content=make_successful_transfer_text(ctx.author.mention, receiver_member.mention, amount),
            allowed_mentions=AllowedMentions.none()
        )
        await ctx.message.delete()
    else:
        await ctx.send(
            f"❌ **Ошибка!**\n\n"
            f"💸 Недостаточно средств для передачи.\n\n"
            f"🧾 Ваш текущий баланс: **{sender_balance}** баллов.",
            delete_after=60
        )
        await ctx.message.delete()


@bot.command(name='таблица', description='Вывести таблицу балансов')
async def table_command(ctx: commands.Context):
    if ctx.author.id not in ADMIN_USERS:
        return
    guild = ctx.message.guild
    all_balances = await request.get_all_balances()

    rows = []
    total_balance = 0 

    for user_balance in all_balances:
        member = guild.get_member(user_balance.user_id)
        if not member:
            continue
        await role_update(member, user_balance.user_balance)
        rows.append(f'{member.name}: {user_balance.user_balance}')
        total_balance += user_balance.user_balance

    rows.append(f'### Общий баланс: {total_balance}')

    await ctx.send(
        f"🧑‍🤝‍🧑 **Участники**\n\n" + '\n'.join(rows),
    )


@bot.command(name='обновитьроли', description='Обновить роли пользователей')
async def update_roles_command(ctx: commands.Context):
    if ctx.author.id not in ADMIN_USERS:
        return
    guild = ctx.message.guild
    all_balances = await request.get_all_balances()

    rows = []
    for user_balance in all_balances:
        member = guild.get_member(user_balance.user_id)
        if not member:
            continue
        report = await role_update(member, user_balance.user_balance)
        if report:
            rows.append(report)
    if rows:
        await ctx.send(
            f"**Участники**\n\n" + '\n'.join(rows)
        )
    else:
        await ctx.send(
            f"❌ Ничего не изменилось",
            delete_after=10,
        )


@bot.command(name='канал', description='Получить свойства канала')
async def show_channel_descr(ctx: commands.Context, channel_id: int):
    if ctx.author.id not in ADMIN_USERS:
        return

    channel = await request.get_channel_by_id(channel_id)
    await ctx.send(
        str(channel),
        delete_after=10,
    )


@bot.command(name='обновитьканал', description='Обновить свойства канала по ссылке')
async def update_channel(ctx: commands.Context, channel_id: int, *, arg):
    if ctx.author.id not in ADMIN_USERS:
        return
    params = dict()
    expected_keys = ['can_ask_balance', 'reactions_tracked']
    for k, v in parse_qsl(arg):
        if k in expected_keys:
            params[k] = v == '1' or v.lower() == 'true'
    channel = await request.update_channel(channel_id, **params)
    await ctx.send(
        str(channel),
        delete_after=10,
    )
    await update_cached_values()


@bot.command(name='пригласитьв', description='Обновить свойства канала по ссылке')
async def update_channel(ctx: commands.Context, thread_id: int, user_id: int):
    if ctx.author.id not in ADMIN_USERS:
        return
    thr = ctx.guild.get_thread(thread_id)
    user = ctx.guild.get_member(user_id)
    if thr:
        print(f'Приглашаю пользователя {user_id} to {thread_id}')
        await thr.add_user(user)
    else:
        await ctx.send("❌ Не найдено", delete_after=10)
