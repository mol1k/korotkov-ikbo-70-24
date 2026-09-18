"""Клиент RPC: имена методов совпадают с функциями модели на сервере."""
import socket

from src import protocol

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9090
DEFAULT_TIMEOUT = 10


class RpcClient:
    """Клиент сервера RPC.

    Методы create_*, get_* и get_recent_prompts повторяют сигнатуры
    функций модели. Методы update_* принимают идентификатор записи и
    только изменяемые поля в виде именованных аргументов, например
    update_client(1, platform="macos").

    Ошибки сервера возбуждаются на стороне клиента теми же
    исключениями: ValidationError, NotFoundError, ProtocolError.
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT,
                 timeout=DEFAULT_TIMEOUT):
        """Подключиться к серверу RPC."""
        self._socket = socket.create_connection((host, port), timeout)
        self._reader = self._socket.makefile("rb")

    def close(self):
        """Закрыть соединение с сервером."""
        self._reader.close()
        self._socket.close()

    def __enter__(self):
        """Вернуть клиент для использования в блоке with."""
        return self

    def __exit__(self, *exc_info):
        """Закрыть соединение при выходе из блока with."""
        self.close()

    def _read_exact(self, size):
        """Прочитать ровно size байт ответа."""
        data = self._reader.read(size)
        if len(data) < size:
            raise ConnectionError("сервер закрыл соединение")
        return data

    def send_raw(self, payload):
        """Отправить готовые байты запроса и прочитать ответ.

        :return: кортеж (код операции, статус, тело ответа).
        """
        self._socket.sendall(payload)
        header = self._read_exact(protocol.RESPONSE_HEADER_SIZE)
        code, status, length = protocol.unpack_response_header(header)
        return code, status, self._read_exact(length)

    def _call(self, name, **arguments):
        """Вызвать удалённую функцию и вернуть её результат."""
        request = protocol.encode_request(name, arguments)
        _, status, body = self.send_raw(request)
        return protocol.decode_response(status, body)

    def create_client(self, time=None, platform=None):
        """Создать запись Client и вернуть её."""
        return self._call("create_client", time=time, platform=platform)

    def get_clients(self):
        """Вернуть все записи Client."""
        return self._call("get_clients")

    def update_client(self, uid, **fields):
        """Изменить поля записи Client и вернуть её."""
        return self._call("update_client", uid=uid, **fields)

    def create_prompt(self, time=None, argument=None, client=None,
                      tags=None, stage=None):
        """Создать запись Prompt и вернуть её."""
        return self._call("create_prompt", time=time, argument=argument,
                          client=client, tags=tags, stage=stage)

    def get_prompts(self):
        """Вернуть все записи Prompt."""
        return self._call("get_prompts")

    def update_prompt(self, uid, **fields):
        """Изменить поля записи Prompt и вернуть её."""
        return self._call("update_prompt", uid=uid, **fields)

    def create_result(self, time=None, result=None, stage=None,
                      error=None, prompt=None, cache_hit=None):
        """Создать запись Result и вернуть её."""
        return self._call("create_result", time=time, result=result,
                          stage=stage, error=error, prompt=prompt,
                          cache_hit=cache_hit)

    def get_results(self):
        """Вернуть все записи Result."""
        return self._call("get_results")

    def update_result(self, uid, **fields):
        """Изменить поля записи Result и вернуть её."""
        return self._call("update_result", uid=uid, **fields)

    def get_recent_prompts(self, now=None):
        """Выполнить выборку по формуле варианта на сервере."""
        return self._call("get_recent_prompts", now=now)
