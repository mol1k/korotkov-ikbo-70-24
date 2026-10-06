"""Протокол удалённого вызова процедур (вариант 7, таблица 7).

Структура запроса::

    код операции (1 байт) | размер тела (5 байт) | тело в формате XML

Структура ответа::

    код операции (2 байта) | размер тела (4 байта) | тело в формате XML

Числа в заголовках записываются от младшего байта к старшему.
Младший байт кода операции в ответе повторяет код операции запроса,
старший байт содержит статус выполнения (STATUS_*).

Тело запроса::

    <request><arg name="platform"><str>linux</str></arg></request>

Тело ответа::

    <response><list><int>1</int><none/><str>linux</str></list></response>
    <response><error>текст ошибки</error></response>
"""
import re
from xml.etree.ElementTree import (
    Element, ParseError, SubElement, fromstring, tostring)

from src.errors import NotFoundError, ProtocolError, ValidationError

BYTE_ORDER = "little"
ENCODING = "utf-8"
REQUEST_CODE_SIZE = 1
REQUEST_LENGTH_SIZE = 5
REQUEST_HEADER_SIZE = REQUEST_CODE_SIZE + REQUEST_LENGTH_SIZE
RESPONSE_CODE_SIZE = 2
RESPONSE_LENGTH_SIZE = 4
RESPONSE_HEADER_SIZE = RESPONSE_CODE_SIZE + RESPONSE_LENGTH_SIZE
MAX_BODY_SIZE = 1024 * 1024
VALUES_PER_ARGUMENT = 1

OPERATIONS = (
    "create_client", "get_clients", "update_client",
    "create_prompt", "get_prompts", "update_prompt",
    "create_result", "get_results", "update_result",
    "get_recent_prompts",
)
OPCODES = {name: code for code, name in enumerate(OPERATIONS, start=1)}
OPERATION_NAMES = {code: name for name, code in OPCODES.items()}

STATUS_OK = 0
STATUS_VALIDATION = 1
STATUS_NOT_FOUND = 2
STATUS_PROTOCOL = 3
ERROR_STATUSES = {
    ValidationError: STATUS_VALIDATION,
    NotFoundError: STATUS_NOT_FOUND,
    ProtocolError: STATUS_PROTOCOL,
}
STATUS_ERRORS = {status: error for error, status in ERROR_STATUSES.items()}
STATUS_SHIFT = 8
CODE_MASK = 0xFF

_XML_TEXT = re.compile(
    "[\t\n\x20-퟿-�\U00010000-\U0010ffff]*")


def operation_name(code):
    """Вернуть имя функции модели по коду операции.

    :raises ProtocolError: если код операции неизвестен.
    """
    name = OPERATION_NAMES.get(code)
    if name is None:
        raise ProtocolError(f"неизвестный код операции {code}")
    return name


def _text_element(tag, text):
    """Создать элемент XML с текстом."""
    element = Element(tag)
    element.text = text
    return element


def _encode_none(value):
    """Закодировать None."""
    return Element("none")


def _encode_int(value):
    """Закодировать целое число."""
    return _text_element("int", str(value))


def _encode_str(value):
    """Закодировать строку, допустимую в XML."""
    if not _XML_TEXT.fullmatch(value):
        raise ProtocolError("строка содержит символы, недопустимые в XML")
    return _text_element("str", value)


def _encode_list(value):
    """Закодировать список значений."""
    element = Element("list")
    element.extend(value_to_xml(item) for item in value)
    return element


ENCODERS = {
    type(None): _encode_none,
    int: _encode_int,
    str: _encode_str,
    list: _encode_list,
    tuple: _encode_list,
}


def value_to_xml(value):
    """Преобразовать значение (None, int, str, list) в элемент XML.

    :raises ProtocolError: если тип значения не поддерживается.
    """
    encoder = ENCODERS.get(type(value))
    if encoder is None:
        raise ProtocolError(
            f"тип {type(value).__name__} не поддерживается протоколом")
    return encoder(value)


def _parse_int(text):
    """Преобразовать текст элемента <int> в число."""
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ProtocolError(f"некорректное целое число {text!r}") from None


