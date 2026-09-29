"""Тестирование RPC на основе модели (MBT) с помощью hypothesis.

Машина состояний RpcStateMachine одновременно выполняет случайные
последовательности вызовов через клиент RPC (сложная система) и над
упрощённой моделью ReferenceModel, после каждого шага сравнивая их
состояния. Сервер RPC запускается в отдельном потоке на свободном
порту.
"""
import socket
import threading
import time as clock

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant
from hypothesis.stateful import rule

from src import model, protocol
from src.client import RpcClient
from src.errors import NotFoundError, ProtocolError, ValidationError
from src.server import create_server
from tests.reference_model import ReferenceModel

NOW = 1_760_000_000
TIME_SPREAD = 1000
MISSING_ID_MIN = 10 ** 6
MISSING_ID_MAX = 10 ** 9
NUMBER_LIMIT = 2 ** 31
MAX_TEXT_SIZE = 12
MAX_EXTRA_BYTES = 1000
MAX_LIST_SIZE = 2
MAX_BINARY_SIZE = 40
MAX_CODE = 255

times = st.integers(NOW - TIME_SPREAD, NOW + TIME_SPREAD)
moments = st.integers(NOW - 2 * TIME_SPREAD, NOW + 2 * TIME_SPREAD)
texts = st.text(
    st.characters(exclude_categories=("Cs", "Cc", "Cn")),
    max_size=MAX_TEXT_SIZE)
numbers = st.integers(-NUMBER_LIMIT, NUMBER_LIMIT)
missing_ids = (st.integers(MISSING_ID_MIN, MISSING_ID_MAX)
               | st.integers(-MISSING_ID_MAX, 0))
not_ints = texts | st.lists(numbers, max_size=MAX_LIST_SIZE)
not_strs = numbers | st.lists(texts, max_size=MAX_LIST_SIZE)
unsupported = (st.floats() | st.binary(min_size=1)
               | st.dictionaries(texts, numbers, min_size=1))
xml_breakers = st.sampled_from(["\x00", "\x01", "\x0b", "\r", "￾"])
known_codes = st.sampled_from(sorted(protocol.OPERATION_NAMES))
unknown_codes = st.integers(0, MAX_CODE).filter(
    lambda code: code not in protocol.OPERATION_NAMES)
tables = st.sampled_from(["client", "prompt", "result"])

FIELD_KINDS = {
    "Client": {"time": int, "platform": str},
    "Prompt": {"time": int, "argument": str, "client": int, "tags": str,
               "stage": str},
    "Result": {"time": int, "result": str, "stage": str, "error": str,
               "prompt": int, "cache_hit": int},
}
WRONG_VALUES = {int: not_ints, str: not_strs}
VALID_VALUES = {int: st.none() | times, str: st.none() | texts}
FOREIGN_KEYS = ("client", "prompt")


def _valid_fields(table, optional):
    """Стратегия словаря корректных значений полей (без внешних ключей)."""
    fields = {
        name: VALID_VALUES[kind]
        for name, kind in FIELD_KINDS[table].items()
        if name not in FOREIGN_KEYS
    }
    if optional:
        return st.fixed_dictionaries({}, optional=fields)
    return st.fixed_dictionaries(fields)


def _bad_field(table):
    """Стратегия пары (поле, значение неверного типа)."""
    kinds = FIELD_KINDS[table]
    return st.sampled_from(sorted(kinds)).flatmap(
        lambda name: st.tuples(st.just(name), WRONG_VALUES[kinds[name]]))


BAD_BODIES = st.sampled_from([
    b"<query />",
    b"<request><value /></request>",
    b"<request><arg><int>1</int></arg></request>",
    b'<request><arg name="uid" /></request>',
    b'<request><arg name="uid"><float>1.5</float></arg></request>',
    b'<request><arg name="uid"><int>x</int></arg></request>',
    b'<request><arg name="uid"><int /></arg></request>',
    b'<request><arg name="extra"><none /></arg></request>',
])


def _request_header(code, length):
    """Собрать заголовок запроса с произвольным размером тела."""
    return (
        code.to_bytes(protocol.REQUEST_CODE_SIZE, protocol.BYTE_ORDER)
        + length.to_bytes(protocol.REQUEST_LENGTH_SIZE, protocol.BYTE_ORDER)
    )


def _expect(expected, method, /, *args, **kwargs):
    """Проверить, что вызов завершается исключением expected."""
    try:
        method(*args, **kwargs)
    except expected:
        return
    raise AssertionError(f"ожидалось исключение {expected.__name__}")


