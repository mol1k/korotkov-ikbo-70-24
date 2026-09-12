"""Модель слоя работы с данными (вариант 7).

Данные хранятся только в памяти. Таблицы Client, Prompt и Result
соответствуют ER-диаграмме варианта. Каждая запись таблицы
представлена списком значений в порядке столбцов диаграммы, таблица
представлена списком таких записей.

Столбцы таблиц:

* Client: id, time, platform;
* Prompt: id, time, argument, client, tags, stage;
* Result: id, time, result, stage, error, prompt, cache_hit.

Поля id, Prompt.client и Result.prompt обязательные, остальные поля
могут иметь значение None. Поле time хранит Unix-время в секундах.
"""
import time as clock
from typing import NamedTuple

from src.errors import NotFoundError, ValidationError

RECENT_WINDOW_SECONDS = 7 * 60


class Column(NamedTuple):
    """Описание столбца таблицы."""

    name: str
    kind: type
    required: bool = False
    reference: str | None = None


class _Keep:
    """Тип маркера «оставить значение поля без изменений»."""

    def __repr__(self):
        """Вернуть имя маркера для отображения в подсказках."""
        return "KEEP"


KEEP = _Keep()

SCHEMA = {
    "Client": (
        Column("id", int, required=True),
        Column("time", int),
        Column("platform", str),
    ),
    "Prompt": (
        Column("id", int, required=True),
        Column("time", int),
        Column("argument", str),
        Column("client", int, required=True, reference="Client"),
        Column("tags", str),
        Column("stage", str),
    ),
    "Result": (
        Column("id", int, required=True),
        Column("time", int),
        Column("result", str),
        Column("stage", str),
        Column("error", str),
        Column("prompt", int, required=True, reference="Prompt"),
        Column("cache_hit", int),
    ),
}

_tables = {name: [] for name in SCHEMA}
_next_ids = {name: 1 for name in SCHEMA}


def reset_storage():
    """Очистить все таблицы и сбросить счётчики идентификаторов.

    Служебная функция для тестов, не входит в API модели и не
    доступна через RPC.
    """
    for name in SCHEMA:
        _tables[name].clear()
        _next_ids[name] = 1


def _check_value(name, value, kind, required):
    """Проверить тип значения поля.

    :raises ValidationError: если тип значения недопустим.
    """
    if value is None and not required:
        return
    if type(value) is not kind:
        raise ValidationError(
            f"поле {name}: ожидается {kind.__name__}, "
            f"получено {type(value).__name__}"
        )


def _find(table, uid):
    """Найти запись таблицы по идентификатору.

    :raises ValidationError: если идентификатор не целое число.
    :raises NotFoundError: если записи с таким id нет.
    """
    _check_value("id", uid, int, True)
    for record in _tables[table]:
        if record[0] == uid:
            return record
    raise NotFoundError(f"{table}: запись с id={uid} не найдена")


def _validate(table, record):
    """Проверить типы полей записи и ссылки на другие таблицы."""
    for column, value in zip(SCHEMA[table], record):
        _check_value(column.name, value, column.kind, column.required)
        if column.reference is not None:
            _find(column.reference, value)


def _create(table, values):
    """Добавить в таблицу новую запись и вернуть её копию."""
    record = [_next_ids[table], *values]
    _validate(table, record)
    _tables[table].append(record)
    _next_ids[table] += 1
    return list(record)


def _all(table):
    """Вернуть копии всех записей таблицы."""
    return [list(record) for record in _tables[table]]


def _update(table, uid, values):
    """Изменить поля записи, значения KEEP оставить прежними."""
    record = _find(table, uid)
    updated = [record[0]]
    for old, new in zip(record[1:], values):
        updated.append(old if new is KEEP else new)
    _validate(table, updated)
    record[:] = updated
    return list(record)


def create_client(time=None, platform=None):
    """Создать запись Client и вернуть её."""
    return _create("Client", (time, platform))


def get_clients():
    """Вернуть все записи Client."""
    return _all("Client")


def update_client(uid, time=KEEP, platform=KEEP):
    """Изменить запись Client с идентификатором uid и вернуть её."""
    return _update("Client", uid, (time, platform))


def create_prompt(time=None, argument=None, client=None, tags=None,
                  stage=None):
    """Создать запись Prompt и вернуть её.

    Поле client обязательно и должно ссылаться на существующий Client.
    """
    return _create("Prompt", (time, argument, client, tags, stage))


def get_prompts():
    """Вернуть все записи Prompt."""
    return _all("Prompt")


def update_prompt(uid, time=KEEP, argument=KEEP, client=KEEP, tags=KEEP,
                  stage=KEEP):
    """Изменить запись Prompt с идентификатором uid и вернуть её."""
    values = (time, argument, client, tags, stage)
    return _update("Prompt", uid, values)


def create_result(time=None, result=None, stage=None, error=None,
                  prompt=None, cache_hit=None):
    """Создать запись Result и вернуть её.

    Поле prompt обязательно и должно ссылаться на существующий Prompt.
    """
    values = (time, result, stage, error, prompt, cache_hit)
    return _create("Result", values)


def get_results():
    """Вернуть все записи Result."""
    return _all("Result")


def update_result(uid, time=KEEP, result=KEEP, stage=KEEP, error=KEEP,
                  prompt=KEEP, cache_hit=KEEP):
    """Изменить запись Result с идентификатором uid и вернуть её."""
    values = (time, result, stage, error, prompt, cache_hit)
    return _update("Result", uid, values)


def get_recent_prompts(now=None):
    """Выборка по формуле реляционной алгебры варианта 7.

    pi[C.platform, P.argument]((sigma[C.time >= now - 7 min] C)
    правое внешнее соединение [C.id = P.client] P)

    Сохраняются все записи Prompt. Если клиент записи не попал в
    выборку sigma, поле platform принимает значение None. Проекция
    удаляет повторяющиеся строки, как принято в реляционной алгебре.

    :param now: момент времени (Unix-время в секундах), по умолчанию
        текущее время.
    :return: список строк [platform, argument].
    """
    if now is None:
        now = int(clock.time())
    _check_value("now", now, int, True)
    border = now - RECENT_WINDOW_SECONDS
    recent = {
        client[0]: client for client in _tables["Client"]
        if client[1] is not None and client[1] >= border
    }
    rows = []
    for prompt in _tables["Prompt"]:
        client = recent.get(prompt[3])
        row = [None if client is None else client[2], prompt[2]]
        if row not in rows:
            rows.append(row)
    return rows


API = (
    create_client, get_clients, update_client,
    create_prompt, get_prompts, update_prompt,
    create_result, get_results, update_result,
    get_recent_prompts,
)