DECODERS = {
    "none": lambda element: None,
    "int": lambda element: _parse_int(element.text),
    "str": lambda element: element.text or "",
    "list": lambda element: [xml_to_value(child) for child in element],
}


def xml_to_value(element):
    """Преобразовать элемент XML в значение Python.

    :raises ProtocolError: если элемент имеет неизвестный тег.
    """
    decoder = DECODERS.get(element.tag)
    if decoder is None:
        raise ProtocolError(f"неизвестный тип значения <{element.tag}>")
    return decoder(element)


def _parse(body):
    """Разобрать тело сообщения в формате XML."""
    try:
        return fromstring(body)
    except ParseError as error:
        raise ProtocolError(f"некорректный XML: {error}") from None


def _to_bytes(root):
    """Сериализовать элемент XML в байты UTF-8."""
    return tostring(root, encoding=ENCODING)


def pack_request(code, body):
    """Собрать запрос из кода операции и тела."""
    return (
        code.to_bytes(REQUEST_CODE_SIZE, BYTE_ORDER)
        + len(body).to_bytes(REQUEST_LENGTH_SIZE, BYTE_ORDER)
        + body
    )


def unpack_request_header(header):
    """Разобрать заголовок запроса.

    :return: кортеж (код операции, размер тела).
    """
    code = int.from_bytes(header[:REQUEST_CODE_SIZE], BYTE_ORDER)
    length = int.from_bytes(header[REQUEST_CODE_SIZE:], BYTE_ORDER)
    return code, length


def encode_request(name, arguments):
    """Закодировать вызов функции name с именованными аргументами."""
    root = Element("request")
    for key, value in arguments.items():
        argument = SubElement(root, "arg", name=key)
        argument.append(value_to_xml(value))
    return pack_request(OPCODES[name], _to_bytes(root))


def decode_arguments(body):
    """Получить именованные аргументы из тела запроса.

    :raises ProtocolError: если тело не соответствует формату.
    """
    root = _parse(body)
    if root.tag != "request":
        raise ProtocolError("корневой элемент запроса должен быть <request>")
    arguments = {}
    for argument in root:
        name = argument.get("name")
        if (argument.tag != "arg" or name is None
                or len(argument) != VALUES_PER_ARGUMENT):
            raise ProtocolError(
                "аргумент должен иметь вид <arg name=\"...\">значение</arg>")
        arguments[name] = xml_to_value(argument[0])
    return arguments


def _pack_response(code, status, root):
    """Собрать ответ из кода операции, статуса и тела."""
    body = _to_bytes(root)
    full_code = (code & CODE_MASK) | (status << STATUS_SHIFT)
    return (
        full_code.to_bytes(RESPONSE_CODE_SIZE, BYTE_ORDER)
        + len(body).to_bytes(RESPONSE_LENGTH_SIZE, BYTE_ORDER)
        + body
    )


def encode_response(code, value):
    """Закодировать успешный ответ со значением value."""
    root = Element("response")
    root.append(value_to_xml(value))
    return _pack_response(code, STATUS_OK, root)


def encode_error(code, error):
    """Закодировать ответ с ошибкой модели или протокола."""
    root = Element("response")
    SubElement(root, "error").text = str(error)
    return _pack_response(code, ERROR_STATUSES[type(error)], root)


def unpack_response_header(header):
    """Разобрать заголовок ответа.

    :return: кортеж (код операции, статус, размер тела).
    """
    full_code = int.from_bytes(header[:RESPONSE_CODE_SIZE], BYTE_ORDER)
    length = int.from_bytes(header[RESPONSE_CODE_SIZE:], BYTE_ORDER)
    return full_code & CODE_MASK, full_code >> STATUS_SHIFT, length


def decode_response(status, body):
    """Получить результат из тела ответа.

    :raises ModelError, ProtocolError: если сервер вернул ошибку.
    """
    element = _parse(body)[0]
    if status == STATUS_OK:
        return xml_to_value(element)
    raise STATUS_ERRORS[status](element.text)
