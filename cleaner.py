import os
import json

import asyncio
from time import sleep

from pyrogram import Client
from pyrogram.raw.functions.messages import Search
from pyrogram.raw.types import InputPeerSelf, InputMessagesFilterEmpty
from pyrogram.raw.types.messages import ChannelMessages
from pyrogram.errors import FloodWait, UnknownError
from pyrogram.raw import functions

API_ID = os.getenv('API_ID', None) or int(input('Enter your Telegram API id: '))
API_HASH = os.getenv('API_HASH', None) or input('Enter your Telegram API hash: ')

app = Client("client", api_id=API_ID, api_hash=API_HASH)


class Cleaner:
    def __init__(self, chats=None, search_chunk_size=100, delete_chunk_size=100):
        self.chats = chats or []
        if search_chunk_size > 100:
            # https://github.com/gurland/telegram-delete-all-messages/issues/31
            #
            # The issue is that pyrogram.raw.functions.messages.Search uses
            # pagination with chunks of 100 messages. Might consider switching
            # to search_messages, which handles pagination transparently.
            raise ValueError('search_chunk_size > 100 not supported')
        self.search_chunk_size = search_chunk_size
        self.delete_chunk_size = delete_chunk_size

    @staticmethod
    def chunks(l, n):
        """Yield successive n-sized chunks from l.
        https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks#answer-312464"""
        for i in range(0, len(l), n):
            yield l[i:i + n]

    @staticmethod
    async def get_all_chats():        
        async with app:
            dialogs = []
            async for dialog in app.get_dialogs():
                dialogs.append(dialog.chat)
            return dialogs

    async def select_groups(self, recursive=0):
        chats = await self.get_all_chats()
        groups = [c for c in chats if c.type.name in ('GROUP', 'SUPERGROUP')]

        print('Delete all your messages in')
        for i, group in enumerate(groups):
            print(f'  {i+1}. {group.title}')

        print(
            f'  {len(groups) + 1}. '
            '(!) DELETE ALL YOUR MESSAGES IN ALL OF THOSE GROUPS (!)\n'
        )

        nums_str = input('Insert option numbers (comma separated): ')
        nums = map(lambda s: int(s.strip()), nums_str.split(','))

        for n in nums:
            if not 1 <= n <= len(groups) + 1:
                print('Invalid option selected. Exiting...')
                exit(-1)

            if n == len(groups) + 1:
                self.chats = groups
                break
            else:
                self.chats.append(groups[n - 1])
        
        groups_str = ', '.join(c.title for c in self.chats)
        print(f'\nSelected {groups_str}.\n')

        if recursive == 1:
            self.run()

    async def run(self):
        for chat in self.chats:
            chat_id = chat.id
            message_ids = []
            add_offset = 0

            while True:
                q = await self.search_messages(chat_id, add_offset)
                message_ids.extend(msg.id for msg in q)
                messages_count = len(q)
                print(f'Found {len(message_ids)} of your messages in "{chat.title}"')
                if messages_count < self.search_chunk_size:
                    break
                add_offset += self.search_chunk_size

            await self.delete_messages(chat_id=chat.id, message_ids=message_ids)
            await self.remove_my_reactions(chat_id=chat.id)

    async def delete_messages(self, chat_id, message_ids):
        print(f'Deleting {len(message_ids)} messages with message IDs:')
        print(message_ids)
        for chunk in self.chunks(message_ids, self.delete_chunk_size):
            try:
                async with app:
                    await app.delete_messages(chat_id=chat_id, message_ids=chunk)
            except FloodWait as flood_exception:
                sleep(flood_exception.x)

    async def search_messages(self, chat_id, add_offset):
        async with app:
            messages = []
            print(f'Searching messages. OFFSET: {add_offset}')
            async for message in app.search_messages(chat_id=chat_id, offset=add_offset, from_user="me", limit=100):
                messages.append(message)
            return messages

    async def remove_my_reactions(self, chat_id, limit_per_chat=1000):
        print(f"Removing my reactions in chat {chat_id} ...")
        async with app:
            count = 0
            async for message in app.get_chat_history(chat_id):

                if count >= limit_per_chat:
                    print(f"Reached limit {limit_per_chat} msg in chat {chat_id}, stopping.")
                    break

                await asyncio.sleep(0.1)
                count += 1
                reactions_obj = getattr(message, "reactions", None)
                if not reactions_obj:
                    continue

                recs = getattr(reactions_obj, "reactions", None)
                if recs is None:
                    if isinstance(reactions_obj, list):
                        recs = reactions_obj
                    else:
                        recs = []

                my_reacted = False
                for rc in recs:
                    if getattr(rc, "chosen_order", None) is not None:
                        my_reacted = True
                        break

                if not my_reacted:
                    continue

                try:
                    await app.send_reaction(chat_id=chat_id, message_id=message.id, emoji="")
                    print(f"Removed reaction from msg {message.id} in chat {chat_id}")
                    await asyncio.sleep(0.05)
                except FloodWait as e:
                    print(f"floodwait: sleeping {e.x}s")
                    await asyncio.sleep(e.x)
                except RPCError as e:
                    print(f"rpcerr from msg {message.id}: {e}")
                except Exception as e:
                    print(f"err for msg {message.id}: {e}")

async def main():
    try:
        deleter = Cleaner()
        await deleter.select_groups()
        await deleter.run()
    except UnknownError as e:
        print(f'UnknownError occured: {e}')
        print('Probably API has changed, ask developers to update this utility')


if __name__ == "__main__":
    session_file = "client.session"
    try:
        app.run(main())
    finally:
        if os.path.exists(session_file):
            os.remove(session_file)
