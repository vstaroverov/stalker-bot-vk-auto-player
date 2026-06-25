import time
import random
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType


class VKClient:
    def __init__(self, token: str, peer_id: int):
        self.peer_id = peer_id
        session = vk_api.VkApi(token=token)
        self.vk = session.get_api()
        self.longpoll = VkLongPoll(session)

    def listen(self, is_running):
        for event in self.longpoll.listen():
            if not is_running():
                break

            if event.type == VkEventType.MESSAGE_NEW and not event.from_me:
                if event.peer_id == self.peer_id:
                    try:
                        result = self.vk.messages.getById(message_ids=event.message_id)
                        if result['items']:
                            msg = result['items'][0]
                            text = msg.get('text', '')
                            buttons = self._extract_buttons(msg)
                            photo_url = self._extract_photo(msg)
                            yield text, buttons, photo_url
                    except Exception as e:
                        yield f"[Ошибка получения сообщения: {e}]", [], None

    def _extract_buttons(self, message: dict) -> list:
        keyboard = message.get('keyboard', {})
        buttons = []
        for row in keyboard.get('buttons', []):
            for btn in row:
                action = btn.get('action', {})
                btn_type = action.get('type', 'text')
                label = action.get('label', '')
                if label and btn_type in ('text', 'callback'):
                    buttons.append({'label': label, 'type': btn_type, 'payload': action.get('payload', '')})
        return buttons

    def _extract_photo(self, message: dict) -> str | None:
        for att in message.get('attachments', []):
            if att.get('type') == 'photo':
                photo = att['photo']
                sizes = photo.get('sizes', [])
                if sizes:
                    # Берём самый большой размер
                    best = max(sizes, key=lambda s: s.get('width', 0) * s.get('height', 0))
                    return best.get('url')
        return None

    def send_message(self, text: str):
        delay = random.uniform(3, 9)
        time.sleep(delay)
        self.vk.messages.send(
            peer_id=self.peer_id,
            message=text,
            random_id=random.randint(1, 2 ** 31)
        )
