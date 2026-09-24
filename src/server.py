"""Сервер удалённого вызова процедур (RPC) на основе TCP.

Сервер принимает запросы по протоколу из src/protocol.py, вызывает
функции модели src/model.py и журналирует все запросы и ответы в
стандартный вывод. Одно соединение может передавать любое число
запросов подряд.
"""
import argparse
import inspect
import logging
import socketserver
import sys
import threading

from src import model, protocol
from src.errors import ModelError, ProtocolError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9090
LOGGER = logging.getLogger("rpc")
FUNCTIONS = {function.__name__: function for function in model.API}
_LOCK = threading.Lock()


def _bind(function, arguments):
    """Проверить, что аргументы подходят к сигнатуре функции."""
    try:
        inspect.signature(function).bind(**arguments)
    except TypeError as error:
        raise ProtocolError(f"неверные аргументы: {error}") from None


def dispatch(code, body):
    """Выполнить запрос и вернуть байты ответа."""
    try:
        function = FUNCTIONS[protocol.operation_name(code)]
        arguments = protocol.decode_arguments(body)
        _bind(function, arguments)
        with _LOCK:
            result = function(**arguments)
    except (ModelError, ProtocolError) as error:
        return protocol.encode_error(code, error)
    return protocol.encode_response(code, result)


def _text(body):
    """Представить тело сообщения текстом для журнала."""
    return body.decode(protocol.ENCODING, errors="replace")


def log_request(code, length, body):
    """Записать запрос в журнал."""
    name = protocol.OPERATION_NAMES.get(code, "?")
    LOGGER.info("запрос: код=%d (%s) размер=%d тело=%s",
                code, name, length, _text(body))


def log_response(data):
    """Записать ответ в журнал."""
    header = data[:protocol.RESPONSE_HEADER_SIZE]
    code, status, length = protocol.unpack_response_header(header)
    body = data[protocol.RESPONSE_HEADER_SIZE:]
    LOGGER.info("ответ: код=%d статус=%d размер=%d тело=%s",
                code, status, length, _text(body))


class RpcHandler(socketserver.StreamRequestHandler):
    """Обработчик соединения с клиентом RPC."""

    def handle(self):
        """Обрабатывать запросы, пока клиент не закроет соединение."""
        LOGGER.info("подключение %s:%d", *self.client_address)
        while self._handle_request():
            pass
        LOGGER.info("отключение %s:%d", *self.client_address)

    def _reply(self, data):
        """Отправить ответ клиенту и записать его в журнал."""
        log_response(data)
        self.wfile.write(data)

    def _handle_request(self):
        """Прочитать и выполнить один запрос.

        :return: False, если соединение нужно закрыть.
        """
        header = self.rfile.read(protocol.REQUEST_HEADER_SIZE)
        if len(header) < protocol.REQUEST_HEADER_SIZE:
            return False
        code, length = protocol.unpack_request_header(header)
        if length > protocol.MAX_BODY_SIZE:
            log_request(code, length, b"")
            error = ProtocolError(f"размер тела {length} больше допустимого")
            self._reply(protocol.encode_error(code, error))
            return False
        body = self.rfile.read(length)
        if len(body) < length:
            return False
        log_request(code, length, body)
        self._reply(dispatch(code, body))
        return True


class RpcServer(socketserver.ThreadingTCPServer):
    """Многопоточный TCP-сервер RPC."""

    allow_reuse_address = True
    daemon_threads = True


def create_server(host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Создать сервер RPC (порт 0 — выбрать свободный порт)."""
    return RpcServer((host, port), RpcHandler)


def main():
    """Точка входа: python -m src.server [--host HOST] [--port PORT].

    Журнал RPC направляется в стандартный вывод.
    """
    parser = argparse.ArgumentParser(description="Сервер RPC на основе TCP")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    with create_server(args.host, args.port) as server:
        LOGGER.info("сервер RPC запущен на %s:%d", *server.server_address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("сервер RPC остановлен")


if __name__ == "__main__":
    main()
