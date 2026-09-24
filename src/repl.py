"""Интерактивный режим (REPL) для модели слоя работы с данными.

Команда вводится как вызов функции модели, аргументы записываются
литералами Python. Имя now в аргументах означает текущее Unix-время,
к нему можно прибавлять и вычитать целые числа::

    model> create_client(time=now - 60, platform="linux")
    model> update_client(1, platform="macos")
    model> get_recent_prompts()

Служебные команды: help, now, exit, quit.

С ключом --remote HOST:PORT команды выполняются на сервере RPC
через клиент src.client.RpcClient.
"""
import argparse
import ast
import inspect
import sys
import time

from src import model
from src.client import RpcClient
from src.errors import ModelError, ProtocolError

PROMPT = "model> "
REMOTE_PROMPT = "rpc> "
EXIT_COMMANDS = ("exit", "quit")
COMMANDS = tuple(function.__name__ for function in model.API)


def _evaluate(node, now):
    """Вычислить значение аргумента: литерал, now или сумму/разность."""
    if isinstance(node, ast.Name) and node.id == "now":
        return now
    if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub)):
        left = _evaluate(node.left, now)
        right = _evaluate(node.right, now)
        if isinstance(node.op, ast.Add):
            return left + right
        return left - right
    return ast.literal_eval(node)


def parse_command(line, now):
    """Разобрать строку вида имя(аргументы).

    :return: кортеж (имя, позиционные аргументы, именованные аргументы).
    :raises SyntaxError, ValueError: если строка не является вызовом.
    """
    tree = ast.parse(line.strip(), mode="eval").body
    if isinstance(tree, ast.Name):
        return tree.id, [], {}
    if not isinstance(tree, ast.Call) or not isinstance(tree.func, ast.Name):
        raise ValueError("ожидается вызов функции: имя(аргументы)")
    args = [_evaluate(arg, now) for arg in tree.args]
    kwargs = {item.arg: _evaluate(item.value, now) for item in tree.keywords}
    return tree.func.id, args, kwargs


def format_result(result):
    """Преобразовать результат вызова в текст для вывода."""
    if isinstance(result, list) and not result:
        return "(нет записей)"
    if isinstance(result, list) and all(
            isinstance(row, list) for row in result):
        return "\n".join(repr(row) for row in result)
    return repr(result)


def help_text():
    """Вернуть справку по командам REPL."""
    lines = ["Функции модели:"]
    for function in model.API:
        signature = inspect.signature(function)
        summary = inspect.getdoc(function).splitlines()[0]
        lines.append(f"  {function.__name__}{signature}")
        lines.append(f"      {summary}")
    lines.append("Служебные команды: help, now, exit, quit.")
    lines.append("KEEP означает «не менять поле», now — текущее время.")
    return "\n".join(lines)


def current_time_text():
    """Вернуть текущее Unix-время в виде текста."""
    return str(int(time.time()))


SERVICE_COMMANDS = {"help": help_text, "now": current_time_text}
ERROR_FORMATS = (
    ((ModelError, ProtocolError), "Ошибка {kind}: {error}"),
    ((SyntaxError, ValueError, TypeError), "Ошибка ввода: {error}"),
    ((ConnectionError,), "Ошибка соединения: {error}"),
)
HANDLED_ERRORS = tuple(
    kind for kinds, _ in ERROR_FORMATS for kind in kinds)


def describe_error(error):
    """Вернуть текст сообщения об ошибке для пользователя."""
    for kinds, template in ERROR_FORMATS:
        if isinstance(error, kinds):
            return template.format(kind=type(error).__name__, error=error)
    return str(error)


def _call(backend, command):
    """Разобрать команду, вызвать функцию и оформить результат."""
    name, args, kwargs = parse_command(command, int(time.time()))
    if name not in COMMANDS:
        raise ValueError(f"неизвестная команда {name}, см. help")
    return format_result(getattr(backend, name)(*args, **kwargs))


def execute(backend, line):
    """Выполнить одну команду REPL и вернуть текст ответа.

    :param backend: объект с функциями модели (модуль model или
        клиент RPC).
    """
    command = line.strip()
    if command in SERVICE_COMMANDS:
        return SERVICE_COMMANDS[command]()
    if not command:
        return ""
    try:
        return _call(backend, command)
    except HANDLED_ERRORS as error:
        return describe_error(error)


def _read_line(prompt, echo):
    """Прочитать строку ввода; None — конец ввода."""
    try:
        line = input(prompt)
    except EOFError:
        print()
        return None
    if echo:
        print(line)
    return line


def run(backend, echo=False, prompt=PROMPT):
    """Запустить цикл чтения и выполнения команд.

    :param echo: печатать введённую команду (при вводе из файла).
    :param prompt: приглашение к вводу.
    """
    print("REPL модели данных. Справка: help, выход: exit.")
    line = _read_line(prompt, echo)
    while line is not None and line.strip() not in EXIT_COMMANDS:
        output = execute(backend, line)
        if output:
            print(output)
        line = _read_line(prompt, echo)


def main():
    """Точка входа: python -m src.repl."""
    parser = argparse.ArgumentParser(
        description="REPL для модели слоя работы с данными")
    parser.add_argument(
        "--remote", metavar="HOST:PORT",
        help="выполнять команды на сервере RPC")
    args = parser.parse_args()
    echo = not sys.stdin.isatty()
    if args.remote is None:
        run(model, echo)
        return
    host, _, port = args.remote.rpartition(":")
    with RpcClient(host, int(port)) as client:
        run(client, echo, REMOTE_PROMPT)


if __name__ == "__main__":
    main()