class RpcStateMachine(RuleBasedStateMachine):
    """Машина состояний: RPC-сервер против упрощённой модели."""

    address = None
    clients = Bundle("clients")
    prompts = Bundle("prompts")
    results = Bundle("results")

    def __init__(self):
        """Очистить хранилище сервера и подключиться к нему."""
        super().__init__()
        model.reset_storage()
        self.reference = ReferenceModel()
        self.rpc = RpcClient(*self.address)

    def teardown(self):
        """Закрыть соединение после завершения сценария."""
        self.rpc.close()

    @rule(target=clients, fields=_valid_fields("Client", optional=False))
    def create_client(self, fields):
        """Создание Client совпадает с упрощённой моделью."""
        record = self.rpc.create_client(**fields)
        assert record == self.reference.create("Client", fields)
        return record[0]

    @rule(target=prompts, client=clients,
          fields=_valid_fields("Prompt", optional=False))
    def create_prompt(self, client, fields):
        """Создание Prompt совпадает с упрощённой моделью."""
        fields = {**fields, "client": client}
        record = self.rpc.create_prompt(**fields)
        assert record == self.reference.create("Prompt", fields)
        return record[0]

    @rule(target=results, prompt=prompts,
          fields=_valid_fields("Result", optional=False))
    def create_result(self, prompt, fields):
        """Создание Result совпадает с упрощённой моделью."""
        fields = {**fields, "prompt": prompt}
        record = self.rpc.create_result(**fields)
        assert record == self.reference.create("Result", fields)
        return record[0]

    @rule(uid=clients, changes=_valid_fields("Client", optional=True))
    def update_client(self, uid, changes):
        """Изменение Client совпадает с упрощённой моделью."""
        record = self.rpc.update_client(uid, **changes)
        assert record == self.reference.update("Client", uid, changes)

    @rule(uid=prompts, changes=_valid_fields("Prompt", optional=True),
          client=clients, move=st.booleans())
    def update_prompt(self, uid, changes, client, move):
        """Изменение Prompt, в том числе перенос к другому клиенту."""
        if move:
            changes = {**changes, "client": client}
        record = self.rpc.update_prompt(uid, **changes)
        assert record == self.reference.update("Prompt", uid, changes)

    @rule(uid=results, changes=_valid_fields("Result", optional=True),
          prompt=prompts, move=st.booleans())
    def update_result(self, uid, changes, prompt, move):
        """Изменение Result, в том числе перенос к другому запросу."""
        if move:
            changes = {**changes, "prompt": prompt}
        record = self.rpc.update_result(uid, **changes)
        assert record == self.reference.update("Result", uid, changes)

    @rule(now=moments)
    def get_recent_prompts(self, now):
        """Выборка по формуле совпадает с упрощённой моделью."""
        expected = self.reference.recent_prompts(now)
        assert self.rpc.get_recent_prompts(now) == expected

    @rule(target=prompts, uid=prompts, now=moments)
    def create_duplicate_prompt(self, uid, now):
        """Копия запроса даёт повторяющуюся строку, проекция её убирает."""
        fields = self.reference.tables["Prompt"][uid]
        record = self.rpc.create_prompt(**fields)
        assert record == self.reference.create("Prompt", fields)
        expected = self.reference.recent_prompts(now)
        assert self.rpc.get_recent_prompts(now) == expected
        return record[0]

    @rule()
    def get_recent_prompts_at_current_time(self):
        """Выборка без now использует текущее время сервера."""
        result = self.rpc.get_recent_prompts()
        assert result == self.reference.recent_prompts(int(clock.time()))

    @rule(bad=_bad_field("Client"))
    def create_client_with_bad_field(self, bad):
        """Неверный тип поля при создании Client."""
        _expect(ValidationError, self.rpc.create_client, **dict([bad]))

    @rule(client=clients, bad=_bad_field("Prompt"))
    def create_prompt_with_bad_field(self, client, bad):
        """Неверный тип поля при создании Prompt."""
        fields = dict([("client", client), bad])
        _expect(ValidationError, self.rpc.create_prompt, **fields)

    @rule(prompt=prompts, bad=_bad_field("Result"))
    def create_result_with_bad_field(self, prompt, bad):
        """Неверный тип поля при создании Result."""
        fields = dict([("prompt", prompt), bad])
        _expect(ValidationError, self.rpc.create_result, **fields)

    @rule(uid=clients, bad=_bad_field("Client"))
    def update_client_with_bad_field(self, uid, bad):
        """Неверный тип поля при изменении Client."""
        _expect(ValidationError, self.rpc.update_client, uid, **dict([bad]))

    @rule(uid=prompts, bad=_bad_field("Prompt"))
    def update_prompt_with_bad_field(self, uid, bad):
        """Неверный тип поля при изменении Prompt."""
        _expect(ValidationError, self.rpc.update_prompt, uid, **dict([bad]))

    @rule(uid=results, bad=_bad_field("Result"))
    def update_result_with_bad_field(self, uid, bad):
        """Неверный тип поля при изменении Result."""
        _expect(ValidationError, self.rpc.update_result, uid, **dict([bad]))

    @rule(fields=_valid_fields("Prompt", optional=False))
    def create_prompt_without_client(self, fields):
        """Обязательное поле client не задано."""
        _expect(ValidationError, self.rpc.create_prompt, **fields)

    @rule(fields=_valid_fields("Result", optional=False))
    def create_result_without_prompt(self, fields):
        """Обязательное поле prompt не задано."""
        _expect(ValidationError, self.rpc.create_result, **fields)

    @rule(client=missing_ids)
    def create_prompt_for_missing_client(self, client):
        """Ссылка на несуществующий Client."""
        _expect(NotFoundError, self.rpc.create_prompt, client=client)

    @rule(prompt=missing_ids)
    def create_result_for_missing_prompt(self, prompt):
        """Ссылка на несуществующий Prompt."""
        _expect(NotFoundError, self.rpc.create_result, prompt=prompt)

    @rule(uid=prompts, client=missing_ids)
    def move_prompt_to_missing_client(self, uid, client):
        """Изменение ссылки Prompt на несуществующий Client."""
        _expect(NotFoundError, self.rpc.update_prompt, uid, client=client)

    @rule(uid=results, prompt=missing_ids)
    def move_result_to_missing_prompt(self, uid, prompt):
        """Изменение ссылки Result на несуществующий Prompt."""
        _expect(NotFoundError, self.rpc.update_result, uid, prompt=prompt)

    @rule(table=tables, uid=missing_ids)
    def update_missing_record(self, table, uid):
        """Изменение несуществующей записи."""
        method = getattr(self.rpc, f"update_{table}")
        _expect(NotFoundError, method, uid)

    @rule(table=tables, uid=not_ints)
    def update_with_bad_id(self, table, uid):
        """Идентификатор записи неверного типа."""
        method = getattr(self.rpc, f"update_{table}")
        _expect(ValidationError, method, uid)

    @rule(now=not_ints)
    def get_recent_prompts_with_bad_now(self, now):
        """Параметр now неверного типа."""
        _expect(ValidationError, self.rpc.get_recent_prompts, now)

    @rule(value=unsupported)
    def send_unsupported_value(self, value):
        """Значение типа, не поддерживаемого протоколом."""
        _expect(ProtocolError, self.rpc.create_client, platform=value)

    @rule(text=texts, breaker=xml_breakers)
    def send_string_invalid_in_xml(self, text, breaker):
        """Строка с символом, недопустимым в XML."""
        _expect(ProtocolError, self.rpc.create_client, platform=text + breaker)

    @rule(code=unknown_codes)
    def send_unknown_operation(self, code):
        """Неизвестный код операции."""
        request = protocol.pack_request(code, b"<request />")
        result_code, status, _ = self.rpc.send_raw(request)
        assert result_code == code
        assert status == protocol.STATUS_PROTOCOL

    @rule(code=known_codes, body=st.binary(max_size=MAX_BINARY_SIZE))
    def send_malformed_xml(self, code, body):
        """Тело запроса не является корректным XML."""
        request = protocol.pack_request(code, b"\x00" + body)
        _, status, _ = self.rpc.send_raw(request)
        assert status == protocol.STATUS_PROTOCOL

    @rule(code=known_codes, body=BAD_BODIES)
    def send_bad_request_structure(self, code, body):
        """Корректный XML с неверной структурой запроса."""
        _, status, _ = self.rpc.send_raw(protocol.pack_request(code, body))
        assert status == protocol.STATUS_PROTOCOL

    @rule(code=known_codes, extra=st.integers(1, MAX_EXTRA_BYTES))
    def send_oversized_request(self, code, extra):
        """Слишком большое тело: ошибка и закрытие соединения."""
        header = _request_header(code, protocol.MAX_BODY_SIZE + extra)
        with RpcClient(*self.address) as rpc:
            _, status, _ = rpc.send_raw(header)
            assert status == protocol.STATUS_PROTOCOL
            _expect(ConnectionError, rpc.send_raw, b"")

    @rule(code=known_codes, missing=st.integers(1, MAX_EXTRA_BYTES))
    def send_truncated_request(self, code, missing):
        """Соединение закрыто до получения всего тела запроса."""
        body = b"<request />"
        header = _request_header(code, len(body) + missing)
        with socket.create_connection(self.address) as connection:
            connection.sendall(header + body)
            connection.shutdown(socket.SHUT_WR)
            assert connection.recv(1) == b""

    @invariant()
    def tables_match_reference(self):
        """Состояние всех таблиц сервера совпадает с упрощённой моделью."""
        assert self.rpc.get_clients() == self.reference.rows("Client")
        assert self.rpc.get_prompts() == self.reference.rows("Prompt")
        assert self.rpc.get_results() == self.reference.rows("Result")


class TestRpcStateMachine(RpcStateMachine.TestCase):
    """Запуск машины состояний как набора тестов unittest."""

    settings = settings(max_examples=200, stateful_step_count=40,
                        deadline=None)

    @classmethod
    def setUpClass(cls):
        """Запустить сервер RPC в отдельном потоке."""
        super().setUpClass()
        cls.server = create_server(port=0)
        RpcStateMachine.address = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        """Остановить сервер RPC."""
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        super().tearDownClass()
